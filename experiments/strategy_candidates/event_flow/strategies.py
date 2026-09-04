"""Causal features and signal rules for the event/flow search."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .engine import Signal


@dataclass(frozen=True)
class DailyFeature:
    session: date
    symbol: str
    completed_at: datetime
    trend: int
    atr_fraction: Decimal
    two_day_atr_return: Decimal
    three_day_atr_return: Decimal
    close_location: Decimal
    consecutive_countertrend: bool
    compression_ratio: Decimal
    inside_day: bool
    volume_ratio: Decimal
    breakouts: Mapping[int, bool]


@dataclass(frozen=True)
class ShockVariant:
    name: str
    lookback_days: int
    minimum_shock_atr: Decimal
    maximum_close_location: Decimal
    require_sequence: bool
    long_only: bool
    stop_atr: Decimal
    hold_days: int


@dataclass(frozen=True)
class CalendarShockVariant:
    name: str
    lookback_days: int
    minimum_shock_atr: Decimal
    maximum_close_location: Decimal
    stop_atr: Decimal
    hold_days: int
    allowed_weekdays: tuple[int, ...] = (0, 1, 2)


@dataclass(frozen=True)
class VolumeBreakoutVariant:
    name: str
    lookback_days: int
    minimum_volume_ratio: Decimal
    stop_atr: Decimal
    hold_days: int


@dataclass(frozen=True)
class CompressionVariant:
    name: str
    maximum_range_atr: Decimal
    minimum_close_location: Decimal
    require_inside_day: bool
    stop_atr: Decimal
    hold_days: int


def choose_shock_signal(features: Sequence[DailyFeature], variant: ShockVariant) -> Signal | None:
    eligible: list[tuple[Decimal, DailyFeature]] = []
    for item in features:
        if item.trend not in (-1, 1) or (variant.long_only and item.trend != 1):
            continue
        shock = item.two_day_atr_return if variant.lookback_days == 2 else item.three_day_atr_return
        countertrend = -Decimal(item.trend) * shock
        location_ok = (
            item.close_location <= variant.maximum_close_location
            if item.trend == 1
            else item.close_location >= Decimal(1) - variant.maximum_close_location
        )
        if (
            countertrend >= variant.minimum_shock_atr
            and location_ok
            and (not variant.require_sequence or item.consecutive_countertrend)
        ):
            eligible.append((countertrend, item))
    if not eligible:
        return None
    _, selected = max(eligible, key=lambda pair: (pair[0], pair[1].symbol))
    return Signal(
        symbol=selected.symbol,
        completed_at=selected.completed_at,
        direction=selected.trend,  # type: ignore[arg-type]
        family="trend-aligned shock reversal",
        variant=variant.name,
    )


def choose_calendar_shock_signal(
    features: Sequence[DailyFeature], variant: CalendarShockVariant
) -> Signal | None:
    if not features or features[0].session.weekday() not in variant.allowed_weekdays:
        return None
    base = ShockVariant(
        name=variant.name,
        lookback_days=variant.lookback_days,
        minimum_shock_atr=variant.minimum_shock_atr,
        maximum_close_location=variant.maximum_close_location,
        require_sequence=False,
        long_only=True,
        stop_atr=variant.stop_atr,
        hold_days=variant.hold_days,
    )
    return choose_shock_signal(features, base)


def choose_volume_breakout_signal(
    features: Sequence[DailyFeature], variant: VolumeBreakoutVariant
) -> Signal | None:
    eligible = [
        item
        for item in features
        if item.trend in (-1, 1)
        and item.volume_ratio >= variant.minimum_volume_ratio
        and item.breakouts.get(variant.lookback_days, False)
    ]
    if not eligible:
        return None
    selected = max(
        eligible,
        key=lambda item: (item.volume_ratio * abs(item.three_day_atr_return), item.symbol),
    )
    return Signal(
        symbol=selected.symbol,
        completed_at=selected.completed_at,
        direction=selected.trend,  # type: ignore[arg-type]
        family="volume-confirmed range breakout",
        variant=variant.name,
    )


def choose_compression_signal(
    features: Sequence[DailyFeature], variant: CompressionVariant
) -> Signal | None:
    eligible = [
        item
        for item in features
        if item.trend in (-1, 1)
        and item.compression_ratio <= variant.maximum_range_atr
        and (
            item.close_location >= variant.minimum_close_location
            if item.trend == 1
            else item.close_location <= Decimal(1) - variant.minimum_close_location
        )
        and (not variant.require_inside_day or item.inside_day)
    ]
    if not eligible:
        return None
    selected = min(eligible, key=lambda item: (item.compression_ratio, item.symbol))
    return Signal(
        symbol=selected.symbol,
        completed_at=selected.completed_at,
        direction=selected.trend,  # type: ignore[arg-type]
        family="trend compression release",
        variant=variant.name,
    )
