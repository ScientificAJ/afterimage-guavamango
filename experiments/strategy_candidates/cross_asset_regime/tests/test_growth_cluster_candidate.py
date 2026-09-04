from __future__ import annotations
from datetime import UTC,date,datetime,timedelta
from decimal import Decimal
from experiments.strategy_candidates.cross_asset_regime.growth_cluster_candidate import GrowthClusterVariant,growth_cluster_signal
from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar
def test_broad_state_does_not_select_non_cluster_leader():
    symbols=('SPY','QQQ','IWM','XLK','XLF','XLE','XLV','XLY');bars=[]
    for i in range(60):
        day=date(2024,1,1)+timedelta(days=i)
        for rank,s in enumerate(symbols):
            slope=Decimal('.2')+Decimal(rank)/30
            if s=='XLE':slope=Decimal('.8')
            c=Decimal(100)+Decimal(i)*slope;bars.append(DailyBar(s,day,datetime(day.year,day.month,day.day,21,tzinfo=UTC),c,c+1,c-1,c,1000))
    x=growth_cluster_signal(GrowthClusterVariant('x',6,Decimal('1.25')),bars,bars[-1].session);assert x is not None and x.underlying in {'QQQ','IWM','XLK','XLY'} and x.underlying!='XLE'
