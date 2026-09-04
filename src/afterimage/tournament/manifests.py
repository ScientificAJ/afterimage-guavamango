from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from afterimage.contracts.models import StrategyIdentity


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateManifest(FrozenModel):
    identity: StrategyIdentity
    parameters: dict[str, str | int | float | bool]
    code_revision: str
    dataset_hash: str
    training_end: datetime
    embargo_sessions: int = Field(ge=1)
    final_holdout_start: datetime
    final_holdout_end: datetime
    fee_per_contract: Decimal
    slippage_per_leg: Decimal
    baselines: tuple[str, ...]


class PromotionPolicy(FrozenModel):
    policy_version: str = "promotion-v1"
    minimum_n: int = 30
    minimum_n_eff: Decimal = Decimal(30)
    minimum_expected_value_r: Decimal = Decimal("0.10")
    minimum_lower_probability: Decimal = Decimal("0.28")
    minimum_positive_loo_fraction: Decimal = Decimal("0.80")
    maximum_drawdown_r: Decimal = Decimal(8)
    weights: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "expected_value": Decimal("0.30"),
            "lower_bound": Decimal("0.25"),
            "drawdown": Decimal("0.20"),
            "stability": Decimal("0.15"),
            "coverage": Decimal("0.10"),
        }
    )


class TournamentSeal(FrozenModel):
    tournament_id: str
    candidate_hashes: tuple[str, ...]
    promotion_policy_hash: str
    holdout_hash: str
    sealed_at: datetime
    seal_hash: str
