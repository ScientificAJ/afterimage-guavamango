from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.multi_day_trend import (
    CarryParameters,
    detect_multi_day_trend,
)


def _trend_rows(symbol: str) -> tuple[Bar, ...]:
    scale = {"SPY": 1.0, "QQQ": 0.8, "IWM": 0.4}[symbol]
    days = (date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7), date(2026, 1, 8))
    rows = []
    for day_index, day in enumerate(days):
        start = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
        base = 100 * scale + day_index
        rows.extend(
            (
                Bar(start, base, base + 0.4, base - 0.2, base + 0.2, 1_000),
                Bar(start + timedelta(hours=5, minutes=15), base + 0.2, base + 1.2, base, base + 1, 1_000),
            )
        )
    return tuple(rows)


def test_multi_day_cross_index_trend_uses_completed_cutoff_and_prior_sessions() -> None:
    bars = {symbol: _trend_rows(symbol) for symbol in ("SPY", "QQQ", "IWM")}
    params = CarryParameters(lookback_sessions=2, min_return=Decimal("0.005"), min_confirmations=2)

    original = detect_multi_day_trend(bars, params)
    future = Bar(datetime(2026, 1, 8, 20, 0, tzinfo=UTC), 100, 200, 50, 60, 10_000)
    with_future = detect_multi_day_trend(
        {symbol: (*rows, future) for symbol, rows in bars.items()}, params
    )

    last_session = [row for row in original if row.signal.signal_bar_start.date() == date(2026, 1, 8)]
    assert {row.underlying for row in last_session} == {"SPY", "QQQ", "IWM"}
    assert all(row.signal.direction == "bullish" for row in last_session)
    assert all(row.signal.completed_at.minute == 50 for row in last_session)
    assert with_future == original
