"""Slow weekly cross-sectional ETF rotation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal,Sequence

try:
    from .candidate import DataExclusion
    from .multiday_rotation_candidate import DailyBar,RotationSignal,TRADE_UNIVERSE,_atr
except ImportError:
    from candidate import DataExclusion  # type: ignore[no-redef]
    from multiday_rotation_candidate import DailyBar,RotationSignal,TRADE_UNIVERSE,_atr  # type: ignore[no-redef]


@dataclass(frozen=True)
class WeeklyRotationVariant:
    name:str
    momentum_lookback:int
    atr_multiplier:Decimal
    hold_sessions:int=10


VARIANTS=(WeeklyRotationVariant('wk_rs60_a150_h10',60,Decimal('1.5')),WeeklyRotationVariant('wk_rs60_a200_h10',60,Decimal('2')),WeeklyRotationVariant('wk_rs120_a150_h10',120,Decimal('1.5')),WeeklyRotationVariant('wk_rs120_a200_h10',120,Decimal('2')))


def _series(bars:Sequence[DailyBar],symbol:str,session:date)->list[DailyBar]:return sorted((b for b in bars if b.symbol==symbol and b.session<=session),key=lambda b:b.session)


def weekly_rotation_signal(variant:WeeklyRotationVariant,bars:Sequence[DailyBar],session:date,*,is_week_end:bool)->RotationSignal|None:
    if not is_week_end:return None
    symbols=('SPY',*TRADE_UNIVERSE);h={s:_series(bars,s,session) for s in symbols};minimum=max(121,variant.momentum_lookback+1)
    if any(len(x)<minimum or x[-1].session!=session for x in h.values()):raise DataExclusion('INCOMPLETE_DAILY_HISTORY')
    returns={s:h[s][-1].close/h[s][-variant.momentum_lookback-1].close-Decimal(1) for s in TRADE_UNIVERSE};spy=h['SPY'];sma100=sum((x.close for x in spy[-100:]),Decimal(0))/Decimal(100);spy_return=spy[-1].close/spy[-21].close-Decimal(1);dispersion=max(returns.values())-min(returns.values())
    if dispersion<Decimal('.05'):return None
    if spy[-1].close>sma100 and spy_return>0 and sum(x>0 for x in returns.values())>=4:
        direction:Literal['bullish','bearish']='bullish';regime:Literal['risk_on','risk_off']='risk_on';underlying=sorted(TRADE_UNIVERSE,key=lambda s:(-returns[s],s))[0]
    elif spy[-1].close<sma100 and spy_return<0 and sum(x<0 for x in returns.values())>=4:
        direction='bearish';regime='risk_off';underlying=sorted(TRADE_UNIVERSE,key=lambda s:(returns[s],s))[0]
    else:return None
    return RotationSignal(session,direction,underlying,_atr(h[underlying]),variant.name,regime,dispersion)
