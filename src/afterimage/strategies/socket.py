from __future__ import annotations

from datetime import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from afterimage.config import StrategyConfig
from afterimage.contracts.models import StrategyIdentity


class StrategyRuntimeSpec(BaseModel):
    """Config-bound contract between a strategy plugin and the live orchestrator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: StrategyIdentity
    display_name: str
    plugin: str
    symbols: tuple[str, ...] = Field(min_length=1)
    bar_timeframe: str
    lookback_calendar_days: int = Field(ge=1, le=366)
    session_start: time
    signal_at: time
    entry_cutoff: time
    execution_kind: Literal["option", "equity"]
    market_scope: Literal["primary", "universe"] = "primary"

    @field_validator("symbols")
    @classmethod
    def normalized_symbols(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(symbol.strip().upper() for symbol in value)
        if any(not symbol for symbol in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("strategy symbols must be non-empty and unique")
        return normalized

    @field_validator("display_name", "plugin", "bar_timeframe")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy runtime strings cannot be blank")
        return value.strip()

    @classmethod
    def from_config(cls, config: StrategyConfig) -> StrategyRuntimeSpec:
        payload = config.payload
        runtime = payload.get("runtime")
        if not isinstance(runtime, dict):
            raise TypeError(f"STRATEGY_RUNTIME_MISSING:{config.strategy_id}")
        values: dict[str, Any] = {
            "identity": {
                "strategy_id": config.strategy_id,
                "strategy_version": config.strategy_version,
            },
            "display_name": payload.get("display_name", config.strategy_id),
            "plugin": payload.get("plugin"),
            "symbols": payload.get("symbols"),
            **runtime,
        }
        return cls.model_validate(values)
