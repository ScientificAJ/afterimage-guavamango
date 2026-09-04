from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import DecisionStatus, EvidenceLevel, SessionState


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VersionStamp(StrictModel):
    strategy_id: str
    strategy_version: str
    feature_schema_version: str = "1"
    evidence_protocol_version: str = "sealed-twins-v1"
    risk_policy_version: str = "hackathon-v1"
    model_id: str = "deterministic"
    prompt_hash: str = "none"
    data_snapshot_id: str = "unbound"

    @field_validator("strategy_id", "strategy_version", "feature_schema_version")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("version fields cannot be blank")
        return value


class StrategyIdentity(StrictModel):
    strategy_id: str
    strategy_version: str

    @field_validator("strategy_id", "strategy_version")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy identity cannot be blank")
        return value


class MarketRecord(StrictModel):
    symbol: str
    timestamp: datetime
    received_at: datetime
    source: str
    feed: str
    kind: Literal["bar", "quote", "trade", "snapshot", "contract"]
    values: dict[str, Any]


class FrozenSnapshot(StrictModel):
    snapshot_id: str
    cutoff: datetime
    identity: StrategyIdentity
    features: dict[str, float | int | str | bool | None]
    records: tuple[MarketRecord, ...] = ()
    provenance: dict[str, str] = Field(default_factory=dict)


class CandidateEvent(StrictModel):
    candidate_id: UUID = Field(default_factory=uuid4)
    identity: StrategyIdentity
    snapshot_id: str
    symbol: str
    direction: Literal["bullish", "bearish", "long_volatility"]
    signal_at: datetime
    features: dict[str, float | int | str | bool | None]
    permitted_structures: tuple[str, ...]


class EvidenceQuery(StrictModel):
    candidate_id: UUID
    identity: StrategyIdentity
    feature_names: tuple[str, ...]
    feature_values: tuple[float, ...]
    k: int = Field(default=40, ge=1, le=500)
    maximum_twin_weight: Decimal = Decimal("0.10")


class BlindTwin(StrictModel):
    twin_id: str
    features: tuple[float, ...]
    distance: Decimal
    weight: Decimal
    cluster_id: str


class EvidenceManifest(StrictModel):
    manifest_id: UUID = Field(default_factory=uuid4)
    query: EvidenceQuery
    twins: tuple[BlindTwin, ...]
    excluded: tuple[dict[str, str], ...] = ()
    versions: VersionStamp
    dataset_hash: str
    created_at: datetime
    commit_hash: str = ""


class RevealedOutcome(StrictModel):
    twin_id: str
    target_first: bool | None
    return_r: Decimal
    censored: bool = False
    path: tuple[Decimal, ...] = ()


class EvidenceMetrics(StrictModel):
    n: int
    n_eff: Decimal
    target_first_probability: Decimal
    lower_confidence_bound: Decimal
    expected_value_r: Decimal
    maximum_drawdown_r: Decimal
    positive_loo_fraction: Decimal
    placebo_edge_r: Decimal
    coverage: Decimal
    confidence_method: str


class EvidenceDecision(StrictModel):
    status: DecisionStatus
    metrics: EvidenceMetrics
    reasons: tuple[str, ...]
    commit_hash: str
    reveal_hash: str


class OptionLeg(StrictModel):
    symbol: str
    ratio_qty: int = Field(ge=1)
    side: Literal["buy", "sell"]
    position_intent: Literal["buy_to_open", "sell_to_open", "buy_to_close", "sell_to_close"]
    bid: Decimal
    ask: Decimal
    quote_at: datetime


class ContractPolicy(StrictModel):
    permitted_structures: tuple[str, ...]
    min_dte: int
    max_dte: int
    min_open_interest: int
    max_relative_spread: Decimal
    max_quote_age_seconds: int


class ExitPlan(StrictModel):
    target_r: Decimal
    stop_r: Decimal
    exit_at: datetime


class PayoffPassport(StrictModel):
    structure: str
    legs: tuple[OptionLeg, ...]
    entry_net_debit: Decimal
    stressed_max_loss: Decimal
    stressed_max_profit: Decimal
    structural_ratio: Decimal
    operational_target_profit: Decimal
    operational_stop_loss: Decimal
    operational_ratio: Decimal
    modeled_costs: Decimal


class AccountSnapshot(StrictModel):
    account_id_hash: str
    paper: bool
    status: str
    equity: Decimal
    cash: Decimal
    options_buying_power: Decimal
    options_approved_level: int
    options_trading_level: int
    trading_blocked: bool
    timestamp: datetime


class RiskGate(StrictModel):
    name: str
    passed: bool
    observed: str
    required: str
    reason_code: str | None = None


class RiskDecision(StrictModel):
    decision_id: UUID = Field(default_factory=uuid4)
    status: DecisionStatus
    gates: tuple[RiskGate, ...]
    quantity: int = Field(ge=0)
    modeled_max_loss: Decimal
    strategy_manifest_hash: str
    evidence_commit_hash: str
    quote_hash: str
    decided_at: datetime


class ExecutionIntent(StrictModel):
    intent_id: UUID = Field(default_factory=uuid4)
    account_id_hash: str
    strategy_manifest_hash: str
    evidence_commit_hash: str
    risk_decision_id: UUID
    legs: tuple[OptionLeg, ...]
    quantity: int = Field(gt=0)
    limit_price: Decimal
    order_class: Literal["mleg"] = "mleg"
    order_type: Literal["limit"] = "limit"
    time_in_force: Literal["day"] = "day"


class ExecutionWarrant(StrictModel):
    warrant_id: UUID = Field(default_factory=uuid4)
    intent: ExecutionIntent
    intent_hash: str
    risk_vector_hash: str
    issued_at: datetime
    expires_at: datetime
    nonce: str
    signature: str
    public_key: str
    consumed_at: datetime | None = None


class BrokerOrder(StrictModel):
    broker_order_id: str
    client_order_id: str
    status: str
    intent_hash: str
    submitted_at: datetime
    raw_hash: str


class SessionEvent(StrictModel):
    event_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    sequence: int = Field(ge=1)
    event_type: str
    state: SessionState
    payload: dict[str, Any]
    versions: VersionStamp
    created_at: datetime
    evidence_level: EvidenceLevel = EvidenceLevel.L0_INVARIANT


class TournamentEntry(StrictModel):
    identity: StrategyIdentity
    manifest_hash: str
    status: DecisionStatus
    score: Decimal
    metrics: EvidenceMetrics
    failed_gates: tuple[str, ...] = ()


class TournamentResult(StrictModel):
    tournament_hash: str
    entries: tuple[TournamentEntry, ...]
    champion: StrategyIdentity | None
    champion_manifest_hash: str | None
    revealed_at: datetime
