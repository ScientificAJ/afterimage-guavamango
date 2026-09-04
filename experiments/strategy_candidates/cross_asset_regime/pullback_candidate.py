"""Broad-trend, cross-sectional-leader pullback resumption signal."""

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
class PullbackVariant:
    name: str
    minimum_depth_atr: Decimal
    atr_multiplier: Decimal
    hold_sessions: int = 5


VARIANTS = (
    PullbackVariant("pb_d00_a50_h05", Decimal("0"), Decimal("0.50")),
    PullbackVariant("pb_d00_a75_h05", Decimal("0"), Decimal("0.75")),
    PullbackVariant("pb_d25_a50_h05", Decimal("0.25"), Decimal("0.50")),
    PullbackVariant("pb_d25_a75_h05", Decimal("0.25"), Decimal("0.75")),
)


def _series(bars: Sequence[DailyBar], symbol: str, session: date) -> list[DailyBar]:
    return sorted((bar for bar in bars if bar.symbol == symbol and bar.session <= session), key=lambda row: row.session)


def pullback_signal(variant: PullbackVariant, bars: Sequence[DailyBar], session: date) -> RotationSignal | None:
    symbols=("SPY",*TRADE_UNIVERSE);history={s:_series(bars,s,session) for s in symbols}
    if any(len(rows)<52 or rows[-1].session!=session for rows in history.values()):raise DataExclusion("INCOMPLETE_DAILY_HISTORY")
    above={}
    for symbol in TRADE_UNIVERSE:
        rows=history[symbol];sma50=sum((r.close for r in rows[-50:]),Decimal(0))/Decimal(50);above[symbol]=rows[-1].close>sma50
    spy=history['SPY'];spy_sma=sum((r.close for r in spy[-50:]),Decimal(0))/Decimal(50)
    prior_returns={s:history[s][-2].close/history[s][-22].close-Decimal(1) for s in TRADE_UNIVERSE}
    dispersion=max(prior_returns.values())-min(prior_returns.values())
    if dispersion<Decimal('0.02'):return None
    if spy[-1].close>spy_sma and sum(above.values())>=5:
        direction:Literal['bullish','bearish']='bullish';regime:Literal['risk_on','risk_off']='risk_on';underlying=sorted(TRADE_UNIVERSE,key=lambda s:(-prior_returns[s],s))[0]
        rows=history[underlying];atr=_atr(rows);sma20=sum((r.close for r in rows[-20:]),Decimal(0))/Decimal(20);depth=rows[-2].close-rows[-1].close
        if prior_returns[underlying]<=0 or rows[-1].close<=sma20 or depth<=0 or depth<variant.minimum_depth_atr*atr:return None
    elif spy[-1].close<spy_sma and sum(not x for x in above.values())>=5:
        direction='bearish';regime='risk_off';underlying=sorted(TRADE_UNIVERSE,key=lambda s:(prior_returns[s],s))[0]
        rows=history[underlying];atr=_atr(rows);sma20=sum((r.close for r in rows[-20:]),Decimal(0))/Decimal(20);depth=rows[-1].close-rows[-2].close
        if prior_returns[underlying]>=0 or rows[-1].close>=sma20 or depth<=0 or depth<variant.minimum_depth_atr*atr:return None
    else:return None
    return RotationSignal(session,direction,underlying,atr,variant.name,regime,dispersion)
