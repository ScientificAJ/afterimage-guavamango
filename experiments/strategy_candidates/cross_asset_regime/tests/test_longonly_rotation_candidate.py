from __future__ import annotations
from datetime import UTC,date,datetime,timedelta
from decimal import Decimal
from experiments.strategy_candidates.cross_asset_regime.longonly_rotation_candidate import LongOnlyVariant,longonly_signal
from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar
def test_longonly_selects_leader_and_never_emits_short():
    symbols=('SPY','QQQ','IWM','XLK','XLF','XLE','XLV','XLY');bars=[]
    for i in range(60):
        day=date(2024,1,1)+timedelta(days=i)
        for rank,s in enumerate(symbols):
            close=Decimal(100)+Decimal(i)*(Decimal('.3')+Decimal(rank)/20);bars.append(DailyBar(s,day,datetime(day.year,day.month,day.day,21,tzinfo=UTC),close,close+1,close-1,close,1000))
    signal=longonly_signal(LongOnlyVariant('x',6,Decimal('.75')),bars,bars[-1].session)
    assert signal is not None and signal.direction=='bullish' and signal.underlying=='XLY'
