from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import MarketRecord
from afterimage.strategies.registry import StrategyRegistry

from .holdout import HoldoutEvaluation, evaluate_strategy_holdout

ET = ZoneInfo("America/New_York")


class ResearchDatasetError(RuntimeError):
    pass


class ResearchPartition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    start: date
    end: date
    source_hash: str
    records: tuple[MarketRecord, ...]
    evaluations: dict[str, HoldoutEvaluation]


class ResearchDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: str = "afterimage-real-research-v1"
    symbol: str = "SPY"
    source: str = "alpaca-market-data-api"
    feed: str = "iex"
    timeframe: str = "5Min"
    embargo_sessions: int
    training: ResearchPartition
    holdout: ResearchPartition
    dataset_hash: str


def build_research_dataset(
    records: Sequence[MarketRecord],
    registry: StrategyRegistry,
    *,
    training_start: date,
    training_end: date,
    holdout_start: date,
    holdout_end: date,
    embargo_sessions: int,
) -> ResearchDataset:
    if (
        training_end >= holdout_start
        or training_start > training_end
        or holdout_start > holdout_end
    ):
        raise ResearchDatasetError("PARTITION_BOUNDARIES_INVALID")
    if embargo_sessions < 0:
        raise ResearchDatasetError("EMBARGO_SESSIONS_INVALID")
    session_dates = sorted({record.timestamp.astimezone(ET).date() for record in records})
    embargo_dates = [day for day in session_dates if training_end < day < holdout_start]
    if len(embargo_dates) < embargo_sessions:
        raise ResearchDatasetError("EMBARGO_SESSIONS_MISSING")
    training = tuple(
        record
        for record in records
        if training_start <= record.timestamp.astimezone(ET).date() <= training_end
    )
    holdout = tuple(
        record
        for record in records
        if holdout_start <= record.timestamp.astimezone(ET).date() <= holdout_end
    )

    def partition(
        name: str,
        start: date,
        end: date,
        selected: tuple[MarketRecord, ...],
    ) -> ResearchPartition:
        source_hash = _record_hash(selected)
        evaluations = {
            item.split("@", maxsplit=1)[0]: evaluate_strategy_holdout(
                selected, registry.load(*item.split("@", maxsplit=1))
            )
            for item in registry.list()
        }
        return ResearchPartition(
            name=name,
            start=start,
            end=end,
            source_hash=source_hash,
            records=selected,
            evaluations=evaluations,
        )

    draft = ResearchDataset(
        embargo_sessions=embargo_sessions,
        training=partition("training", training_start, training_end, training),
        holdout=partition("holdout", holdout_start, holdout_end, holdout),
        dataset_hash="",
    )
    return draft.model_copy(update={"dataset_hash": _dataset_hash(draft)})


def validate_research_dataset(dataset: ResearchDataset) -> None:
    for partition in (dataset.training, dataset.holdout):
        if _record_hash(partition.records) != partition.source_hash:
            raise ResearchDatasetError("SOURCE_HASH_MISMATCH")
        for evaluation in partition.evaluations.values():
            if evaluation.source_hash != partition.source_hash:
                raise ResearchDatasetError("EVALUATION_SOURCE_HASH_MISMATCH")
    if _dataset_hash(dataset) != dataset.dataset_hash:
        raise ResearchDatasetError("DATASET_HASH_MISMATCH")


def public_research_manifest(dataset: ResearchDataset) -> dict[str, object]:
    def public_partition(partition: ResearchPartition) -> dict[str, object]:
        return {
            "name": partition.name,
            "start": partition.start.isoformat(),
            "end": partition.end.isoformat(),
            "source_hash": partition.source_hash,
            "record_count": len(partition.records),
            "evaluations": {
                strategy_id: evaluation.model_dump(mode="json")
                for strategy_id, evaluation in partition.evaluations.items()
            },
        }

    return {
        "schema_version": dataset.schema_version,
        "dataset_hash": dataset.dataset_hash,
        "symbol": dataset.symbol,
        "provenance": {
            "provider": "Alpaca Market Data API",
            "transport": "checksum-pinned official Alpaca CLI OAuth profile",
            "endpoint": f"/v2/stocks/{dataset.symbol}/bars",
            "source": dataset.source,
            "feed": dataset.feed,
            "timeframe": dataset.timeframe,
            "raw_market_records": "private cache; omitted from public redistribution",
        },
        "methodology": {
            "result_type": "underlying-path R proxy; not option or broker P&L",
            "bar_timestamp_semantics": (
                "Alpaca timestamps are bar starts; each 5-minute close is admitted only at "
                "start+5 minutes."
            ),
            "target_r": "3",
            "stop_r": "-1",
            "same_bar_collision": "stop-first-conservative",
            "no_signal_policy": "no invented outcome",
            "embargo_sessions": dataset.embargo_sessions,
        },
        "training": public_partition(dataset.training),
        "holdout": public_partition(dataset.holdout),
    }


def persist_research_dataset(
    dataset: ResearchDataset, private_path: Path, public_path: Path
) -> None:
    validate_research_dataset(dataset)
    private_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private_path.parent, 0o700)
    if private_path.is_symlink():
        raise ResearchDatasetError("PRIVATE_RESEARCH_PATH_SYMLINK")
    descriptor = os.open(
        private_path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(dataset.model_dump_json(indent=2))
        handle.write("\n")
    os.chmod(private_path, 0o600)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(
        json.dumps(public_research_manifest(dataset), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_research_dataset(path: Path) -> ResearchDataset:
    try:
        dataset = ResearchDataset.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResearchDatasetError(f"RESEARCH_DATASET_NOT_FOUND:{path.name}") from exc
    validate_research_dataset(dataset)
    return dataset


def _record_hash(records: Sequence[MarketRecord]) -> str:
    return canonical_sha256(
        [record.model_dump(mode="json", exclude={"received_at"}) for record in records]
    )


def _dataset_hash(dataset: ResearchDataset) -> str:
    return canonical_sha256(dataset.model_dump(mode="json", exclude={"dataset_hash"}))
