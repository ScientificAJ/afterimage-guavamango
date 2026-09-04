from __future__ import annotations

from datetime import UTC,date,datetime,timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.credit_impulse_candidate import CreditImpulseVariant,credit_impulse_signal
from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar


def test_positive_credit_impulse_with_breadth_emits_qqq_long() -> None:
    symbols=('SPY','HYG','TLT','QQQ','IWM','XLK','XLF','XLE','XLV','XLY');bars=[]
    for i in range(30):
        day=date(2024,1,1)+timedelta(days=i)
        for symbol in symbols:
            slope=Decimal('.5') if symbol!='TLT' else Decimal('.1')
            close=Decimal(100)+slope*i
            bars.append(DailyBar(symbol,day,datetime(day.year,day.month,day.day,21,tzinfo=UTC),close,close+1,close-1,close,1000))
    signal=credit_impulse_signal(CreditImpulseVariant('x',Decimal('.0025'),Decimal('1')),bars,bars[-1].session,is_week_end=True)
    assert signal is not None and signal.underlying=='QQQ' and signal.direction=='bullish'
