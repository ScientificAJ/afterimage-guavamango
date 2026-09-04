from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.mean_reversion.candidate import Bar, Costs, OptionPairBar
from experiments.strategy_candidates.mean_reversion.trend_confirmation import (
    TrendParameters,
    bracket_round_trip,
    detect_cross_index_trend,
    detect_cross_index_underlying_trend,
    make_rolling_folds,
    performance,
)
from experiments.strategy_candidates.mean_reversion.run_cross_index_trend import (
    stock_page_rows,
)


def _index_bars(symbol: str) -> tuple[Bar, ...]:
    scale = {"SPY": 1.0, "QQQ": 0.8, "IWM": 0.4}[symbol]
    start = datetime(2025, 5, 1, 13, 30, tzinfo=UTC)
    return tuple(
        Bar(
            timestamp=start + timedelta(minutes=5 * index),
            open=100 + scale * index,
            high=100.2 + scale * index,
            low=99.8 + scale * index,
            close=100.1 + scale * index,
            volume=1_000,
        )
        for index in range(7)
    )


def test_cross_index_signal_uses_only_completed_aligned_bars() -> None:
    bars = {symbol: _index_bars(symbol) for symbol in ("SPY", "QQQ", "IWM")}
    params = TrendParameters(
        signal_minute_new_york=10 * 60,
        recent_lookback=3,
        min_session_move=Decimal("0.001"),
        min_confirmations=3,
        risk_fraction=Decimal("0.1"),
        target_r=Decimal("3"),
        max_holding_bars=6,
    )

    original = detect_cross_index_trend(bars, params)
    future = Bar(
        datetime(2025, 5, 1, 14, 5, tzinfo=UTC), 200, 210, 50, 60, 10_000
    )
    with_future = detect_cross_index_trend(
        {symbol: (*rows, future) for symbol, rows in bars.items()}, params
    )

    assert len(original) == 1
    assert original[0].direction == "bullish"
    assert original[0].signal_bar_start == datetime(2025, 5, 1, 14, 0, tzinfo=UTC)
    assert original[0].completed_at == datetime(2025, 5, 1, 14, 5, tzinfo=UTC)
    assert with_future[0] == original[0]


def test_cross_index_underlying_variant_trades_each_confirming_market() -> None:
    bars = {symbol: _index_bars(symbol) for symbol in ("SPY", "QQQ", "IWM")}
    params = TrendParameters(10 * 60, 3, Decimal("0.001"), 2, Decimal(".1"), Decimal("3"), 6)

    signals = detect_cross_index_underlying_trend(bars, params)

    assert {row.underlying for row in signals} == {"SPY", "QQQ", "IWM"}
    assert all(row.signal.direction == "bullish" for row in signals)


def test_rolling_folds_have_unique_oos_and_embargo() -> None:
    sessions = tuple(date(2025, 5, 1) + timedelta(days=index) for index in range(12))

    folds = make_rolling_folds(sessions, train_size=6, embargo=1, test_size=2, step=2)

    assert folds[0].train == sessions[:6]
    assert folds[0].embargo == sessions[6:7]
    assert folds[0].test == sessions[7:9]
    assert folds[1].train == sessions[2:8]
    assert folds[1].embargo == sessions[8:9]
    assert folds[1].test == sessions[9:11]
    assert set(folds[0].test).isdisjoint(folds[1].test)


def test_bracket_target_is_three_r_after_costs_and_next_bar_completion() -> None:
    completed = datetime(2025, 5, 1, 14, 5, tzinfo=UTC)
    rows = (
        OptionPairBar(
            completed,
            Decimal("1.9"), Decimal("2"), Decimal("1.8"), Decimal("1.95"),
            Decimal(".45"), Decimal(".5"), Decimal(".4"), Decimal(".45"),
        ),
        OptionPairBar(
            completed + timedelta(minutes=5),
            Decimal("2.5"), Decimal("2.6"), Decimal("2.4"), Decimal("2.55"),
            Decimal(".45"), Decimal(".5"), Decimal(".4"), Decimal(".45"),
        ),
    )

    trade = bracket_round_trip(
        completed,
        rows,
        Costs(Decimal(".02"), Decimal(".65")),
        risk_fraction=Decimal(".1"),
        target_r=Decimal("3"),
        max_holding_bars=3,
    )

    assert trade.entry_at == completed + timedelta(minutes=5)
    assert trade.exit_at == completed + timedelta(minutes=10)
    assert trade.exit_reason == "target"
    assert trade.return_r == Decimal("3")
    assert trade.operational_target_stop == Decimal("3")


def test_bracket_timestamps_respect_option_bar_duration() -> None:
    completed = datetime(2025, 5, 1, 14, 0, tzinfo=UTC)
    rows = (
        OptionPairBar(
            completed,
            Decimal("1.9"), Decimal("2"), Decimal("1.8"), Decimal("1.95"),
            Decimal(".45"), Decimal(".5"), Decimal(".4"), Decimal(".45"),
        ),
        OptionPairBar(
            completed + timedelta(minutes=15),
            Decimal("2.5"), Decimal("2.6"), Decimal("2.4"), Decimal("2.55"),
            Decimal(".45"), Decimal(".5"), Decimal(".4"), Decimal(".45"),
        ),
    )

    trade = bracket_round_trip(
        completed,
        rows,
        Costs(Decimal(".02"), Decimal(".65")),
        risk_fraction=Decimal(".1"),
        target_r=Decimal("3"),
        max_holding_bars=3,
        bar_minutes=15,
    )

    assert trade.entry_at == completed + timedelta(minutes=15)
    assert trade.exit_at == completed + timedelta(minutes=30)


def test_performance_reports_profit_factor() -> None:
    result = performance((Decimal("30"), Decimal("-10"), Decimal("15")))

    assert result["net_pnl"] == Decimal("35")
    assert result["profit_factor"] == Decimal("4.5")
    assert result["hit_rate"] == Decimal("2") / Decimal("3")


def test_empty_performance_has_complete_zeroed_accounting() -> None:
    result = performance(())

    assert result["gross_profit"] == Decimal(0)
    assert result["gross_loss"] == Decimal(0)
    assert result["profit_factor"] is None


def test_stock_cli_page_accepts_both_observed_response_shapes() -> None:
    row = {"t": "2025-05-01T13:30:00Z"}

    assert stock_page_rows({"bars": [row]}, "SPY") == [row]
    assert stock_page_rows({"bars": {"SPY": [row]}}, "SPY") == [row]
