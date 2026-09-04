"""Near-unanimous breadth persistence rotation."""
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
class UnanimousVariant:
    name:str
    breadth_required:int
    atr_multiplier:Decimal
    hold_sessions:int=5
VARIANTS=(UnanimousVariant('ub_b6_a125_h05',6,Decimal('1.25')),UnanimousVariant('ub_b6_a150_h05',6,Decimal('1.5')),UnanimousVariant('ub_b7_a125_h05',7,Decimal('1.25')),UnanimousVariant('ub_b7_a150_h05',7,Decimal('1.5')))
def _series(bars:Sequence[DailyBar],symbol:str,session:date):return sorted((b for b in bars if b.symbol==symbol and b.session<=session),key=lambda b:b.session)
def unanimous_signal(v:UnanimousVariant,bars:Sequence[DailyBar],session:date)->RotationSignal|None:
    symbols=('SPY',*TRADE_UNIVERSE);h={s:_series(bars,s,session) for s in symbols}
    if any(len(x)<51 or x[-1].session!=session for x in h.values()):raise DataExclusion('INCOMPLETE_DAILY_HISTORY')
    spy=h['SPY'];sma=sum((x.close for x in spy[-50:]),Decimal(0))/Decimal(50);returns={s:h[s][-1].close/h[s][-21].close-Decimal(1) for s in TRADE_UNIVERSE};disp=max(returns.values())-min(returns.values())
    if spy[-1].close<=sma or spy[-1].close<=spy[-11].close or sum(x>0 for x in returns.values())<v.breadth_required or disp<Decimal('.02'):return None
    underlying=sorted(TRADE_UNIVERSE,key=lambda s:(-returns[s],s))[0];return RotationSignal(session,'bullish',underlying,_atr(h[underlying]),v.name,'risk_on',disp)
