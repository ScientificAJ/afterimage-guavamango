from __future__ import annotations

from datetime import date
from decimal import Decimal

from experiments.strategy_candidates.event_flow.metrics import summarize_returns


def test_metrics_include_profit_factor_expectancy_drawdown_and_concentration() -> None:
    rows = [
        (date(2026, 1, 2), "XLK", Decimal(3)),
        (date(2026, 1, 3), "XLK", Decimal(-1)),
        (date(2026, 2, 2), "XLF", Decimal(1)),
        (date(2026, 2, 3), "XLF", Decimal("-0.5")),
    ]

    result = summarize_returns(rows)

    assert result.sample_count == 4
    assert result.profit_factor == Decimal("2.666666666666666666666666667")
    assert result.expectancy_r == Decimal("0.625")
    assert result.max_drawdown_r == Decimal(1)
    assert result.positive_month_fraction == Decimal(1)
    assert result.positive_underlyings == 2
    assert result.largest_win_fraction == Decimal("0.75")
