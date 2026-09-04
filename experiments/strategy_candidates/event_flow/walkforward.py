"""Chronological variant selection with a hard past-only fold boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from .engine import Trade
from .metrics import summarize_returns


def select_for_fold(
    trades_by_variant: Mapping[str, Sequence[Trade]],
    fold_start: datetime,
    *,
    minimum_samples: int = 12,
) -> str | None:
    candidates: list[tuple[Decimal, Decimal, int, str]] = []
    for name, trades in trades_by_variant.items():
        training = tuple(item for item in trades if item.entry_at < fold_start)
        if len(training) < minimum_samples:
            continue
        stats = summarize_returns(
            (item.entry_at.date(), item.symbol, item.return_r) for item in training
        )
        if stats.net_r <= 0 or stats.profit_factor <= Decimal(1):
            continue
        # Prefer repeatable expectancy, then PF and sample size.  All values are
        # based strictly before fold_start; no fold outcomes enter selection.
        candidates.append((stats.expectancy_r, stats.profit_factor, stats.sample_count, name))
    return max(candidates)[-1] if candidates else None
