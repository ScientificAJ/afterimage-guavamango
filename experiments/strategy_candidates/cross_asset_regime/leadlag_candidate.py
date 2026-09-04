"""Attempt 003 pure sector-to-index lead-lag catch-up signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Sequence

try:
    from .candidate import DataExclusion, ET, StockBar
except ImportError:
    from candidate import DataExclusion, ET, StockBar  # type: ignore[no-redef]


SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLY")
INDEXES = ("QQQ", "IWM")


@dataclass(frozen=True)
class LeadLagVariant:
    name: str
    sector_breadth_required: int
    minimum_lag: Decimal
    stop_fraction: Decimal
    minimum_sector_move: Decimal = Decimal("0.0010")
    hold_bars: int = 6
    exit_mode: str = "target_stop_3r"


LEADLAG_VARIANTS = tuple(
    LeadLagVariant(
        f"leadlag_b{breadth}_g{int(lag * 10000):02d}_s{int(stop * 100):02d}",
        breadth,
        lag,
        stop,
    )
    for breadth in (3, 4)
    for lag in (Decimal("0.0005"), Decimal("0.0010"))
    for stop in (Decimal("0.15"), Decimal("0.20"), Decimal("0.25"))
)


@dataclass(frozen=True)
class LeadLagSignal:
    session: date
    completed_at: datetime
    direction: Literal["bullish", "bearish"]
    underlying: Literal["QQQ", "IWM"]
    reference_price: Decimal
    sector_breadth: int
    sector_mean_return: Decimal
    lag: Decimal
    variant: str


def leadlag_signal_at(
    variant: LeadLagVariant,
    bars: Sequence[StockBar],
    session: date,
    signal_bar_start: datetime,
) -> LeadLagSignal | None:
    if signal_bar_start.tzinfo is None:
        raise ValueError("TIMEZONE_AWARE_SIGNAL_BAR_REQUIRED")
    first_start = signal_bar_start - timedelta(minutes=120)
    first: dict[str, StockBar] = {}
    last: dict[str, StockBar] = {}
    required = set((*SECTORS, *INDEXES))
    for bar in bars:
        if bar.symbol not in required or bar.timestamp.astimezone(ET).date() != session:
            continue
        if bar.timestamp == first_start:
            first[bar.symbol] = bar
        elif bar.timestamp == signal_bar_start:
            last[bar.symbol] = bar
    if set(first) != required or set(last) != required:
        raise DataExclusion("INCOMPLETE_LEADLAG_STOCK_WINDOW")
    returns = {symbol: last[symbol].close / first[symbol].open - Decimal(1) for symbol in required}
    positive = sum(returns[symbol] > 0 for symbol in SECTORS)
    negative = sum(returns[symbol] < 0 for symbol in SECTORS)
    sector_mean = sum((returns[symbol] for symbol in SECTORS), Decimal(0)) / Decimal(len(SECTORS))
    if positive >= variant.sector_breadth_required and sector_mean >= variant.minimum_sector_move:
        direction: Literal["bullish", "bearish"] = "bullish"
        sign = Decimal(1)
        breadth = positive
    elif negative >= variant.sector_breadth_required and sector_mean <= -variant.minimum_sector_move:
        direction = "bearish"
        sign = Decimal(-1)
        breadth = negative
    else:
        return None
    eligible = [
        symbol
        for symbol in INDEXES
        if returns[symbol] * sign > 0
        and sector_mean * sign - returns[symbol] * sign >= variant.minimum_lag
    ]
    if not eligible:
        return None
    underlying = sorted(eligible, key=lambda symbol: (returns[symbol] * sign, symbol))[0]
    return LeadLagSignal(
        session=session,
        completed_at=signal_bar_start + timedelta(minutes=15),
        direction=direction,
        underlying=underlying,  # type: ignore[arg-type]
        reference_price=last[underlying].close,
        sector_breadth=breadth,
        sector_mean_return=sector_mean,
        lag=sector_mean * sign - returns[underlying] * sign,
        variant=variant.name,
    )
