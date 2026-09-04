from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.breakout_candidate import BreakoutVariant, breakout_signal
from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar


def test_breakout_requires_new_channel_high_and_selects_largest() -> None:
    symbols = ("SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")
    bars = []
    for index in range(55):
        session = date(2024, 1, 1) + timedelta(days=index)
        for rank, symbol in enumerate(symbols):
            close = Decimal(100 + index) + Decimal(rank * index) / Decimal(20)
            bars.append(DailyBar(symbol, session, datetime(session.year, session.month, session.day, 21, tzinfo=UTC), close, close, close - 1, close, 1000))
    signal = breakout_signal(BreakoutVariant("x", 10, Decimal("0.50")), bars, bars[-1].session)
    assert signal is not None
    assert signal.direction == "bullish"
    assert signal.underlying == "XLY"
