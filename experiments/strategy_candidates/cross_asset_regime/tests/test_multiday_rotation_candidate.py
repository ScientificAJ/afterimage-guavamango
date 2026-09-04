from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import (
    DailyBar,
    MultiDayCosts,
    RotationSignal,
    RotationVariant,
    rotation_signal,
    simulate_multiday_trade,
)


def _daily(symbol: str, index: int, close: Decimal) -> DailyBar:
    session = date(2024, 1, 1) + timedelta(days=index)
    return DailyBar(symbol, session, datetime(session.year, session.month, session.day, 21, tzinfo=UTC), close, close + 1, close - 1, close, 1000)


def test_risk_on_signal_selects_strongest_completed_etf() -> None:
    symbols = ("SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")
    bars = []
    for index in range(60):
        for rank, symbol in enumerate(symbols):
            growth = Decimal("0.4") + Decimal(rank) / Decimal(20)
            bars.append(_daily(symbol, index, Decimal(100) + growth * index))
    variant = RotationVariant("x", 20, Decimal("0.50"), 5)
    signal = rotation_signal(variant, bars, bars[-1].session)
    assert signal is not None
    assert signal.direction == "bullish"
    assert signal.underlying == "XLY"


def test_multiday_target_is_net_three_r_and_stop_has_precedence() -> None:
    variant = RotationVariant("x", 20, Decimal("0.50"), 2)
    signal = RotationSignal(date(2024, 1, 1), "bullish", "QQQ", Decimal(1), "x", "risk_on", Decimal("0.10"))
    bars = [
        DailyBar("QQQ", date(2024, 1, 2), datetime(2024, 1, 2, 21, tzinfo=UTC), Decimal(100), Decimal(104), Decimal(98), Decimal(101), 1000),
        DailyBar("QQQ", date(2024, 1, 3), datetime(2024, 1, 3, 21, tzinfo=UTC), Decimal(101), Decimal(102), Decimal(100), Decimal(101), 1000),
    ]
    trade = simulate_multiday_trade(signal, bars, variant, MultiDayCosts())
    assert trade.target_to_stop >= Decimal(3)
    assert trade.outcome == "stop"
