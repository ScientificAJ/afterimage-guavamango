from __future__ import annotations

from datetime import date
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.candidate import ScoredTrade
from experiments.strategy_candidates.cross_asset_regime.run_gap_research import (
    admission_criteria,
    select_gap_variant,
)


def test_gap_variant_selection_cannot_observe_pseudo_oos() -> None:
    rows = {
        "a": tuple(ScoredTrade(date(2026, month, day), Decimal("0.30"), Decimal("30")) for month in (1, 2, 3, 4) for day in (5, 6, 7)),
        "b": (
            *tuple(ScoredTrade(date(2026, month, day), Decimal("0.20"), Decimal("20")) for month in (1, 2, 3, 4) for day in (5, 6, 7)),
            ScoredTrade(date(2026, 5, 4), Decimal("100"), Decimal("10000")),
        ),
    }
    assert select_gap_variant(rows, minimum_samples=12) == "a"


def test_admission_requires_every_floor_and_flags_exceptional_sample_path() -> None:
    passing = admission_criteria(
        target_stop_ratio=Decimal("3.01"),
        profit_factor=Decimal("2.20"),
        expectancy_r=Decimal("0.30"),
        sample_count=35,
        max_drawdown_r=Decimal("5.0"),
        positive_underlyings=2,
        positive_regimes=1,
        positive_month_fraction=Decimal("0.60"),
        stressed_net_pnl=Decimal("1"),
        positive_neighbor_fraction=Decimal("0.67"),
        largest_win_fraction=Decimal("0.20"),
    )
    assert passing["admitted"] is True
    assert passing["exceptional_sample_used"] is False

    failing = admission_criteria(**{**passing["inputs"], "expectancy_r": Decimal("0.24")})
    assert failing["admitted"] is False
    assert failing["criteria"]["expectancy_at_least_0_25r"] is False
