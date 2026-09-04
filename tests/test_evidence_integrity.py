from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.models import (
    BlindTwin,
    EvidenceQuery,
    RevealedOutcome,
    StrategyIdentity,
    VersionStamp,
)
from afterimage.evidence.commit_reveal import build_manifest
from afterimage.evidence.metrics import EvidencePolicy, evaluate_evidence
from afterimage.evidence.vault import HistoricalRow, OutcomeVault


def twin(name: str, cluster: str, weight: str = "0.333333333333333333") -> BlindTwin:
    return BlindTwin(
        twin_id=name,
        features=(1.0,),
        distance=Decimal(0),
        weight=Decimal(weight),
        cluster_id=cluster,
    )


def test_drawdown_is_chronological_and_placebo_is_an_actual_baseline() -> None:
    twins = (twin("late_loss", "a"), twin("early_win", "b"), twin("latest_loss", "c"))
    outcomes = (
        RevealedOutcome(
            twin_id="late_loss",
            session_date=date(2026, 1, 2),
            target_first=False,
            return_r=Decimal(-3),
            placebo_return_r=Decimal(-1),
        ),
        RevealedOutcome(
            twin_id="early_win",
            session_date=date(2026, 1, 1),
            target_first=True,
            return_r=Decimal(2),
            placebo_return_r=Decimal(0),
        ),
        RevealedOutcome(
            twin_id="latest_loss",
            session_date=date(2026, 1, 3),
            target_first=False,
            return_r=Decimal(-3),
            placebo_return_r=Decimal(-1),
        ),
    )
    permissive = EvidencePolicy(
        minimum_n=1,
        minimum_n_eff=Decimal(1),
        break_even_probability=Decimal(0),
        probability_margin=Decimal(0),
        minimum_expected_value_r=Decimal(-10),
        minimum_positive_loo_fraction=Decimal(0),
        minimum_placebo_edge_r=Decimal(-10),
        maximum_drawdown_r=Decimal(99),
    )

    decision = evaluate_evidence(twins, outcomes, "commit", "reveal", permissive)

    assert decision.metrics.maximum_drawdown_r == Decimal(6)
    assert decision.metrics.placebo_expected_value_r < 0
    assert decision.metrics.placebo_edge_r == (
        decision.metrics.expected_value_r - decision.metrics.placebo_expected_value_r
    )


def test_vault_reveal_contains_dates_and_predeclared_placebo_outcomes() -> None:
    row = HistoricalRow(
        private_row_id="row-1",
        session_date=date(2026, 1, 2),
        cluster_id="week-1",
        features={"x": 1.0},
        target_first=True,
        return_r=Decimal(3),
        placebo_return_r=Decimal("-0.25"),
    )
    vault = OutcomeVault((row,), salt="fixed")
    blind = vault.blind_rows()[0]

    revealed = vault.reveal((blind.twin_id,))[0]

    assert revealed.session_date == row.session_date
    assert revealed.placebo_return_r == Decimal("-0.25")


def test_identical_evidence_inputs_produce_identical_commit_hashes() -> None:
    query = EvidenceQuery(
        candidate_id=UUID("00000000-0000-0000-0000-000000000001"),
        identity=StrategyIdentity(strategy_id="test", strategy_version="1"),
        feature_names=("x",),
        feature_values=(1.0,),
        k=1,
        maximum_twin_weight=Decimal(1),
    )
    versions = VersionStamp(strategy_id="test", strategy_version="1")
    twins = (twin("twin-1", "week-1", "1"),)

    first = build_manifest(query, twins, versions, "dataset")
    second = build_manifest(query, twins, versions, "dataset")

    assert first.manifest_id != second.manifest_id
    assert first.created_at <= datetime.now(UTC)
    assert first.commit_hash == second.commit_hash


def test_missing_outcomes_cannot_accidentally_pass() -> None:
    decision = evaluate_evidence(
        (twin("missing", "a", "1"),), (), "commit", "reveal", EvidencePolicy()
    )

    assert decision.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert decision.metrics.coverage == 0
