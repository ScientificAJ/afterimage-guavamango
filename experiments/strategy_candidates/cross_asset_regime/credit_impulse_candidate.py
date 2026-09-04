"""Weekly HYG/TLT risk impulse with broad equity confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal, Sequence

try:
    from .candidate import DataExclusion
    from .multiday_rotation_candidate import DailyBar, RotationSignal, TRADE_UNIVERSE, _atr
except ImportError:
    from candidate import DataExclusion  # type: ignore[no-redef]
    from multiday_rotation_candidate import DailyBar, RotationSignal, TRADE_UNIVERSE, _atr  # type: ignore[no-redef]


@dataclass(frozen=True)
class CreditImpulseVariant:
    name: str
    ratio_threshold: Decimal
    atr_multiplier: Decimal
    hold_sessions: int = 5


VARIANTS=(
    CreditImpulseVariant('cd_t25_a75_h05',Decimal('.0025'),Decimal('.75')),
    CreditImpulseVariant('cd_t25_a100_h05',Decimal('.0025'),Decimal('1')),
    CreditImpulseVariant('cd_t50_a75_h05',Decimal('.0050'),Decimal('.75')),
    CreditImpulseVariant('cd_t50_a100_h05',Decimal('.0050'),Decimal('1')),
)


def _series(bars:Sequence[DailyBar],symbol:str,session:date)->list[DailyBar]:
    return sorted((b for b in bars if b.symbol==symbol and b.session<=session),key=lambda b:b.session)


def credit_impulse_signal(variant:CreditImpulseVariant,bars:Sequence[DailyBar],session:date,*,is_week_end:bool)->RotationSignal|None:
    if not is_week_end:return None
    symbols=('SPY','HYG','TLT',*TRADE_UNIVERSE);h={s:_series(bars,s,session) for s in symbols}
    if any(len(rows)<22 or rows[-1].session!=session for rows in h.values()):raise DataExclusion('INCOMPLETE_DAILY_HISTORY')
    ratio_now=h['HYG'][-1].close/h['TLT'][-1].close;ratio_prior=h['HYG'][-6].close/h['TLT'][-6].close;impulse=ratio_now/ratio_prior-Decimal(1)
    returns={s:h[s][-1].close/h[s][-21].close-Decimal(1) for s in TRADE_UNIVERSE};spy_return=h['SPY'][-1].close/h['SPY'][-21].close-Decimal(1)
    if impulse>=variant.ratio_threshold and spy_return>0 and sum(x>0 for x in returns.values())>=4:
        direction:Literal['bullish','bearish']='bullish';regime:Literal['risk_on','risk_off']='risk_on';underlying='QQQ'
    elif impulse<=-variant.ratio_threshold and spy_return<0 and sum(x<0 for x in returns.values())>=4:
        direction='bearish';regime='risk_off';underlying='IWM'
    else:return None
    return RotationSignal(session,direction,underlying,_atr(h[underlying]),variant.name,regime,abs(impulse))
