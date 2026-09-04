from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from experiments.strategy_candidates.mean_reversion.candidate import (
    Bar,
    Costs,
    OptionPairBar,
    Parameters,
    build_dry_run_order,
    conservative_round_trip,
    detect_signals,
    make_walk_forward_folds,
    summarize,
)


def bar(minute: int, *, opn: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        timestamp=datetime(2025, 1, 2, 14, minute, tzinfo=UTC),
        open=opn,
        high=high,
        low=low,
        close=close,
        volume=1_000,
    )


def test_signal_filter_applies_before_one_signal_per_session_lockout() -> None:
    params = Parameters(
        lookback=3,
        z_threshold=Decimal("2"),
        min_wick_fraction=Decimal("0.6"),
        earliest_signal_minute_from_open=30,
    )
    rows = [
        bar(30, opn=100, high=100.2, low=99.8, close=100),
        bar(35, opn=100, high=100.3, low=99.9, close=100.2),
        bar(40, opn=100.2, high=100.2, low=99.7, close=99.8),
        bar(45, opn=99.8, high=100.0, low=98.0, close=99.8),
        bar(50, opn=100, high=100.2, low=99.8, close=100),
        bar(55, opn=100, high=100.3, low=99.9, close=100.2),
        Bar(datetime(2025, 1, 2, 15, 0, tzinfo=UTC), 100.2, 100.2, 99.7, 99.8, 1_000),
        Bar(datetime(2025, 1, 2, 15, 5, tzinfo=UTC), 99.8, 100.0, 98.0, 99.8, 1_000),
    ]

    signals = detect_signals(rows, params)

    assert len(signals) == 1
    assert signals[0].signal_bar_start == datetime(2025, 1, 2, 15, 5, tzinfo=UTC)


def test_failed_low_auction_uses_only_completed_bars() -> None:
    params = Parameters(lookback=3, z_threshold=Decimal("2"), min_wick_fraction=Decimal("0.6"))
    completed = [
        bar(30, opn=100, high=100.2, low=99.8, close=100),
        bar(35, opn=100, high=100.3, low=99.9, close=100.2),
        bar(40, opn=100.2, high=100.2, low=99.7, close=99.8),
        bar(45, opn=99.8, high=100.0, low=98.0, close=99.8),
    ]

    original = detect_signals(completed, params)
    with_future = detect_signals(
        [*completed, bar(50, opn=99.8, high=120, low=90, close=110)], params
    )

    assert len(original) == 1
    assert original[0].direction == "bullish"
    assert original[0].signal_bar_start == datetime(2025, 1, 2, 14, 45, tzinfo=UTC)
    assert original[0].completed_at == datetime(2025, 1, 2, 14, 50, tzinfo=UTC)
    assert with_future[0] == original[0]


def test_failed_auction_can_require_reversal_body_volume_and_mean_reclaim() -> None:
    params = Parameters(
        lookback=3,
        z_threshold=Decimal("2"),
        min_wick_fraction=Decimal("0.6"),
        require_directional_body=True,
        min_volume_ratio=Decimal("1.5"),
        max_close_distance_z=Decimal("1"),
    )
    history = [
        bar(30, opn=100, high=100.2, low=99.8, close=100),
        bar(35, opn=100, high=100.3, low=99.9, close=100.2),
        bar(40, opn=100.2, high=100.2, low=99.7, close=99.8),
    ]
    valid = Bar(datetime(2025, 1, 2, 14, 45, tzinfo=UTC), 99.7, 100, 98, 99.9, 2_000)
    low_volume = valid.__class__(**{**valid.__dict__, "volume": 1_000})
    wrong_body = valid.__class__(**{**valid.__dict__, "open": 99.95})

    assert len(detect_signals([*history, valid], params)) == 1
    assert detect_signals([*history, low_volume], params) == ()
    assert detect_signals([*history, wrong_body], params) == ()


def test_walk_forward_folds_are_chronological_and_embargoed() -> None:
    sessions = tuple(date(2025, 1, day) for day in range(2, 12))

    folds = make_walk_forward_folds(sessions, min_train=4, test_size=2, embargo=1)

    assert folds[0].train == sessions[:4]
    assert folds[0].embargo == (sessions[4],)
    assert folds[0].test == sessions[5:7]
    assert folds[1].train == sessions[:7]
    assert folds[1].embargo == (sessions[7],)
    assert folds[1].test == sessions[8:10]
    assert all(max(fold.train) < min(fold.test) for fold in folds)


