from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from experiments.strategy_candidates.cross_asset_regime.candidate import ScoredTrade
from experiments.strategy_candidates.cross_asset_regime.run_research import (
    assert_read_only_arguments,
    canonical_hash,
    development_folds,
    freeze_candidate,
    partition_for,
    _signal_from_selection,
    _normalize_result_rows,
)


def _weekdays(start: date, end: date) -> tuple[date, ...]:
    rows = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() < 5:
            rows.append(cursor)
        cursor += timedelta(days=1)
    return tuple(rows)


def test_acquisition_guard_allows_only_declared_read_endpoints() -> None:
    assert_read_only_arguments(("data", "bars", "--symbol", "QQQ"))
    assert_read_only_arguments(("option", "contracts", "--underlying-symbols", "IWM"))
    assert_read_only_arguments(("account", "get"))
    with pytest.raises(ValueError, match="READ_ONLY"):
        assert_read_only_arguments(("order", "submit", "--dry-run"))
    with pytest.raises(ValueError, match="READ_ONLY"):
        assert_read_only_arguments(("option", "contracts", "--cancel", "x"))


def test_cache_hash_is_canonical_and_partition_dates_are_frozen() -> None:
    assert canonical_hash({"b": 2, "a": 1}) == canonical_hash({"a": 1, "b": 2})
    assert partition_for(date(2026, 7, 31)) == "development"
    assert partition_for(date(2026, 8, 3)) == "untouched_holdout"
    assert partition_for(date(2026, 9, 4)) == "outside"


def test_development_folds_expand_and_validate_may_june_july() -> None:
    sessions = _weekdays(date(2026, 1, 2), date(2026, 7, 31))
    folds = development_folds(sessions)
    assert tuple(fold.validation_start.month for fold in folds) == (5, 6, 7)
    assert tuple(fold.training_end.month for fold in folds) == (4, 5, 6)
    assert all(max(fold.training_dates) < min(fold.validation_dates) for fold in folds)
    assert len(folds[0].training_dates) < len(folds[1].training_dates) < len(folds[2].training_dates)


def test_freeze_candidate_uses_only_pooled_development_validation() -> None:
    sessions = _weekdays(date(2026, 1, 2), date(2026, 7, 31))
    folds = development_folds(sessions)
    validation_dates = tuple(day for fold in folds for day in fold.validation_dates)
    rows = {
        "a": tuple(ScoredTrade(day, Decimal("0.10"), Decimal("10")) for day in validation_dates[:9]),
        "b": (
            *tuple(ScoredTrade(day, Decimal("0.05"), Decimal("5")) for day in validation_dates[:9]),
            ScoredTrade(date(2026, 8, 3), Decimal("100"), Decimal("10000")),
        ),
    }
    frozen = freeze_candidate(rows, folds, minimum_samples=8)
    assert frozen["selected_variant"] == "a"
    assert frozen["validation_metrics"].sample_count == 9
    assert frozen["observed_partitions"] == ("development_validation",)


def test_cached_selection_rehydrates_without_script_only_imports() -> None:
    signal = _signal_from_selection(
        {
            "session": "2026-05-04",
            "completed_at": "2026-05-04T10:30:00-04:00",
            "direction": "bullish",
            "underlying": "QQQ",
            "reference_price": "600.25",
            "breadth_count": 6,
            "mean_return": "0.002",
            "variant": "b6_spy10_h07_3r",
        }
    )
    assert signal.completed_at.isoformat() == "2026-05-04T10:30:00-04:00"
    assert signal.variant == "b6_spy10_h07_3r"


def test_single_symbol_stock_bar_lists_are_tagged_with_requested_symbol() -> None:
    rows = _normalize_result_rows(
        [{"t": "2026-05-04T13:30:00Z", "o": 600, "h": 601, "l": 599, "c": 600.5, "v": 100}],
        ("data", "bars", "--symbol", "QQQ"),
        result_key="bars",
    )
    assert rows[0]["symbol"] == "QQQ"
