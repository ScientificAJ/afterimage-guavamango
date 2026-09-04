from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.models import ExecutionIntent, ExitPlan, OptionLeg


class WatchdogAction(StrEnum):
    HOLD = "HOLD"
    EXIT_TARGET = "EXIT_TARGET"
    EXIT_STOP = "EXIT_STOP"
    EXIT_TIME = "EXIT_TIME"
    HALT_STALE_QUOTES = "HALT_STALE_QUOTES"
    HALT_POSITION_MISMATCH = "HALT_POSITION_MISMATCH"


class WatchdogContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    now: datetime
    exit_at: datetime
    current_profit: Decimal
    target_profit: Decimal
    stop_loss: Decimal
    quote_age_seconds: Decimal
    maximum_quote_age_seconds: Decimal
    position_matches: bool


class WatchdogAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: WatchdogAction
    current_profit: Decimal
    quote_age_seconds: Decimal
    position_matches: bool
    observed_at: datetime
    quote_symbols: tuple[str, ...]
    exit_legs: tuple[OptionLeg, ...]
    exit_limit_price: Decimal


def decide_watchdog_action(context: WatchdogContext) -> WatchdogAction:
    if not context.position_matches:
        return WatchdogAction.HALT_POSITION_MISMATCH
    if context.quote_age_seconds > context.maximum_quote_age_seconds:
        return WatchdogAction.HALT_STALE_QUOTES
    if context.current_profit >= context.target_profit:
        return WatchdogAction.EXIT_TARGET
    if context.current_profit <= -abs(context.stop_loss):
        return WatchdogAction.EXIT_STOP
    if context.now >= context.exit_at:
        return WatchdogAction.EXIT_TIME
    return WatchdogAction.HOLD


class PositionWatchdog:
    """Read broker truth and calculate a conservative, immediately executable exit mark."""

    def __init__(self, gateway: Any, maximum_quote_age_seconds: Decimal = Decimal(2)) -> None:
        self.gateway = gateway
        self.maximum_quote_age_seconds = maximum_quote_age_seconds

    @staticmethod
    def _quote_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        value = payload.get("quotes", payload.get("data", payload))
        return value if isinstance(value, dict) else {}

    @staticmethod
    def matched_quantity(
        intent: ExecutionIntent, positions: tuple[dict[str, Any], ...]
    ) -> int | None:
        observed: dict[str, Decimal] = {}
        for position in positions:
            symbol = position.get("symbol")
            quantity = position.get("qty")
            if not isinstance(symbol, str) or not symbol or quantity is None:
                return None
            if symbol in observed:
                return None
            try:
                observed[symbol] = Decimal(str(quantity))
            except (InvalidOperation, ValueError):
                return None
        if set(observed) != {leg.symbol for leg in intent.legs}:
            return None
        quantities: set[Decimal] = set()
        for leg in intent.legs:
            signed_ratio = Decimal(leg.ratio_qty) * (
                Decimal(1) if leg.side == "buy" else Decimal(-1)
            )
            quantity = observed[leg.symbol] / signed_ratio
            quantities.add(quantity)
        if len(quantities) != 1:
            return None
        quantity = quantities.pop()
        if quantity != quantity.to_integral_value() or not 0 < quantity <= intent.quantity:
            return None
        return int(quantity)

    @classmethod
    def _position_matches(
        cls, intent: ExecutionIntent, positions: tuple[dict[str, Any], ...]
    ) -> bool:
        return cls.matched_quantity(intent, positions) == intent.quantity

    async def assess(
        self,
        intent: ExecutionIntent,
        exit_plan: ExitPlan,
        target_profit: Decimal,
        stop_loss: Decimal,
        now: datetime | None = None,
    ) -> WatchdogAssessment:
        observed_at = now or datetime.now(UTC)
        positions = await self.gateway.positions()
        symbols = tuple(leg.symbol for leg in intent.legs)
        quotes = self._quote_map(await self.gateway.option_quotes(symbols=list(symbols)))
        liquidation_value = Decimal(0)
        timestamps: list[datetime] = []
        exit_legs: list[OptionLeg] = []
        complete = True
        for leg in intent.legs:
            quote = quotes.get(leg.symbol)
            if not isinstance(quote, dict):
                complete = False
                continue
            timestamp_value = quote.get("t", quote.get("timestamp"))
            if not isinstance(timestamp_value, str):
                complete = False
                continue
            timestamp = datetime.fromisoformat(timestamp_value)
            timestamps.append(timestamp)
            bid = Decimal(str(quote.get("bp", quote.get("bid_price", 0))))
            ask = Decimal(str(quote.get("ap", quote.get("ask_price", 0))))
            if bid <= 0 or ask <= bid:
                complete = False
                continue
            if leg.side == "buy":
                liquidation_value += bid * leg.ratio_qty
                exit_legs.append(
                    leg.model_copy(
                        update={
                            "side": "sell",
                            "position_intent": "sell_to_close",
                            "bid": bid,
                            "ask": ask,
                            "quote_at": timestamp,
                        }
                    )
                )
            else:
                liquidation_value -= ask * leg.ratio_qty
                exit_legs.append(
                    leg.model_copy(
                        update={
                            "side": "buy",
                            "position_intent": "buy_to_close",
                            "bid": bid,
                            "ask": ask,
                            "quote_at": timestamp,
                        }
                    )
                )
        if liquidation_value <= 0:
            complete = False
        quote_age = (
            max(Decimal(str((observed_at - timestamp).total_seconds())) for timestamp in timestamps)
            if complete and len(timestamps) == len(intent.legs)
            else Decimal("Infinity")
        )
        profit = (
            (liquidation_value - intent.limit_price) * Decimal(100) * intent.quantity
            if complete
            else Decimal(0)
        )
        matches = self._position_matches(intent, positions)
        action = decide_watchdog_action(
            WatchdogContext(
                now=observed_at,
                exit_at=exit_plan.exit_at,
                current_profit=profit,
                target_profit=target_profit,
                stop_loss=stop_loss,
                quote_age_seconds=quote_age,
                maximum_quote_age_seconds=self.maximum_quote_age_seconds,
                position_matches=matches,
            )
        )
        return WatchdogAssessment(
            action=action,
            current_profit=profit,
            quote_age_seconds=quote_age,
            position_matches=matches,
            observed_at=observed_at,
            quote_symbols=symbols,
            exit_legs=tuple(exit_legs) if complete else (),
            exit_limit_price=liquidation_value if complete else Decimal(0),
        )
