from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from test_real_holdout import session

from afterimage.research.dataset import (
    ResearchDatasetError,
    build_research_dataset,
    load_research_dataset,
    persist_research_dataset,
    public_research_manifest,
    validate_research_dataset,
)
from afterimage.strategies.registry import default_registry


def test_research_dataset_enforces_an_embargo_and_runs_every_registered_strategy() -> None:
    records = (
        session(date(2026, 6, 29), "target")
        + session(date(2026, 6, 30), "stop")
        + session(date(2026, 7, 1), "target")
    )

    dataset = build_research_dataset(
        records,
        default_registry(),
        training_start=date(2026, 6, 29),
        training_end=date(2026, 6, 29),
        holdout_start=date(2026, 7, 1),
        holdout_end=date(2026, 7, 1),
        embargo_sessions=1,
    )

    assert {record.timestamp.date() for record in dataset.training.records} == {date(2026, 6, 29)}
    assert {record.timestamp.date() for record in dataset.holdout.records} == {date(2026, 7, 1)}
    assert set(dataset.training.evaluations) == {
        "opening_range_failure_v1",
        "momentum_continuation_v1",
        "volatility_dislocation_v1",
    }
    assert dataset.training.evaluations["opening_range_failure_v1"].rows[0].return_r == 3
    assert dataset.holdout.evaluations["opening_range_failure_v1"].rows[0].return_r == 3
    assert dataset.dataset_hash
    validate_research_dataset(dataset)

    public = public_research_manifest(dataset)
    assert public["dataset_hash"] == dataset.dataset_hash
    assert public["provenance"]["provider"] == "Alpaca Market Data API"
    assert public["provenance"]["feed"] == "iex"
    assert "records" not in public["training"]
    assert public["training"]["record_count"] == len(dataset.training.records)
    assert public["holdout"]["evaluations"]["opening_range_failure_v1"]["rows"]


def test_research_dataset_rejects_any_post_build_market_record_tampering() -> None:
    dataset = build_research_dataset(
        session(date(2026, 7, 1), "target"),
        default_registry(),
        training_start=date(2026, 7, 1),
        training_end=date(2026, 7, 1),
        holdout_start=date(2026, 7, 2),
        holdout_end=date(2026, 7, 2),
        embargo_sessions=0,
    )
    changed = dataset.model_copy(
        update={
            "training": dataset.training.model_copy(
                update={"records": dataset.training.records[:-1]}
            )
        }
    )

    with pytest.raises(ResearchDatasetError, match="SOURCE_HASH_MISMATCH"):
        validate_research_dataset(changed)


def test_research_dataset_persistence_keeps_raw_bars_private_and_public_manifest_clean(
    tmp_path: Path,
) -> None:
    dataset = build_research_dataset(
        session(date(2026, 7, 1), "target"),
        default_registry(),
        training_start=date(2026, 7, 1),
        training_end=date(2026, 7, 1),
        holdout_start=date(2026, 7, 2),
        holdout_end=date(2026, 7, 2),
        embargo_sessions=0,
    )
    private = tmp_path / "private" / "spy.json"
    public = tmp_path / "evidence" / "spy-manifest.json"

    persist_research_dataset(dataset, private, public)

    assert private.stat().st_mode & 0o777 == 0o600
    assert private.parent.stat().st_mode & 0o777 == 0o700
    assert load_research_dataset(private) == dataset
    public_payload = json.loads(public.read_text(encoding="utf-8"))
    assert "records" not in public_payload["training"]
    assert public_payload["dataset_hash"] == dataset.dataset_hash
