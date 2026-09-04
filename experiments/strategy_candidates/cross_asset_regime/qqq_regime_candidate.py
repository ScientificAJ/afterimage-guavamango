"""Attempt 006: QQQ-only, regime-conditioned overnight-gap continuation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal, Sequence

try:
    from .candidate import DataExclusion, ET, StockBar, UNIVERSE
except ImportError:
    from candidate import DataExclusion, ET, StockBar, UNIVERSE  # type: ignore[no-redef]


SECTORS = ("XLK", "XLF", "XLE", "XLV", "XLY")


@dataclass(frozen=True)
class QQQRegimeVariant:
    name: str
    breadth_required: int
    minimum_mean_gap: Decimal
    sector_confirmations: int
    stop_fraction: Decimal = Decimal("0.0015")
    hold_bars: int = 6


FOCAL_VARIANT = QQQRegimeVariant(
    "qqq_regime_b5_m10_c4_s15", 5, Decimal("0.0010"), 4
)
VARIANTS = (
    FOCAL_VARIANT,
    QQQRegimeVariant("qqq_regime_b4_m10_c4_s15", 4, Decimal("0.0010"), 4),
    QQQRegimeVariant("qqq_regime_b5_m15_c4_s15", 5, Decimal("0.0015"), 4),
    QQQRegimeVariant("qqq_regime_b5_m10_c3_s15", 5, Decimal("0.0010"), 3),
)


@dataclass(frozen=True)
class QQQRegimeSignal:
    session: date
    completed_at: datetime
    direction: Literal["bullish", "bearish"]
    underlying: Literal["QQQ"]
    reference_price: Decimal
    variant: str
    regime: str
    gap_breadth: int
    sector_confirmations: int


def _lagged_spy_regime(
    spy_daily_closes: Sequence[tuple[date, Decimal]], session: date
) -> Literal["risk_on", "risk_off"]:
    eligible = [value for day, value in sorted(spy_daily_closes) if day < session]
    if len(eligible) < 20:
        raise DataExclusion("INSUFFICIENT_LAGGED_SPY_HISTORY")
    average = sum(eligible[-20:], Decimal(0)) / Decimal(20)
    return "risk_on" if eligible[-1] >= average else "risk_off"


def qqq_regime_signal(
    variant: QQQRegimeVariant,
    bars: Sequence[StockBar],
    spy_daily_closes: Sequence[tuple[date, Decimal]],
    session: date,
) -> QQQRegimeSignal | None:
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
    gaps = {
        symbol: current[symbol].open / prior[symbol].close - Decimal(1)
        for symbol in UNIVERSE
    }
    positive = sum(value > 0 for value in gaps.values())
    negative = sum(value < 0 for value in gaps.values())
    mean_gap = sum(gaps.values(), Decimal(0)) / Decimal(len(UNIVERSE))
    if positive >= variant.breadth_required and mean_gap >= variant.minimum_mean_gap:
        direction: Literal["bullish", "bearish"] = "bullish"
        directional = Decimal(1)
        gap_breadth = positive
    elif negative >= variant.breadth_required and mean_gap <= -variant.minimum_mean_gap:
        direction = "bearish"
        directional = Decimal(-1)
        gap_breadth = negative
    else:
        return None
    qqq_first_bar = current["QQQ"].close / current["QQQ"].open - Decimal(1)
    if qqq_first_bar * directional <= 0:
        return None
    confirming_sectors = sum(
        (current[symbol].close / current[symbol].open - Decimal(1)) * directional > 0
        for symbol in SECTORS
    )
    if confirming_sectors < variant.sector_confirmations:
        return None
    market = _lagged_spy_regime(spy_daily_closes, session)
    regime = f"{market}_{direction}"
    if regime == "risk_on_bullish":
        return None
    return QQQRegimeSignal(
        session=session,
        completed_at=datetime.combine(session, time(9, 45), ET),
        direction=direction,
        underlying="QQQ",
        reference_price=current["QQQ"].close,
        variant=variant.name,
        regime=regime,
        gap_breadth=gap_breadth,
        sector_confirmations=confirming_sectors,
    )
