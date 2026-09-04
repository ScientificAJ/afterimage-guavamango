"""Attempt 002 pure overnight-gap breadth confirmation logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_CEILING, Decimal
from typing import Literal, Sequence

try:
    from .candidate import (
        CENT,
        ET,
        MULTIPLIER,
        Costs,
        DataExclusion,
        OptionFrame,
        StockBar,
        Trade,
        UNIVERSE,
    )
except ImportError:
    from candidate import (  # type: ignore[no-redef]
        CENT,
        ET,
        MULTIPLIER,
        Costs,
        DataExclusion,
        OptionFrame,
        StockBar,
        Trade,
        UNIVERSE,
    )


@dataclass(frozen=True)
class GapVariant:
    name: str
    breadth_required: int
    minimum_mean_gap: Decimal
    stop_fraction: Decimal
    hold_bars: int = 6
    exit_mode: str = "target_stop_3r"


GAP_VARIANTS = tuple(
    GapVariant(
        f"gap_b{breadth}_m{int(mean_gap * 10000):02d}_s{int(stop * 100):02d}",
        breadth,
        mean_gap,
        stop,
    )
    for breadth in (4, 5)
    for mean_gap in (Decimal("0.0010"), Decimal("0.0020"))
    for stop in (Decimal("0.15"), Decimal("0.20"), Decimal("0.25"))
)


@dataclass(frozen=True)
class GapSignal:
    session: date
    completed_at: datetime
    direction: Literal["bullish", "bearish"]
    underlying: Literal["QQQ", "IWM"]
    reference_price: Decimal
    breadth_count: int
    mean_gap: Decimal
    variant: str


def gap_signal(
    variant: GapVariant, bars: Sequence[StockBar], session: date
) -> GapSignal | None:
    current = {
        bar.symbol: bar
        for bar in bars
        if bar.symbol in UNIVERSE
        and bar.timestamp.astimezone(ET).date() == session
        and bar.timestamp.astimezone(ET).time() == time(9, 30)
    }
    if set(current) != set(UNIVERSE):
        raise DataExclusion("INCOMPLETE_FIRST_BAR_UNIVERSE")
    prior_sessions = sorted(
        {
            bar.timestamp.astimezone(ET).date()
            for bar in bars
            if bar.symbol in UNIVERSE and bar.timestamp.astimezone(ET).date() < session
        }
    )
    if not prior_sessions:
        raise DataExclusion("NO_PRIOR_REGULAR_SESSION")
    prior_session = prior_sessions[-1]
    prior: dict[str, StockBar] = {}
    for symbol in UNIVERSE:
        eligible = [
            bar
            for bar in bars
            if bar.symbol == symbol and bar.timestamp.astimezone(ET).date() == prior_session
        ]
        if not eligible:
            raise DataExclusion("INCOMPLETE_PRIOR_CLOSE_UNIVERSE")
        prior[symbol] = max(eligible, key=lambda item: item.timestamp)
    gaps = {symbol: current[symbol].open / prior[symbol].close - Decimal(1) for symbol in UNIVERSE}
    positive = sum(value > 0 for value in gaps.values())
    negative = sum(value < 0 for value in gaps.values())
    mean_gap = sum(gaps.values(), Decimal(0)) / Decimal(len(UNIVERSE))
    if positive >= variant.breadth_required and mean_gap >= variant.minimum_mean_gap:
        direction: Literal["bullish", "bearish"] = "bullish"
        directional = Decimal(1)
        breadth_count = positive
    elif negative >= variant.breadth_required and mean_gap <= -variant.minimum_mean_gap:
        direction = "bearish"
        directional = Decimal(-1)
        breadth_count = negative
    else:
        return None
    for symbol in ("QQQ", "IWM"):
        first_bar_return = current[symbol].close / current[symbol].open - Decimal(1)
        if first_bar_return * directional <= 0:
            return None
    underlying = sorted(
        ("QQQ", "IWM"), key=lambda symbol: (-(gaps[symbol] * directional), symbol)
    )[0]
    return GapSignal(
        session=session,
        completed_at=datetime.combine(session, time(9, 45), ET),
        direction=direction,
        underlying=underlying,  # type: ignore[arg-type]
        reference_price=current[underlying].close,
        breadth_count=breadth_count,
        mean_gap=mean_gap,
        variant=variant.name,
    )


def gap_target_stop_levels(
    entry_debit: Decimal, stop_fraction: Decimal, costs: Costs
) -> tuple[Decimal, Decimal, Decimal]:
    if entry_debit <= 0 or not Decimal(0) < stop_fraction < Decimal(1):
        raise ValueError("POSITIVE_DEBIT_AND_STOP_FRACTION_REQUIRED")
    fees = costs.fee_per_contract * Decimal(4)
    gross_loss_budget = entry_debit * MULTIPLIER * stop_fraction
    raw_stop = entry_debit + (-gross_loss_budget + fees) / MULTIPLIER
    stop_credit = max(Decimal(0), raw_stop.quantize(CENT, rounding=ROUND_CEILING))
    stop_net = (stop_credit - entry_debit) * MULTIPLIER - fees
    if stop_net >= 0:
        raise DataExclusion("STOP_NOT_BELOW_BREAKEVEN")
    raw_target = entry_debit + (abs(stop_net) * Decimal(3) + fees) / MULTIPLIER
    target_credit = raw_target.quantize(CENT, rounding=ROUND_CEILING)
    return stop_credit, target_credit, abs(stop_net)


def simulate_gap_trade(
    signal: GapSignal,
    frames: Sequence[OptionFrame],
    variant: GapVariant,
    costs: Costs = Costs(),
) -> Trade:
    ordered = tuple(
        sorted(
            (
                frame
                for frame in frames
                if frame.timestamp >= signal.completed_at
                and frame.timestamp.astimezone(ET).date() == signal.session
            ),
            key=lambda item: item.timestamp,
        )
    )
    if len(ordered) <= variant.hold_bars:
        raise DataExclusion("INSUFFICIENT_SYNCHRONIZED_OPTION_BARS")
    slippage = costs.slippage_per_leg * Decimal(2)
    entry = ordered[0]
    entry_debit = (entry.long.open - entry.short.open + slippage).quantize(CENT)
    if entry_debit <= 0 or entry_debit >= Decimal(5):
        raise DataExclusion("INVALID_NEXT_BAR_ENTRY_DEBIT")
    stop_credit, target_credit, risk_dollars = gap_target_stop_levels(
        entry_debit, variant.stop_fraction, costs
    )
    if target_credit >= Decimal(5) - slippage:
        raise DataExclusion("THREE_R_TARGET_EXCEEDS_VERTICAL_CAP")
    exit_frame = ordered[variant.hold_bars]
    exit_credit = max(
        Decimal(0), exit_frame.long.open - exit_frame.short.open - slippage
    ).quantize(CENT)
    outcome: Literal["target", "stop", "time"] = "time"
    for frame in ordered[1 : variant.hold_bars + 1]:
        credit = max(Decimal(0), frame.long.open - frame.short.open - slippage).quantize(CENT)
        if credit <= stop_credit:
            exit_frame = frame
            exit_credit = credit
            outcome = "stop"
            break
        if credit >= target_credit:
            exit_frame = frame
            exit_credit = target_credit
            outcome = "target"
            break
    fees = (costs.fee_per_contract * Decimal(4)).quantize(CENT)
    net_pnl = ((exit_credit - entry_debit) * MULTIPLIER - fees).quantize(CENT)
    return Trade(
        session=signal.session,
        variant=variant.name,
        direction=signal.direction,
        underlying=signal.underlying,
        long_symbol=entry.long.symbol,
        short_symbol=entry.short.symbol,
        entry_at=entry.timestamp,
        exit_at=exit_frame.timestamp,
        entry_debit=entry_debit,
        exit_credit=exit_credit,
        net_pnl=net_pnl,
        return_r=net_pnl / risk_dollars,
        modeled_fees=fees,
        modeled_slippage=(costs.slippage_per_leg * Decimal(4) * MULTIPLIER).quantize(CENT),
        outcome=outcome,
    )