def test_conservative_option_round_trip_enters_on_next_bar_and_charges_costs() -> None:
    completed_at = datetime(2025, 1, 2, 14, 50, tzinfo=UTC)
    rows = (
        OptionPairBar(
            timestamp=completed_at - timedelta(minutes=5),
            long_open=Decimal("1.80"),
            long_high=Decimal("1.90"),
            long_low=Decimal("1.70"),
            long_close=Decimal("1.85"),
            short_open=Decimal("0.50"),
            short_high=Decimal("0.55"),
            short_low=Decimal("0.45"),
            short_close=Decimal("0.50"),
        ),
        OptionPairBar(
            timestamp=completed_at,
            long_open=Decimal("1.90"),
            long_high=Decimal("2.00"),
            long_low=Decimal("1.85"),
            long_close=Decimal("1.95"),
            short_open=Decimal("0.45"),
            short_high=Decimal("0.50"),
            short_low=Decimal("0.40"),
            short_close=Decimal("0.45"),
        ),
        OptionPairBar(
            timestamp=completed_at + timedelta(minutes=5),
            long_open=Decimal("2.45"),
            long_high=Decimal("2.60"),
            long_low=Decimal("2.40"),
            long_close=Decimal("2.50"),
            short_open=Decimal("0.55"),
            short_high=Decimal("0.60"),
            short_low=Decimal("0.50"),
            short_close=Decimal("0.55"),
        ),
    )

    trade = conservative_round_trip(
        completed_at,
        rows,
        Costs(slippage_per_leg=Decimal("0.02"), fee_per_contract=Decimal("0.65")),
        max_holding_bars=1,
    )

    assert trade.entry_at == completed_at
    assert trade.exit_at == completed_at + timedelta(minutes=5)
    assert trade.entry_debit == Decimal("1.64")
    assert trade.exit_credit == Decimal("1.76")
    assert trade.total_fees == Decimal("2.60")
    assert trade.net_pnl == Decimal("9.40")


def test_next_bar_close_fill_waits_for_bar_completion_and_applies_slippage() -> None:
    completed_at = datetime(2025, 1, 2, 14, 50, tzinfo=UTC)
    rows = (
        OptionPairBar(
            completed_at,
            Decimal("1.90"), Decimal("2.00"), Decimal("1.85"), Decimal("1.95"),
            Decimal("0.45"), Decimal("0.50"), Decimal("0.40"), Decimal("0.45"),
        ),
        OptionPairBar(
            completed_at + timedelta(minutes=5),
            Decimal("2.45"), Decimal("2.60"), Decimal("2.40"), Decimal("2.50"),
            Decimal("0.55"), Decimal("0.60"), Decimal("0.50"), Decimal("0.55"),
        ),
    )

    trade = conservative_round_trip(
        completed_at,
        rows,
        Costs(slippage_per_leg=Decimal("0.02"), fee_per_contract=Decimal("0.65")),
        max_holding_bars=1,
        fill_model="next_bar_close",
    )

    assert trade.entry_at == completed_at + timedelta(minutes=5)
    assert trade.exit_at == completed_at + timedelta(minutes=10)
    assert trade.entry_debit == Decimal("1.54")
    assert trade.exit_credit == Decimal("1.91")
    assert trade.net_pnl == Decimal("34.40")


def test_summary_reports_hand_checked_expectancy_hit_rate_and_drawdown() -> None:
    result = summarize(
        pnl_dollars=(Decimal("100"), Decimal("-50"), Decimal("50")),
        returns_r=(Decimal("1"), Decimal("-0.5"), Decimal("0.5")),
    )

    assert result.sample_size == 3
    assert result.net_pnl == Decimal("100")
    assert result.expectancy_r == pytest.approx(Decimal("0.3333333333"))
    assert result.hit_rate == pytest.approx(Decimal("0.6666666667"))
    assert result.max_drawdown == Decimal("50")


def test_dry_run_order_is_an_exact_two_leg_debit_vertical_and_never_submits() -> None:
    artifact = build_dry_run_order(
        direction="bullish",
        long_symbol="SPY250107C00590000",
        short_symbol="SPY250107C00595000",
        limit_price=Decimal("1.23"),
        client_order_id="mean-reversion-oos-example",
    )

    assert artifact["submission_allowed"] is False
    assert artifact["cli_arguments"][-1] == "--dry-run"
    assert artifact["payload"] == {
        "qty": "1",
        "type": "limit",
        "limit_price": "1.23",
        "time_in_force": "day",
        "order_class": "mleg",
        "client_order_id": "mean-reversion-oos-example",
        "legs": [
            {
                "symbol": "SPY250107C00590000",
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": "SPY250107C00595000",
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ],
    }
