from __future__ import annotations

from datetime import UTC,date,datetime,timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar
from experiments.strategy_candidates.cross_asset_regime.weekly_rotation_candidate import WeeklyRotationVariant,weekly_rotation_signal


def test_weekly_rotation_selects_long_term_leader() -> None:
    symbols=('SPY','QQQ','IWM','XLK','XLF','XLE','XLV','XLY');bars=[]
    for i in range(130):
        day=date(2023,1,1)+timedelta(days=i)
        for rank,s in enumerate(symbols):
            close=Decimal(100)+Decimal(i)*(Decimal('.3')+Decimal(rank)/20);bars.append(DailyBar(s,day,datetime(day.year,day.month,day.day,21,tzinfo=UTC),close,close+1,close-1,close,1000))
    signal=weekly_rotation_signal(WeeklyRotationVariant('x',60,Decimal('1.5')),bars,bars[-1].session,is_week_end=True)
    assert signal is not None and signal.underlying=='XLY' and signal.direction=='bullish'
