from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from test_real_holdout import session

from afterimage.contracts.hashing import canonical_sha256
from afterimage.execution.lifecycle import ExecutionError
from afterimage.orchestration.coordinator import Coordinator
from afterimage.research import build_research_dataset, persist_research_dataset
from afterimage.storage import Database
from afterimage.strategies.registry import default_registry


def test_tournament_scores_strategy_implementations_from_the_real_holdout(
    tmp_path: Path,
) -> None:
    dataset = build_research_dataset(
        session(date(2026, 6, 29), "target")
        + session(date(2026, 6, 30), "stop")
        + session(date(2026, 7, 1), "target"),
        default_registry(),
        training_start=date(2026, 6, 29),
        training_end=date(2026, 6, 29),
        holdout_start=date(2026, 7, 1),
        holdout_end=date(2026, 7, 1),
        embargo_sessions=1,
    )
    private = tmp_path / "research.json"
    persist_research_dataset(dataset, private, tmp_path / "manifest.json")
    coordinator = Coordinator(
        Database(f"sqlite:///{tmp_path / 'tournament.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )

    tournament = coordinator.run_research_tournament(private)

    provenance = tournament["result_provenance"]
    assert len(provenance) == 3
    for item in provenance.values():
        evaluation = dataset.holdout.evaluations[item["strategy_id"]]
        assert item["outcome_series_hash"] == canonical_sha256(
            [row.model_dump(mode="json") for row in evaluation.rows]
        )
        assert item["observations"] == len(evaluation.rows)
    assert tournament["champion"] is None
    assert tournament["evaluation_label"] == (
        "real Alpaca chronological holdout; underlying-path R proxy; not broker P&L"
    )


def test_execution_promotion_gate_recomputes_no_champion_from_bound_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = build_research_dataset(
        session(date(2026, 6, 29), "target")
        + session(date(2026, 6, 30), "stop")
        + session(date(2026, 7, 1), "target"),
        default_registry(),
        training_start=date(2026, 6, 29),
        training_end=date(2026, 6, 29),
        holdout_start=date(2026, 7, 1),
        holdout_end=date(2026, 7, 1),
        embargo_sessions=1,
    )
    private = tmp_path / "research.json"
    persist_research_dataset(dataset, private, tmp_path / "manifest.json")
    monkeypatch.setenv("AFTERIMAGE_RESEARCH_DATASET_PATH", str(private))
    coordinator = Coordinator(
        Database(f"sqlite:///{tmp_path / 'promotion.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    strategy = coordinator.registry.load("opening_range_failure_v1")

    with pytest.raises(ExecutionError, match="STRATEGY_NOT_PROMOTED:NO_CHAMPION"):
        coordinator._require_promoted_strategy(
            strategy.identity.strategy_id,
            coordinator._strategy_authority_hash(strategy),
        )
