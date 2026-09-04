"""Causal, volume-screened option trade-VWAP execution sensitivity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

from candidate import LEG_SIDE_FEE, MULTIPLIER, DataExclusion
from pivots import MomentumFamily, PivotTrade

VWAP_SLIPPAGE = Decimal("0.02")
CENT = Decimal("0.01")
MINIMUM_VOLUME = 10
MINIMUM_TRADES = 5


@dataclass(frozen=True)
class VwapOptionBar:
    symbol: str
    timestamp: datetime
    close: Decimal
    vwap: Decimal
    volume: int
    trade_count: int

    def __post_init__(self) -> None:
        if not self.symbol or self.close <= 0 or self.vwap <= 0:
            raise DataExclusion("VWAP_BAR_INVALID")
        if not self.close.is_finite() or not self.vwap.is_finite():
            raise DataExclusion("VWAP_BAR_NONFINITE")
        if self.volume < 0 or self.trade_count < 0:
            raise DataExclusion("VWAP_BAR_NEGATIVE_ACTIVITY")

    @property
    def liquid(self) -> bool:
        return self.volume >= MINIMUM_VOLUME and self.trade_count >= MINIMUM_TRADES


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def simulate_causal_vwap_long(
    *,
    session_date: str,
    symbol: str,
    family: MomentumFamily,
    direction: Literal["bullish", "bearish"],
    bars: tuple[VwapOptionBar, ...],
) -> PivotTrade:
    if len(bars) < 2:
        raise DataExclusion("FEWER_THAN_TWO_VWAP_BARS")
    ordered = tuple(sorted(bars, key=lambda item: item.timestamp))
    if len({item.symbol for item in ordered}) != 1:
        raise DataExclusion("VWAP_OPTION_SYMBOL_MISMATCH")
    if not ordered[0].liquid:
        raise DataExclusion("VWAP_ENTRY_LIQUIDITY_FILTER_FALSE")
    entry_debit = _money(ordered[0].vwap + VWAP_SLIPPAGE)
    fees = LEG_SIDE_FEE * 2
    maximum_loss = _money(entry_debit * MULTIPLIER + fees)
    stop_risk = maximum_loss * family.stop_fraction_of_debit
    target = stop_risk * family.operational_target_stop
    liquid_exit_indices = [index for index in range(1, len(ordered)) if ordered[index].liquid]
    if not liquid_exit_indices:
        raise DataExclusion("NO_LIQUID_VWAP_EXIT_BAR")
    selected_index = liquid_exit_indices[-1]
    outcome: Literal["target", "stop", "time"] = "time"
    for index in liquid_exit_indices:
        if index >= len(ordered) - 1:
            break
        mark_credit = _money(max(ordered[index].close - VWAP_SLIPPAGE, Decimal(0)))
        mark_net = _money((mark_credit - entry_debit) * MULTIPLIER - fees)
        if mark_net >= target or mark_net <= -stop_risk:
            later_liquid = [item for item in liquid_exit_indices if item > index]
            if not later_liquid:
                break
            selected_index = later_liquid[0]
            outcome = "target" if mark_net >= target else "stop"
            break
    selected = ordered[selected_index]
    exit_credit = _money(max(selected.vwap - VWAP_SLIPPAGE, Decimal(0)))
    net_pnl = _money((exit_credit - entry_debit) * MULTIPLIER - fees)
    return PivotTrade(
        session_date=session_date,
        symbol=symbol,
        strategy="causal_vwap_long_reversal",
        family=family.name,
        direction=direction,
        entry_at=ordered[0].timestamp,
        exit_at=selected.timestamp,
        entry_value=entry_debit,
        exit_value=exit_credit,
        net_pnl=net_pnl,
        max_loss=maximum_loss,
        return_r=net_pnl / maximum_loss,
        outcome=outcome,
        stop_risk_dollars=stop_risk,
        target_dollars=target,
        operational_target_stop=target / stop_risk,
        modeled_fees=fees,
        modeled_slippage=VWAP_SLIPPAGE * 2 * MULTIPLIER,
        synchronized_frames=len(ordered),
        leg_symbols=(ordered[0].symbol,),
    )
