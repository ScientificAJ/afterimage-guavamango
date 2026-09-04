"""Breadth-confirmed multi-day ETF channel breakout."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Sequence

try:
    from .candidate import DataExclusion
    from .multiday_rotation_candidate import DailyBar, RotationSignal, TRADE_UNIVERSE, _atr
except ImportError:
    from candidate import DataExclusion  # type: ignore[no-redef]
    from multiday_rotation_candidate import DailyBar, RotationSignal, TRADE_UNIVERSE, _atr  # type: ignore[no-redef]


@dataclass(frozen=True)
class BreakoutVariant:
    name: str
    channel_lookback: int
    atr_multiplier: Decimal
    hold_sessions: int = 5


VARIANTS = (
    BreakoutVariant("bo_n10_a50_h05", 10, Decimal("0.50")),
    BreakoutVariant("bo_n10_a75_h05", 10, Decimal("0.75")),
    BreakoutVariant("bo_n20_a50_h05", 20, Decimal("0.50")),
    BreakoutVariant("bo_n20_a75_h05", 20, Decimal("0.75")),
)


def _series(bars: Sequence[DailyBar], symbol: str, session: date) -> list[DailyBar]:
    return sorted((bar for bar in bars if bar.symbol == symbol and bar.session <= session), key=lambda row: row.session)


def breakout_signal(
    variant: BreakoutVariant, bars: Sequence[DailyBar], session: date
) -> RotationSignal | None:
    symbols = ("SPY", *TRADE_UNIVERSE)
    history = {symbol: _series(bars, symbol, session) for symbol in symbols}
    minimum = max(51, variant.channel_lookback + 1)
    if any(len(rows) < minimum or rows[-1].session != session for rows in history.values()):
        raise DataExclusion("INCOMPLETE_DAILY_HISTORY")
    above = {}
    for symbol in TRADE_UNIVERSE:
        rows = history[symbol]
        sma = sum((row.close for row in rows[-50:]), Decimal(0)) / Decimal(50)
        above[symbol] = rows[-1].close > sma
    spy = history["SPY"]
    spy_sma = sum((row.close for row in spy[-50:]), Decimal(0)) / Decimal(50)
    if spy[-1].close > spy_sma and sum(above.values()) >= 5:
        direction: Literal["bullish", "bearish"] = "bullish"
        regime: Literal["risk_on", "risk_off"] = "risk_on"
        scores = {}
        for symbol in TRADE_UNIVERSE:
            rows = history[symbol]
            prior_high = max(row.high for row in rows[-variant.channel_lookback - 1 : -1])
            if rows[-1].close > prior_high:
                scores[symbol] = rows[-1].close / prior_high - Decimal(1)
    elif spy[-1].close < spy_sma and sum(not value for value in above.values()) >= 5:
        direction = "bearish"
        regime = "risk_off"
        scores = {}
        for symbol in TRADE_UNIVERSE:
            rows = history[symbol]
            prior_low = min(row.low for row in rows[-variant.channel_lookback - 1 : -1])
            if rows[-1].close < prior_low:
                scores[symbol] = prior_low / rows[-1].close - Decimal(1)
    else:
        return None
    if not scores:
        return None
    underlying = sorted(scores, key=lambda symbol: (-scores[symbol], symbol))[0]
    return RotationSignal(session, direction, underlying, _atr(history[underlying]), variant.name, regime, scores[underlying])
