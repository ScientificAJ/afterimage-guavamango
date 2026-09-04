from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal

from afterimage.contracts.models import BlindTwin, EvidenceQuery

from .vault import BlindFeatureRow


def _robust_scale(values: list[float]) -> tuple[float, float]:
    median = statistics.median(values)
    deviations = [abs(value - median) for value in values]
    mad = statistics.median(deviations) or 1.0
    return median, 1.4826 * mad


def retrieve_twins(
    query: EvidenceQuery,
    rows: Sequence[BlindFeatureRow],
    maximum_per_cluster: int = 3,
) -> tuple[BlindTwin, ...]:
    if not rows:
        return ()
    scales: dict[str, tuple[float, float]] = {}
    for name in query.feature_names:
        available = [row.features[name] for row in rows if name in row.features]
        if not available:
            raise ValueError(f"feature unavailable in blind vault: {name}")
        scales[name] = _robust_scale(available)
    ranked: list[tuple[float, BlindFeatureRow]] = []
    for row in rows:
        if any(name not in row.features for name in query.feature_names):
            continue
        distance = math.sqrt(
            sum(
                ((row.features[name] - query.feature_values[index]) / scales[name][1]) ** 2
                for index, name in enumerate(query.feature_names)
            )
        )
        ranked.append((distance, row))
    ranked.sort(key=lambda item: (item[0], item[1].twin_id))
    chosen: list[tuple[float, BlindFeatureRow]] = []
    clusters: Counter[str] = Counter()
    for distance, row in ranked:
        if clusters[row.cluster_id] >= maximum_per_cluster:
            continue
        chosen.append((distance, row))
        clusters[row.cluster_id] += 1
        if len(chosen) >= query.k:
            break
    if not chosen:
        return ()
    raw_weights = [Decimal(str(1 / (1 + distance))) for distance, _ in chosen]
    cap = query.maximum_twin_weight
    weights = _cap_and_normalize(raw_weights, cap)
    return tuple(
        BlindTwin(
            twin_id=row.twin_id,
            features=tuple(row.features[name] for name in query.feature_names),
            distance=Decimal(str(round(distance, 12))),
            weight=weight,
            cluster_id=row.cluster_id,
        )
        for (distance, row), weight in zip(chosen, weights, strict=True)
    )


def _cap_and_normalize(raw: Sequence[Decimal], cap: Decimal) -> tuple[Decimal, ...]:
    if len(raw) * cap < Decimal(1):
        raise ValueError("maximum twin weight is infeasible for selected cohort")
    weights = [value / sum(raw) for value in raw]
    for _ in range(20):
        over = [index for index, value in enumerate(weights) if value > cap]
        if not over:
            break
        fixed = sum((cap for _ in over), start=Decimal(0))
        free = [index for index in range(len(weights)) if index not in over]
        free_total = sum(weights[index] for index in free)
        for index in over:
            weights[index] = cap
        for index in free:
            weights[index] = weights[index] / free_total * (Decimal(1) - fixed)
    normalized = [value / sum(weights) for value in weights]
    return tuple(normalized)
