from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.event_flow.engine import Bar
from experiments.strategy_candidates.event_flow.market_data import (
    ET,
    aggregate_daily,
    normalize_daily_opens,
    regular_sessions,
    session_close,
)
from experiments.strategy_candidates.event_flow.run_research import build_features


def _bar(hour: int, minute: int, price: str) -> Bar:
    value = Decimal(price)
    return Bar(
        symbol="SPY",
        timestamp=datetime(2026, 1, 2, hour, minute, tzinfo=UTC),
        open=value,
        high=value + Decimal(1),
        low=value - Decimal(1),
        close=value,
        volume=100,
    )


def test_daily_aggregation_excludes_extended_hours_and_completes_after_close() -> None:
    bars = (_bar(13, 0, "50"), _bar(14, 30, "100"), _bar(19, 45, "102"), _bar(21, 0, "60"))

    sessions = regular_sessions(bars)
    daily = aggregate_daily(bars, minimum_bars=2)
    session_bars = next(iter(sessions.values()))

    assert session_bars[0].open == Decimal(100)
    assert len(session_bars) == 2
    assert daily[0].open == Decimal(100)
    assert daily[0].close == Decimal(102)
    assert daily[0].timestamp > session_bars[-1].timestamp


def test_daily_api_timestamps_are_normalized_to_tradeable_session_times() -> None:
    raw = (_bar(4, 0, "100"),)

    normalized = normalize_daily_opens(raw)

    assert normalized[0].timestamp.hour == 14
    assert normalized[0].timestamp.minute == 30
    assert session_close(normalized[0]).hour == 21


def test_daily_features_are_only_complete_at_session_close() -> None:
    bars = tuple(
        Bar(
            symbol="SPY",
            timestamp=datetime(2025, 1, 2, 14, 30, tzinfo=UTC) + timedelta(days=index),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=100,
        )
        for index in range(112)
    )

    features = build_features({"SPY": bars})

    assert next(iter(features.values()))[0].completed_at.astimezone(ET).hour == 16
