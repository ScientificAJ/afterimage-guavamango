"""Causal next-bar simulator shared by event/flow candidate families."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Costs:
    slippage_bps: Decimal = Decimal(1)
    fee_per_share_per_side: Decimal = Decimal("0.005")

    @property
    def slippage_fraction(self) -> Decimal:
        return self.slippage_bps / Decimal(10000)


@dataclass(frozen=True)
class Signal:
    symbol: str
    completed_at: datetime
    direction: Literal[-1, 1]
    family: str
    variant: str


@dataclass(frozen=True)
class StrategyParameters:
    stop_fraction: Decimal = Decimal("0.002")
    max_holding_bars: int = 8
    notional: Decimal = Decimal(10000)


@dataclass(frozen=True)
class Trade:
    family: str
    variant: str
    symbol: str
    direction: int
    signal_at: datetime
    entry_at: datetime
    exit_at: datetime
    raw_entry: Decimal
    entry_fill: Decimal
    stop_price: Decimal
    target_price: Decimal
    raw_exit: Decimal
    exit_fill: Decimal
    shares: int
    net_pnl: Decimal
    risk_dollars: Decimal
    return_r: Decimal
    outcome: Literal["target", "stop", "time"]
    target_to_stop: Decimal
    modeled_fees: Decimal
    modeled_slippage: Decimal


def _entry_fill(direction: int, raw: Decimal, costs: Costs) -> Decimal:
    return raw * (Decimal(1) + Decimal(direction) * costs.slippage_fraction)


def _exit_fill(direction: int, raw: Decimal, costs: Costs) -> Decimal:
    return raw * (Decimal(1) - Decimal(direction) * costs.slippage_fraction)


def bracket_levels(
    *,
    direction: Literal[-1, 1],
    raw_entry: Decimal,
    shares: int,
    stop_fraction: Decimal,
    costs: Costs,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return cent-rounded stop/target whose modeled net reward is at least 3R."""
    if direction not in (-1, 1) or raw_entry <= 0 or shares <= 0:
        raise ValueError("VALID_DIRECTION_ENTRY_AND_SHARES_REQUIRED")
    if not Decimal(0) < stop_fraction < Decimal(1):
        raise ValueError("VALID_STOP_REQUIRED")
    direction_d = Decimal(direction)
    entry = _entry_fill(direction, raw_entry, costs)
    fees = costs.fee_per_share_per_side * Decimal(shares) * Decimal(2)
    raw_stop = raw_entry * (Decimal(1) - direction_d * stop_fraction)
    stop = raw_stop.quantize(CENT, rounding=ROUND_HALF_UP)
    stop_net = direction_d * (_exit_fill(direction, stop, costs) - entry) * shares - fees
    if stop_net >= 0:
        raise ValueError("STOP_MUST_LOSE_AFTER_COSTS")
    risk = -stop_net
    raw_target = (entry + direction_d * (Decimal(3) * risk + fees) / Decimal(shares)) / (
        Decimal(1) - direction_d * costs.slippage_fraction
    )
    target = raw_target.quantize(CENT, rounding=ROUND_CEILING if direction == 1 else ROUND_FLOOR)
    reward = direction_d * (_exit_fill(direction, target, costs) - entry) * shares - fees
    if reward / risk < Decimal(3):
        raise AssertionError("THREE_R_TARGET_ROUNDING_FAILURE")
    return stop, target, risk, reward


def simulate_trade(
    signal: Signal,
    bars: Sequence[Bar],
    parameters: StrategyParameters,
    costs: Costs,
) -> Trade:
    ordered = tuple(
        sorted((bar for bar in bars if bar.symbol == signal.symbol), key=lambda x: x.timestamp)
    )
    future = tuple(bar for bar in ordered if bar.timestamp > signal.completed_at)
    if not future:
        raise ValueError("NEXT_BAR_REQUIRED")
    entry_bar = future[0]
    entry_fill = _entry_fill(signal.direction, entry_bar.open, costs)
    shares = int(parameters.notional // entry_fill)
    if shares < 1:
        raise ValueError("NOTIONAL_TOO_SMALL")
    stop, target, risk, reward = bracket_levels(
        direction=signal.direction,
        raw_entry=entry_bar.open,
        shares=shares,
        stop_fraction=parameters.stop_fraction,
        costs=costs,
    )
    horizon = future[: max(1, parameters.max_holding_bars)]
    selected = horizon[-1]
    raw_exit = selected.close
    outcome: Literal["target", "stop", "time"] = "time"
    for bar in horizon:
        stop_hit = bar.low <= stop if signal.direction == 1 else bar.high >= stop
        target_hit = bar.high >= target if signal.direction == 1 else bar.low <= target
        if stop_hit:
            selected, raw_exit, outcome = bar, stop, "stop"
            break
        if target_hit:
            selected, raw_exit, outcome = bar, target, "target"
            break
    exit_fill = _exit_fill(signal.direction, raw_exit, costs)
    fees = (costs.fee_per_share_per_side * Decimal(shares) * Decimal(2)).quantize(CENT)
    net = (Decimal(signal.direction) * (exit_fill - entry_fill) * Decimal(shares) - fees).quantize(
        CENT
    )
    slippage = ((entry_bar.open + raw_exit) * costs.slippage_fraction * Decimal(shares)).quantize(
        CENT
    )
    return Trade(
        family=signal.family,
        variant=signal.variant,
        symbol=signal.symbol,
        direction=signal.direction,
        signal_at=signal.completed_at,
        entry_at=entry_bar.timestamp,
        exit_at=selected.timestamp,
        raw_entry=entry_bar.open,
        entry_fill=entry_fill,
        stop_price=stop,
        target_price=target,
        raw_exit=raw_exit,
        exit_fill=exit_fill,
        shares=shares,
        net_pnl=net,
        risk_dollars=risk,
        return_r=net / risk,
        outcome=outcome,
        target_to_stop=reward / risk,
        modeled_fees=fees,
        modeled_slippage=slippage,
    )
