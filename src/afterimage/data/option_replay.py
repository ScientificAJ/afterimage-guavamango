from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReplayError(ValueError):
    pass


class ReplayLegQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: str
    side: Literal["buy", "sell"]
    bid: Decimal = Field(ge=0)
    ask: Decimal = Field(gt=0)
    timestamp: datetime


class ReplayFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    timestamp: datetime
    legs: tuple[ReplayLegQuote, ...]


class ReplayOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    entry_debit: Decimal
    exit_value: Decimal
    profit: Decimal
    return_r: Decimal
    outcome: Literal["target_first", "stop_first", "time_exit", "censored"]
    entry_at: datetime
    exit_at: datetime
    modeled_costs: Decimal
    pricing_policy: str = "long_at_ask_short_at_bid"
    path: tuple[Decimal, ...]


class OptionReplay:
    def __init__(
        self,
        maximum_leg_skew_seconds: int = 1,
        maximum_quote_age_seconds: int = 2,
        fee_per_contract: Decimal = Decimal("0.00"),
        slippage_per_leg: Decimal = Decimal("0.01"),
    ) -> None:
        self.maximum_leg_skew_seconds = maximum_leg_skew_seconds
        self.maximum_quote_age_seconds = maximum_quote_age_seconds
        self.fee_per_contract = fee_per_contract
        self.slippage_per_leg = slippage_per_leg

    def _validate_frame(self, frame: ReplayFrame) -> None:
        if not frame.legs:
            raise ReplayError("MISSING_LEGS")
        timestamps = [leg.timestamp for leg in frame.legs]
        if any(leg.ask <= leg.bid or leg.bid <= 0 for leg in frame.legs):
            raise ReplayError("CROSSED_OR_ONE_SIDED_QUOTE")
        if (max(timestamps) - min(timestamps)).total_seconds() > self.maximum_leg_skew_seconds:
            raise ReplayError("LEG_TIMESTAMP_SKEW")
        if any(
            abs((frame.timestamp - ts).total_seconds()) > self.maximum_quote_age_seconds
            for ts in timestamps
        ):
            raise ReplayError("STALE_QUOTE")

    def _entry_debit(self, frame: ReplayFrame) -> Decimal:
        self._validate_frame(frame)
        total = Decimal(0)
        for leg in frame.legs:
            price = (
                leg.ask + self.slippage_per_leg
                if leg.side == "buy"
                else leg.bid - self.slippage_per_leg
            )
            total += price if leg.side == "buy" else -price
        return total

    def _exit_value(self, frame: ReplayFrame) -> Decimal:
        self._validate_frame(frame)
        total = Decimal(0)
        for leg in frame.legs:
            price = (
                leg.bid - self.slippage_per_leg
                if leg.side == "buy"
                else leg.ask + self.slippage_per_leg
            )
            total += price if leg.side == "buy" else -price
        return total

    def first_passage(
        self,
        frames: Sequence[ReplayFrame],
        target_profit: Decimal,
        stop_loss: Decimal,
        quantity: int = 1,
    ) -> ReplayOutcome:
        if not frames:
            raise ReplayError("NO_QUOTES")
        ordered = sorted(frames, key=lambda frame: frame.timestamp)
        entry = self._entry_debit(ordered[0])
        contracts = len(ordered[0].legs) * quantity
        costs = (self.fee_per_contract * contracts + self.slippage_per_leg * contracts) * Decimal(
            100
        )
        risk = abs(stop_loss)
        path: list[Decimal] = []
        selected = ordered[-1]
        outcome: Literal["target_first", "stop_first", "time_exit", "censored"] = "time_exit"
        for frame in ordered[1:]:
            value = self._exit_value(frame)
            profit = (value - entry) * Decimal(quantity * 100) - costs
            path.append(profit)
            if profit >= target_profit:
                selected, outcome = frame, "target_first"
                break
            if profit <= -abs(stop_loss):
                selected, outcome = frame, "stop_first"
                break
        exit_value = self._exit_value(selected)
        profit = (exit_value - entry) * Decimal(quantity * 100) - costs
        return ReplayOutcome(
            entry_debit=entry,
            exit_value=exit_value,
            profit=profit,
            return_r=profit / risk if risk else Decimal(0),
            outcome=outcome,
            entry_at=ordered[0].timestamp,
            exit_at=selected.timestamp,
            modeled_costs=costs,
            path=tuple(path),
        )
