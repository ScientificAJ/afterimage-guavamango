from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from experiments.strategy_candidates.mean_reversion.candidate import Fold, Signal
from experiments.strategy_candidates.mean_reversion.research import (
    ScoredTrade,
    contract_pair,
    pair_option_bars,
    select_variant,
)


def test_contract_pair_uses_three_or_more_dte_and_directional_debit_vertical() -> None:
    bullish = Signal(
        direction="bullish",
        signal_bar_start=datetime(2025, 1, 2, 15, 0, tzinfo=UTC),
        completed_at=datetime(2025, 1, 2, 15, 5, tzinfo=UTC),
        reference_price=Decimal("588.40"),
        z_score=Decimal("-2.5"),
    )
    bearish = bullish.__class__(**{**bullish.__dict__, "direction": "bearish"})

    assert contract_pair(bullish) == (
        "SPY250106C00588000",
        "SPY250106C00593000",
    )
    assert contract_pair(bearish) == (
        "SPY250106P00588000",
        "SPY250106P00583000",
    )
    assert contract_pair(bullish, minimum_dte=7) == (
        "SPY250109C00588000",
        "SPY250109C00593000",
    )


def test_option_bars_are_paired_only_when_both_legs_traded() -> None:
    payload = {
        "bars": {
            "LONG": [
                {"t": "2025-01-02T15:05:00Z", "o": 2, "h": 2.2, "l": 1.9, "c": 2.1},
                {"t": "2025-01-02T15:10:00Z", "o": 2.1, "h": 2.3, "l": 2, "c": 2.2},
            ],
            "SHORT": [
                {"t": "2025-01-02T15:10:00Z", "o": 0.5, "h": 0.6, "l": 0.4, "c": 0.5}
            ],
        }
    }

    paired = pair_option_bars(payload, "LONG", "SHORT")

    assert len(paired) == 1
    assert paired[0].timestamp == datetime(2025, 1, 2, 15, 10, tzinfo=UTC)
    assert paired[0].long_high == Decimal("2.3")
    assert paired[0].short_low == Decimal("0.4")


def test_variant_selection_uses_training_dates_only() -> None:
    fold = Fold(
        train=(date(2025, 1, 2), date(2025, 1, 3)),
        embargo=(date(2025, 1, 6),),
        test=(date(2025, 1, 7),),
    )
    trades = {
        "stable": (
            ScoredTrade(date(2025, 1, 2), Decimal("0.3"), Decimal("30")),
            ScoredTrade(date(2025, 1, 3), Decimal("0.2"), Decimal("20")),
            ScoredTrade(date(2025, 1, 7), Decimal("-10"), Decimal("-1000")),
        ),
        "future_winner": (
            ScoredTrade(date(2025, 1, 2), Decimal("-0.1"), Decimal("-10")),
            ScoredTrade(date(2025, 1, 3), Decimal("0"), Decimal("0")),
            ScoredTrade(date(2025, 1, 7), Decimal("10"), Decimal("1000")),
        ),
    }

    assert select_variant(trades, fold.train, minimum_samples=2) == "stable"
