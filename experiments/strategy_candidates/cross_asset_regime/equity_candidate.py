"""Attempt 004 liquid-ETF execution with an explicit net 3R/1R bracket."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal, Sequence

try:
    from .candidate import CENT, DataExclusion, ET, StockBar
except ImportError:
    from candidate import CENT, DataExclusion, ET, StockBar  # type: ignore[no-redef]


@dataclass(frozen=True)
class EquityCosts:
    slippage_fraction: Decimal = Decimal("0.0001")
    fee_per_share_per_side: Decimal = Decimal("0.005")


@dataclass(frozen=True)
class EquityVariant:
    name: str
    sector_breadth_required: int
    minimum_lag: Decimal
    stop_fraction: Decimal
    hold_bars: int = 6


EQUITY_VARIANTS = tuple(
    EquityVariant(
        f"equity_b{breadth}_g{int(lag * 10000):02d}_s{int(stop * 10000):02d}",
        breadth,
        lag,
        stop,
    )
    for breadth in (3, 4)
    for lag in (Decimal("0.0005"), Decimal("0.0010"))
    for stop in (Decimal("0.0015"), Decimal("0.0025"), Decimal("0.0035"))
)


@dataclass(frozen=True)
class EquitySignal:
    session: date
    completed_at: datetime
    direction: Literal["bullish", "bearish"]
    underlying: Literal["QQQ", "IWM"]
    reference_price: Decimal
    variant: str


@dataclass(frozen=True)
class EquityTrade:
    session: date
    variant: str
    direction: str
    underlying: str
    entry_at: datetime
    exit_at: datetime
    shares: int
    raw_entry: Decimal
    entry_fill: Decimal
    stop_price: Decimal
    target_price: Decimal
    exit_fill: Decimal
    net_pnl: Decimal
    return_r: Decimal
    outcome: Literal["target", "stop", "time"]
    modeled_fees: Decimal
    modeled_slippage: Decimal
    target_to_stop: Decimal


def _exit_fill(direction: str, raw_price: Decimal, costs: EquityCosts) -> Decimal:
    if direction == "bullish":
        return raw_price * (Decimal(1) - costs.slippage_fraction)
    return raw_price * (Decimal(1) + costs.slippage_fraction)


def bracket_levels(
    *,
    direction: Literal["bullish", "bearish"],
    raw_entry: Decimal,
    shares: int,
    stop_fraction: Decimal,
    costs: EquityCosts,
) -> tuple[Decimal, Decimal, Decimal]:
    if raw_entry <= 0 or shares <= 0 or not Decimal(0) < stop_fraction < Decimal(1):
        raise ValueError("VALID_ENTRY_SHARES_AND_STOP_REQUIRED")
    fees = costs.fee_per_share_per_side * Decimal(shares) * Decimal(2)
    if direction == "bullish":
        entry_fill = raw_entry * (Decimal(1) + costs.slippage_fraction)
        stop = (raw_entry * (Decimal(1) - stop_fraction)).quantize(CENT, rounding=ROUND_HALF_UP)
        stop_net = (_exit_fill(direction, stop, costs) - entry_fill) * shares - fees
        risk = abs(stop_net)
        raw_target = (entry_fill + (risk * Decimal(3) + fees) / shares) / (Decimal(1) - costs.slippage_fraction)
        target = raw_target.quantize(CENT, rounding=ROUND_CEILING)
        target_net = (_exit_fill(direction, target, costs) - entry_fill) * shares - fees
    elif direction == "bearish":
        entry_fill = raw_entry * (Decimal(1) - costs.slippage_fraction)
        stop = (raw_entry * (Decimal(1) + stop_fraction)).quantize(CENT, rounding=ROUND_HALF_UP)
        stop_net = (entry_fill - _exit_fill(direction, stop, costs)) * shares - fees
        risk = abs(stop_net)
        raw_target = (entry_fill - (risk * Decimal(3) + fees) / shares) / (Decimal(1) + costs.slippage_fraction)
        target = raw_target.quantize(CENT, rounding=ROUND_FLOOR)
        target_net = (entry_fill - _exit_fill(direction, target, costs)) * shares - fees
    else:
        raise ValueError("UNKNOWN_DIRECTION")
    if stop_net >= 0 or target_net / risk < Decimal(3):
        raise DataExclusion("NET_THREE_TO_ONE_BRACKET_NOT_ACHIEVED")
    return stop, target, risk


def simulate_equity_trade(
    signal: EquitySignal,
    bars: Sequence[StockBar],
    variant: EquityVariant,
    costs: EquityCosts = EquityCosts(),
    *,
    notional: Decimal = Decimal("10000"),
) -> EquityTrade:
    ordered = tuple(
        sorted(
            (
                bar for bar in bars
                if bar.symbol == signal.underlying
                and bar.timestamp >= signal.completed_at
                and bar.timestamp.astimezone(ET).date() == signal.session
            ),
            key=lambda item: item.timestamp,
        )
    )
    if len(ordered) <= variant.hold_bars:
        raise DataExclusion("INSUFFICIENT_UNDERLYING_EXIT_BARS")
    entry = ordered[0]
    entry_fill = entry.open * (
        Decimal(1) + costs.slippage_fraction
        if signal.direction == "bullish"
        else Decimal(1) - costs.slippage_fraction
    )
    shares = int(notional // entry_fill)
    if shares < 1:
        raise DataExclusion("NOTIONAL_TOO_SMALL")
    stop, target, risk = bracket_levels(
        direction=signal.direction,
        raw_entry=entry.open,
        shares=shares,
        stop_fraction=variant.stop_fraction,
        costs=costs,
    )
    selected = ordered[variant.hold_bars]
    raw_exit = selected.close
    outcome: Literal["target", "stop", "time"] = "time"
    for bar in ordered[1 : variant.hold_bars + 1]:
        if signal.direction == "bullish":
            if bar.low <= stop:
                selected, raw_exit, outcome = bar, stop, "stop"
                break
            if bar.high >= target:
                selected, raw_exit, outcome = bar, target, "target"
                break
        else:
            if bar.high >= stop:
                selected, raw_exit, outcome = bar, stop, "stop"
                break
            if bar.low <= target:
                selected, raw_exit, outcome = bar, target, "target"
                break
    exit_fill = _exit_fill(signal.direction, raw_exit, costs)
    fees = (costs.fee_per_share_per_side * Decimal(shares) * Decimal(2)).quantize(CENT)
    if signal.direction == "bullish":
        gross = (exit_fill - entry_fill) * shares
    else:
        gross = (entry_fill - exit_fill) * shares
    net_pnl = (gross - fees).quantize(CENT)
    stop_exit = _exit_fill(signal.direction, stop, costs)
    target_exit = _exit_fill(signal.direction, target, costs)
    if signal.direction == "bullish":
        stop_net = (stop_exit - entry_fill) * shares - fees
        target_net = (target_exit - entry_fill) * shares - fees
    else:
        stop_net = (entry_fill - stop_exit) * shares - fees
        target_net = (entry_fill - target_exit) * shares - fees
    modeled_slippage = (entry.open * costs.slippage_fraction * shares + raw_exit * costs.slippage_fraction * shares).quantize(CENT)
    return EquityTrade(
        session=signal.session,
        variant=variant.name,
        direction=signal.direction,
        underlying=signal.underlying,
        entry_at=entry.timestamp,
        exit_at=selected.timestamp,
        shares=shares,
        raw_entry=entry.open,
        entry_fill=entry_fill,
        stop_price=stop,
        target_price=target,
        exit_fill=exit_fill,
        net_pnl=net_pnl,
        return_r=net_pnl / risk,
        outcome=outcome,
        modeled_fees=fees,
        modeled_slippage=modeled_slippage,
        target_to_stop=target_net / abs(stop_net),
    )
