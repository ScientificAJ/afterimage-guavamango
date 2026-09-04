from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from afterimage.contracts.hashing import canonical_sha256
from afterimage.tournament import PromotionPolicy


class FrozenConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskPolicy(FrozenConfig):
    policy_version: str
    paper_only: bool = True
    maximum_modeled_loss: Decimal
    maximum_equity_notional: Decimal = Decimal(10000)
    maximum_daily_loss: Decimal
    maximum_high_water_drawdown_fraction: Decimal
    maximum_open_strategy_positions: int = Field(ge=0)
    minimum_structural_reward_risk: Decimal
    minimum_operational_reward_risk: Decimal
    maximum_quote_age_seconds: Decimal
    maximum_leg_timestamp_skew_seconds: Decimal
    maximum_relative_spread: Decimal
    minimum_open_interest: int = Field(ge=0)
    allow_averaging_down: bool = False
    allow_martingale: bool = False
    allow_kelly_sizing: bool = False


class StrategyConfig(FrozenConfig):
    strategy_id: str
    strategy_version: str
    payload: dict[str, Any]
    source_hash: str


class RuntimeConfig(FrozenConfig):
    risk: RiskPolicy
    tournament: PromotionPolicy
    strategies: dict[str, StrategyConfig]
    manifest_hash: str

    def strategy(self, strategy_id: str) -> StrategyConfig:
        try:
            return self.strategies[strategy_id]
        except KeyError as exc:
            raise KeyError(f"strategy configuration missing: {strategy_id}") from exc


def _yaml_object(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"CONFIG_MISSING:{path}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"CONFIG_NOT_AN_OBJECT:{path}")
    return value


def load_runtime_config(root: str | Path = "configs") -> RuntimeConfig:
    config_root = Path(root)
    risk_payload = _yaml_object(config_root / "risk" / "hackathon-v1.yaml")
    tournament_payload = _yaml_object(config_root / "tournament-v1.yaml")
    candidate_names = tournament_payload.pop("candidates", [])
    strategy_configs: dict[str, StrategyConfig] = {}
    raw_strategies: list[dict[str, Any]] = []
    for candidate in candidate_names:
        strategy_id, separator, version = str(candidate).partition("@")
        if not separator:
            raise RuntimeError(f"CONFIG_CANDIDATE_VERSION_MISSING:{candidate}")
        payload = _yaml_object(config_root / "strategies" / f"{strategy_id}.yaml")
        if payload.get("strategy_id") != strategy_id or payload.get("strategy_version") != version:
            raise RuntimeError(f"CONFIG_STRATEGY_IDENTITY_MISMATCH:{candidate}")
        raw_strategies.append(payload)
        strategy_configs[strategy_id] = StrategyConfig(
            strategy_id=strategy_id,
            strategy_version=version,
            payload=payload,
            source_hash=canonical_sha256(payload),
        )
    manifest_payload = {
        "risk": risk_payload,
        "tournament": tournament_payload,
        "strategies": raw_strategies,
    }
    return RuntimeConfig(
        risk=RiskPolicy.model_validate(risk_payload),
        tournament=PromotionPolicy.model_validate(tournament_payload),
        strategies=strategy_configs,
        manifest_hash=canonical_sha256(manifest_payload),
    )
