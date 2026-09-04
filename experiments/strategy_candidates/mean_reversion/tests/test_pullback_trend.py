from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.pullback_trend import (
    PullbackParameters,
    detect_pullback_resumption,
)


def _rows(symbol: str) -> tuple[Bar, ...]:
    scale = {"SPY": 1.0, "QQQ": 0.8, "IWM": 0.4}[symbol]
    start = datetime(2026, 5, 4, 13, 30, tzinfo=UTC)
    rows = []
    for index in range(12):
        price = 100 * scale + index * 0.2
        rows.append(Bar(start + timedelta(minutes=5 * index), price, price + .2, price - .1, price + .1, 1_000))
    prior = rows[-1]
    rows.append(Bar(start + timedelta(minutes=60), prior.close, prior.close + .1, prior.close - .4, prior.close - .2, 1_000))
    red = rows[-1]
    rows.append(Bar(start + timedelta(minutes=65), red.close, red.high + .3, red.low, red.high + .2, 1_500))
    return tuple(rows)


def test_cross_index_pullback_resumption_waits_for_completed_engulfing_bar() -> None:
    bars = {symbol: _rows(symbol) for symbol in ("SPY", "QQQ", "IWM")}
    params = PullbackParameters(6, Decimal("0.001"), 2, Decimal("0.8"), 10 * 60, 14 * 60 + 30)

    original = detect_pullback_resumption(bars, params)
    future = Bar(datetime(2026, 5, 4, 15, 0, tzinfo=UTC), 200, 210, 50, 60, 100_000)
    with_future = detect_pullback_resumption(
        {symbol: (*rows, future) for symbol, rows in bars.items()}, params
    )

    assert {row.underlying for row in original} == {"SPY", "QQQ", "IWM"}
    assert all(row.signal.direction == "bullish" for row in original)
    assert all(row.signal.signal_bar_start == datetime(2026, 5, 4, 14, 35, tzinfo=UTC) for row in original)
    assert all(row.signal.completed_at == datetime(2026, 5, 4, 14, 40, tzinfo=UTC) for row in original)
    assert with_future == original
