from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import (
    CandidateEvent,
    ContractPolicy,
    EvidenceQuery,
    ExitPlan,
    FrozenSnapshot,
    MarketRecord,
    StrategyIdentity,
)


class MarketFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    symbol: str
    cutoff: datetime
    records: tuple[MarketRecord, ...]
    context: dict[str, Any] = Field(default_factory=dict)


class StrategyPlugin(Protocol):
    identity: StrategyIdentity

    def freeze(self, raw: MarketFrame) -> FrozenSnapshot: ...
    def detect(self, snapshot: FrozenSnapshot) -> CandidateEvent | None: ...
    def evidence_query(self, candidate: CandidateEvent) -> EvidenceQuery: ...
    def contract_policy(self, candidate: CandidateEvent) -> ContractPolicy: ...
    def exit_plan(self, candidate: CandidateEvent) -> ExitPlan: ...


class BaseStrategy(ABC):
    identity: StrategyIdentity

    def freeze(self, raw: MarketFrame) -> FrozenSnapshot:
        eligible = tuple(record for record in raw.records if record.timestamp <= raw.cutoff)
        features = self.build_features(
            MarketFrame(symbol=raw.symbol, cutoff=raw.cutoff, records=eligible, context=raw.context)
        )
        payload = {
            "identity": self.identity.model_dump(),
            "cutoff": raw.cutoff,
            "features": features,
            "records": eligible,
        }
        return FrozenSnapshot(
            snapshot_id=canonical_sha256(payload),
            cutoff=raw.cutoff,
            identity=self.identity,
            features=features,
            records=eligible,
            provenance={"builder": self.__class__.__name__, "point_in_time": "true"},
        )

    @abstractmethod
    def build_features(self, raw: MarketFrame) -> dict[str, float | int | str | bool | None]:
        raise NotImplementedError

    @abstractmethod
    def detect(self, snapshot: FrozenSnapshot) -> CandidateEvent | None:
        raise NotImplementedError

    def evidence_query(self, candidate: CandidateEvent) -> EvidenceQuery:
        numeric = [
            (key, value)
            for key, value in candidate.features.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        return EvidenceQuery(
            candidate_id=candidate.candidate_id,
            identity=candidate.identity,
            feature_names=tuple(key for key, _ in numeric),
            feature_values=tuple(float(value) for _, value in numeric),
        )

    def contract_policy(self, candidate: CandidateEvent) -> ContractPolicy:
        return ContractPolicy(
            permitted_structures=candidate.permitted_structures,
            min_dte=2,
            max_dte=7,
            min_open_interest=100,
            max_relative_spread="0.05",
            max_quote_age_seconds=2,
        )

    @abstractmethod
    def exit_plan(self, candidate: CandidateEvent) -> ExitPlan:
        raise NotImplementedError


def bar_values(snapshot: FrozenSnapshot) -> list[tuple[datetime, dict[str, Any]]]:
    return sorted(
        [(record.timestamp, record.values) for record in snapshot.records if record.kind == "bar"],
        key=lambda item: item[0],
    )


def numeric_feature(
    features: dict[str, float | int | str | bool | None], key: str, default: float = 0.0
) -> float:
    value = features.get(key)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default
