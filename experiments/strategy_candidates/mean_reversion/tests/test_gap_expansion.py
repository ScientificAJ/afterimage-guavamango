from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.gap_expansion import (
    GapParameters,
    detect_gap_expansion,
)


def _session(symbol: str, day: date, compressed: bool = False) -> tuple[Bar, ...]:
    scale = {"SPY": 1.0, "QQQ": 0.8, "IWM": 0.4}[symbol]
    base = 100 * scale
    spread = 0.2 if compressed else 1.5
    start = datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC)
    return (
        Bar(start, base, base + spread, base - spread, base + 0.1, 1_000),
        Bar(start + timedelta(minutes=5), base + 0.1, base + spread, base - spread, base + 0.2, 1_000),
    )


def test_gap_expansion_uses_prior_compression_and_completed_opening_bar_only() -> None:
    days = (date(2025, 9, 2), date(2025, 9, 3), date(2025, 9, 4), date(2025, 9, 5), date(2025, 9, 8))
    bars = {}
    for symbol in ("SPY", "QQQ", "IWM"):
        history = [
            row
            for day in days[:-1]
            for row in _session(symbol, day, compressed=day == days[-2])
        ]
        prior_close = history[-1].close
        current_start = datetime(2025, 9, 8, 13, 30, tzinfo=UTC)
        opening = Bar(
            current_start,
            prior_close * 1.002,
            prior_close * 1.006,
            prior_close * 1.001,
            prior_close * 1.005,
            2_000,
        )
        bars[symbol] = (*history, opening)
    params = GapParameters(3, Decimal("0.6"), Decimal("0.001"), Decimal("0.001"), 3)

    original = detect_gap_expansion(bars, params)
    destructive_future = Bar(
        datetime(2025, 9, 8, 13, 35, tzinfo=UTC), 200, 210, 50, 60, 100_000
    )
    with_future = detect_gap_expansion(
        {symbol: (*rows, destructive_future) for symbol, rows in bars.items()}, params
    )

    assert {row.underlying for row in original} == {"SPY", "QQQ", "IWM"}
    assert all(row.signal.direction == "bullish" for row in original)
    assert all(row.signal.completed_at.minute == 35 for row in original)
    assert with_future == original


def test_gap_without_cross_symbol_confirmation_is_rejected() -> None:
    days = (date(2025, 9, 2), date(2025, 9, 3), date(2025, 9, 4), date(2025, 9, 5), date(2025, 9, 8))
    bars = {
        symbol: tuple(
            row
            for day in days
            for row in _session(symbol, day, compressed=day == days[-2])
        )
        for symbol in ("SPY", "QQQ", "IWM")
    }
    params = GapParameters(3, Decimal("0.6"), Decimal("0.01"), Decimal("0.01"), 2)

    assert detect_gap_expansion(bars, params) == ()
