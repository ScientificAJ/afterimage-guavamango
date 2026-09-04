from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.candidate import ET, StockBar, UNIVERSE
from experiments.strategy_candidates.cross_asset_regime.qqq_regime_candidate import (
    FOCAL_VARIANT,
    qqq_regime_signal,
)


def _bar(symbol: str, day: date, open_price: str, close_price: str) -> StockBar:
    opened = Decimal(open_price)
    closed = Decimal(close_price)
    return StockBar(
        symbol,
        datetime.combine(day, time(9, 30), ET).astimezone(UTC),
        opened,
        max(opened, closed),
        min(opened, closed),
        closed,
        1000,
    )


def _window(session: date) -> list[StockBar]:
    prior = session - timedelta(days=1)
    rows = [_bar(symbol, prior, "99", "100") for symbol in UNIVERSE]
    rows.extend(_bar(symbol, session, "101", "102") for symbol in UNIVERSE)
    return rows


def test_risk_on_bullish_cell_is_excluded() -> None:
    session = date(2024, 2, 1)
    spy = tuple((session - timedelta(days=offset), Decimal(121 - offset)) for offset in range(21, 0, -1))
    assert qqq_regime_signal(FOCAL_VARIANT, _window(session), spy, session) is None


def test_risk_off_bullish_signal_is_qqq_only() -> None:
    session = date(2024, 2, 1)
    spy = tuple((session - timedelta(days=offset), Decimal(121 + offset)) for offset in range(21, 0, -1))
    signal = qqq_regime_signal(FOCAL_VARIANT, _window(session), spy, session)
    assert signal is not None
    assert signal.underlying == "QQQ"
    assert signal.direction == "bullish"
    assert signal.regime == "risk_off_bullish"
