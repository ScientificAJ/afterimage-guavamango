from __future__ import annotations

from datetime import UTC,date,datetime,timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.multiday_rotation_candidate import DailyBar
from experiments.strategy_candidates.cross_asset_regime.pullback_candidate import PullbackVariant,pullback_signal


def test_risk_on_leader_pullback_emits_continuation_signal() -> None:
    symbols=("SPY","QQQ","IWM","XLK","XLF","XLE","XLV","XLY");bars=[]
    for i in range(60):
        day=date(2024,1,1)+timedelta(days=i)
        for rank,symbol in enumerate(symbols):
            close=Decimal(100)+Decimal(i)*(Decimal('0.4')+Decimal(rank)/20)
            if i==59 and symbol=='XLY':close-=Decimal(1)
            bars.append(DailyBar(symbol,day,datetime(day.year,day.month,day.day,21,tzinfo=UTC),close,close+1,close-1,close,1000))
    signal=pullback_signal(PullbackVariant('x',Decimal(0),Decimal('.50')),bars,bars[-1].session)
    assert signal is not None
    assert signal.direction=='bullish' and signal.underlying=='XLY'
