from __future__ import annotations
from datetime import UTC,date,datetime,timedelta
from decimal import Decimal
from experiments.strategy_candidates.cross_asset_regime.lowvol_rotation_candidate import LowVolVariant,lowvol_signal
from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar
def test_low_noise_breadth_emits_long():
    symbols=('SPY','QQQ','IWM','XLK','XLF','XLE','XLV','XLY');bars=[]
    for i in range(60):
        day=date(2024,1,1)+timedelta(days=i)
        for rank,s in enumerate(symbols):
            c=Decimal(100)+Decimal(i)*(Decimal('.2')+Decimal(rank)/40);bars.append(DailyBar(s,day,datetime(day.year,day.month,day.day,21,tzinfo=UTC),c,c+Decimal('.3'),c-Decimal('.3'),c,1000))
    x=lowvol_signal(LowVolVariant('x',Decimal('.012'),Decimal('1')),bars,bars[-1].session);assert x is not None and x.direction=='bullish'
