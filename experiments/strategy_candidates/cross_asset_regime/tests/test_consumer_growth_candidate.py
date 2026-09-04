from __future__ import annotations
from datetime import UTC,date,datetime,timedelta
from decimal import Decimal
from experiments.strategy_candidates.cross_asset_regime.consumer_growth_candidate import ConsumerGrowthVariant,consumer_growth_signal
from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar
def test_nonexecution_sector_can_define_state_but_not_selection():
    symbols=('SPY','QQQ','IWM','XLK','XLF','XLE','XLV','XLY');bars=[]
    for i in range(60):
        day=date(2024,1,1)+timedelta(days=i)
        for rank,s in enumerate(symbols):
            slope=Decimal('.2')+Decimal(rank)/40
            if s=='XLK':slope=Decimal('.8')
            c=Decimal(100)+Decimal(i)*slope;bars.append(DailyBar(s,day,datetime(day.year,day.month,day.day,21,tzinfo=UTC),c,c+1,c-1,c,1000))
    x=consumer_growth_signal(ConsumerGrowthVariant('x',6,Decimal('1.25')),bars,bars[-1].session);assert x is not None and x.underlying in {'QQQ','IWM','XLY'}
