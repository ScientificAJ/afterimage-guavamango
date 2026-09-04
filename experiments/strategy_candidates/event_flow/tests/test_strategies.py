from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from experiments.strategy_candidates.event_flow.strategies import (
    CalendarShockVariant,
    DailyFeature,
    ShockVariant,
    VolumeBreakoutVariant,
    choose_calendar_shock_signal,
    choose_shock_signal,
    choose_volume_breakout_signal,
)


def _feature(symbol: str, shock: str, volume_ratio: str = "1") -> DailyFeature:
    return DailyFeature(
        session=date(2026, 1, 2),
        symbol=symbol,
        completed_at=datetime(2026, 1, 2, 21, tzinfo=UTC),
        trend=1,
        atr_fraction=Decimal("0.01"),
        two_day_atr_return=Decimal(shock),
        three_day_atr_return=Decimal(shock),
        close_location=Decimal("0.20"),
        consecutive_countertrend=True,
        compression_ratio=Decimal("0.7"),
        inside_day=False,
        volume_ratio=Decimal(volume_ratio),
        breakouts={5: True, 10: False, 20: False, 40: False},
    )


def test_shock_reversal_chooses_most_stretched_eligible_etf() -> None:
    variant = ShockVariant(
        name="shock",
        lookback_days=3,
        minimum_shock_atr=Decimal("0.75"),
        maximum_close_location=Decimal(1),
        require_sequence=False,
        long_only=True,
        stop_atr=Decimal("1.25"),
        hold_days=10,
    )

    signal = choose_shock_signal((_feature("XLK", "-0.8"), _feature("XLF", "-1.2")), variant)

    assert signal is not None
    assert signal.symbol == "XLF"
    assert signal.direction == 1


def test_volume_breakout_requires_both_completed_breakout_and_volume_expansion() -> None:
    variant = VolumeBreakoutVariant(
        name="breakout",
        lookback_days=5,
        minimum_volume_ratio=Decimal("1.5"),
        stop_atr=Decimal("0.75"),
        hold_days=20,
    )

    rejected = choose_volume_breakout_signal((_feature("XLK", "0.2", "1.4"),), variant)
    accepted = choose_volume_breakout_signal((_feature("XLK", "0.2", "1.6"),), variant)

    assert rejected is None
    assert accepted is not None
    assert accepted.symbol == "XLK"


def test_calendar_shock_only_allows_predeclared_signal_weekdays() -> None:
    variant = CalendarShockVariant(
        name="turnaround",
        lookback_days=2,
        minimum_shock_atr=Decimal("0.6"),
        maximum_close_location=Decimal("0.3"),
        stop_atr=Decimal(1),
        hold_days=5,
        allowed_weekdays=(0, 1, 2),
    )
    monday = _feature("XLK", "-1")
    monday = DailyFeature(**{**monday.__dict__, "session": date(2026, 1, 5)})
    thursday = DailyFeature(**{**monday.__dict__, "session": date(2026, 1, 8)})

    assert choose_calendar_shock_signal((monday,), variant) is not None
    assert choose_calendar_shock_signal((thursday,), variant) is None
