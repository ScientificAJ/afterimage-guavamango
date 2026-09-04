from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


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
