"""Low-noise broad-consensus long-only ETF rotation."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Sequence
try:
    from .candidate import DataExclusion
    from .multiday_rotation_candidate import DailyBar,RotationSignal,TRADE_UNIVERSE,_atr
except ImportError:
    from candidate import DataExclusion  # type: ignore[no-redef]
    from multiday_rotation_candidate import DailyBar,RotationSignal,TRADE_UNIVERSE,_atr  # type: ignore[no-redef]
@dataclass(frozen=True)
class LowVolVariant:
    name:str
    maximum_mean_abs_spy_return:Decimal
    atr_multiplier:Decimal
    hold_sessions:int=5
VARIANTS=(LowVolVariant('lv_v12_a100_h05',Decimal('.012'),Decimal('1')),LowVolVariant('lv_v12_a125_h05',Decimal('.012'),Decimal('1.25')),LowVolVariant('lv_v16_a100_h05',Decimal('.016'),Decimal('1')),LowVolVariant('lv_v16_a125_h05',Decimal('.016'),Decimal('1.25')))
def _series(bars:Sequence[DailyBar],symbol:str,session:date):return sorted((b for b in bars if b.symbol==symbol and b.session<=session),key=lambda b:b.session)
def lowvol_signal(v:LowVolVariant,bars:Sequence[DailyBar],session:date)->RotationSignal|None:
    symbols=('SPY',*TRADE_UNIVERSE);h={s:_series(bars,s,session) for s in symbols}
    if any(len(x)<51 or x[-1].session!=session for x in h.values()):raise DataExclusion('INCOMPLETE_DAILY_HISTORY')
    spy=h['SPY'];sma=sum((x.close for x in spy[-50:]),Decimal(0))/Decimal(50);noise=sum((abs(spy[i].close/spy[i-1].close-Decimal(1)) for i in range(len(spy)-19,len(spy))),Decimal(0))/Decimal(19);returns={s:h[s][-1].close/h[s][-21].close-Decimal(1) for s in TRADE_UNIVERSE};disp=max(returns.values())-min(returns.values())
    if spy[-1].close<=sma or spy[-1].close<=spy[-11].close or noise>v.maximum_mean_abs_spy_return or sum(x>0 for x in returns.values())<6 or disp<Decimal('.02'):return None
    underlying=sorted(TRADE_UNIVERSE,key=lambda s:(-returns[s],s))[0];return RotationSignal(session,'bullish',underlying,_atr(h[underlying]),v.name,'risk_on',disp)
