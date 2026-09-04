from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal
from statistics import NormalDist

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.models import (
    BlindTwin,
    EvidenceDecision,
    EvidenceMetrics,
    RevealedOutcome,
)


class EvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    minimum_n: int = 30
    minimum_n_eff: Decimal = Decimal(30)
    confidence: Decimal = Decimal("0.95")
    break_even_probability: Decimal = Decimal("0.25")
    probability_margin: Decimal = Decimal("0.03")
    minimum_expected_value_r: Decimal = Decimal("0.10")
    minimum_positive_loo_fraction: Decimal = Decimal("0.80")
    minimum_placebo_edge_r: Decimal = Decimal("0.05")
    maximum_drawdown_r: Decimal = Decimal(8)


def effective_sample_size(weights: Sequence[Decimal]) -> Decimal:
    total = sum(weights)
    if total <= 0:
        return Decimal(0)
    normalized = [weight / total for weight in weights]
    return Decimal(1) / sum(weight * weight for weight in normalized)


def wilson_lower(success_probability: Decimal, n_eff: Decimal, confidence: Decimal) -> Decimal:
    if n_eff <= 0:
        return Decimal(0)
    z = Decimal(str(NormalDist().inv_cdf(float(confidence))))
    n = n_eff
    center = success_probability + z * z / (2 * n)
    radius = z * Decimal(
        str(
            math.sqrt(
                float(success_probability * (1 - success_probability) / n + z * z / (4 * n * n))
            )
        )
    )
    return (center - radius) / (1 + z * z / n)


def _maximum_drawdown(values: Sequence[Decimal]) -> Decimal:
    equity = peak = Decimal(0)
    maximum = Decimal(0)
    for value in values:
        equity += value
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def evaluate_evidence(
    twins: Sequence[BlindTwin],
    outcomes: Sequence[RevealedOutcome],
    commit_hash: str,
    reveal_hash: str,
    policy: EvidencePolicy | None = None,
) -> EvidenceDecision:
    policy = policy or EvidencePolicy()
    outcome_by_id = {outcome.twin_id: outcome for outcome in outcomes}
    paired = [
        (twin, outcome_by_id[twin.twin_id]) for twin in twins if twin.twin_id in outcome_by_id
    ]
    weights = [twin.weight for twin, _ in paired]
    n_eff = effective_sample_size(weights)
    total_weight = sum(weights) or Decimal(1)
    probability = (
        sum(
            twin.weight
            for twin, outcome in paired
            if outcome.target_first is True and not outcome.censored
        )
        / total_weight
    )
    expected_value = sum(twin.weight * outcome.return_r for twin, outcome in paired) / total_weight
    lower = wilson_lower(probability, n_eff, policy.confidence)
    by_cluster: dict[str, list[tuple[BlindTwin, RevealedOutcome]]] = defaultdict(list)
    for pair in paired:
        by_cluster[pair[0].cluster_id].append(pair)
    loo_values = []
    for cluster in by_cluster:
        remainder = [
            pair for key, values in by_cluster.items() if key != cluster for pair in values
        ]
        remainder_weight = sum(pair[0].weight for pair in remainder)
        if remainder_weight:
            loo_values.append(
                sum(pair[0].weight * pair[1].return_r for pair in remainder) / remainder_weight
            )
    positive_loo = (
        Decimal(sum(value > 0 for value in loo_values)) / Decimal(len(loo_values))
        if loo_values
        else Decimal(0)
    )
    placebo_edge = expected_value
    drawdown = _maximum_drawdown([outcome.return_r for _, outcome in paired])
    coverage = Decimal(len(paired)) / Decimal(max(1, len(twins)))
    metrics = EvidenceMetrics(
        n=len(paired),
        n_eff=n_eff,
        target_first_probability=probability,
        lower_confidence_bound=lower,
        expected_value_r=expected_value,
        maximum_drawdown_r=drawdown,
        positive_loo_fraction=positive_loo,
        placebo_edge_r=placebo_edge,
        coverage=coverage,
        confidence_method=f"one-sided Wilson {policy.confidence}",
    )
    reasons = []
    if len(paired) < policy.minimum_n:
        reasons.append("INSUFFICIENT_RAW_SAMPLE")
    if n_eff < policy.minimum_n_eff:
        reasons.append("INSUFFICIENT_EFFECTIVE_SAMPLE")
    if lower <= policy.break_even_probability + policy.probability_margin:
        reasons.append("PROBABILITY_LOWER_BOUND")
    if expected_value <= policy.minimum_expected_value_r:
        reasons.append("EXPECTED_VALUE")
    if positive_loo < policy.minimum_positive_loo_fraction:
        reasons.append("LEAVE_ONE_CLUSTER_OUT")
    if placebo_edge < policy.minimum_placebo_edge_r:
        reasons.append("PLACEBO_SEPARATION")
    if drawdown > policy.maximum_drawdown_r:
        reasons.append("MAXIMUM_DRAWDOWN")
    status = DecisionStatus.PASS
    if any(reason.startswith("INSUFFICIENT") for reason in reasons):
        status = DecisionStatus.INSUFFICIENT_EVIDENCE
    elif reasons:
        status = DecisionStatus.REJECT
    return EvidenceDecision(
        status=status,
        metrics=metrics,
        reasons=tuple(reasons),
        commit_hash=commit_hash,
        reveal_hash=reveal_hash,
    )
