from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.models import EvidenceMetrics, TournamentEntry

from .manifests import CandidateManifest, PromotionPolicy


def failed_gates(metrics: EvidenceMetrics, policy: PromotionPolicy) -> tuple[str, ...]:
    failed = []
    if metrics.n < policy.minimum_n:
        failed.append("INSUFFICIENT_RAW_SAMPLE")
    if metrics.n_eff < policy.minimum_n_eff:
        failed.append("INSUFFICIENT_EFFECTIVE_SAMPLE")
    if metrics.expected_value_r <= policy.minimum_expected_value_r:
        failed.append("EXPECTED_VALUE")
    if metrics.lower_confidence_bound <= policy.minimum_lower_probability:
        failed.append("PROBABILITY_LOWER_BOUND")
    if metrics.positive_loo_fraction < policy.minimum_positive_loo_fraction:
        failed.append("LEAVE_ONE_CLUSTER_OUT")
    if metrics.maximum_drawdown_r > policy.maximum_drawdown_r:
        failed.append("MAXIMUM_DRAWDOWN")
    return tuple(failed)


def score(metrics: EvidenceMetrics, policy: PromotionPolicy) -> Decimal:
    w = policy.weights
    drawdown_quality = max(
        Decimal(0), Decimal(1) - metrics.maximum_drawdown_r / policy.maximum_drawdown_r
    )
    return (
        metrics.expected_value_r * w["expected_value"]
        + metrics.lower_confidence_bound * w["lower_bound"]
        + drawdown_quality * w["drawdown"]
        + metrics.positive_loo_fraction * w["stability"]
        + metrics.coverage * w["coverage"]
    )


def build_entry(
    manifest: CandidateManifest,
    manifest_hash: str,
    metrics: EvidenceMetrics,
    policy: PromotionPolicy,
) -> TournamentEntry:
    failed = failed_gates(metrics, policy)
    status = DecisionStatus.PASS if not failed else DecisionStatus.REJECT
    if any(reason.startswith("INSUFFICIENT") for reason in failed):
        status = DecisionStatus.INSUFFICIENT_EVIDENCE
    return TournamentEntry(
        identity=manifest.identity,
        manifest_hash=manifest_hash,
        status=status,
        score=score(metrics, policy),
        metrics=metrics,
        failed_gates=failed,
    )


def select_champion(entries: Sequence[TournamentEntry]) -> TournamentEntry | None:
    eligible = [entry for entry in entries if entry.status == DecisionStatus.PASS]
    return max(eligible, key=lambda entry: (entry.score, entry.manifest_hash)) if eligible else None
