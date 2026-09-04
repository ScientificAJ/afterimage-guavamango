from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.candidate import (
    Costs,
    Contract,
    OptionBar,
    OptionFrame,
    ScoredTrade,
    StockBar,
    Trade,
    VARIANTS,
    enforce_non_overlapping,
    select_on_training,
    select_vertical,
    signal_for_session,
    simulate_trade,
    summarize,
    target_stop_levels,
)


UNIVERSE = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")


def _bars(closes: dict[str, str], future: dict[str, str] | None = None) -> tuple[StockBar, ...]:
    rows: list[StockBar] = []
    for symbol in UNIVERSE:
        rows.append(
            StockBar(symbol, datetime(2026, 1, 20, 14, 30, tzinfo=UTC), Decimal("100"), Decimal("100"), Decimal("100"), Decimal("100"), 100)
        )
        rows.append(
            StockBar(symbol, datetime(2026, 1, 20, 15, 15, tzinfo=UTC), Decimal(closes[symbol]), Decimal(closes[symbol]), Decimal(closes[symbol]), Decimal(closes[symbol]), 100)
        )
        if future:
            rows.append(
                StockBar(symbol, datetime(2026, 1, 20, 15, 30, tzinfo=UTC), Decimal(future[symbol]), Decimal(future[symbol]), Decimal(future[symbol]), Decimal(future[symbol]), 100)
            )
    return tuple(rows)


def _daily(up: bool = True) -> tuple[tuple[date, Decimal], ...]:
    base = date(2026, 1, 5)
    values = [Decimal(100 + index) if up else Decimal(120 - index) for index in range(10)]
    return tuple((base + timedelta(days=index), value) for index, value in enumerate(values))


def test_signal_uses_only_bars_completed_by_1030_and_selects_relative_strength_leader() -> None:
    closes = {"QQQ": "101.0", "IWM": "100.3", "XLK": "100.8", "XLF": "100.4", "XLE": "100.2", "XLV": "99.9", "XLY": "100.5"}
    future = {symbol: "80" for symbol in UNIVERSE}
    signal = signal_for_session(VARIANTS[0], _bars(closes, future), _daily(), date(2026, 1, 20))
    assert signal is not None
    assert signal.completed_at == datetime(2026, 1, 20, 15, 30, tzinfo=UTC)
    assert signal.direction == "bullish"
    assert signal.underlying == "QQQ"
    assert signal.reference_price == Decimal("101.0")
    assert signal.breadth_count == 6


def test_bearish_signal_selects_iwm_laggard_symmetrically() -> None:
    closes = {"QQQ": "99.7", "IWM": "99.0", "XLK": "99.2", "XLF": "99.6", "XLE": "99.8", "XLV": "100.1", "XLY": "99.5"}
    signal = signal_for_session(VARIANTS[0], _bars(closes), _daily(up=False), date(2026, 1, 20))
    assert signal is not None
    assert signal.direction == "bearish"
    assert signal.underlying == "IWM"
    assert signal.breadth_count == 6


def test_spy_regime_variant_filters_a_direction_misaligned_with_prior_data() -> None:
    closes = {"QQQ": "101.0", "IWM": "100.3", "XLK": "100.8", "XLF": "100.4", "XLE": "100.2", "XLV": "100.1", "XLY": "100.5"}
    assert signal_for_session(VARIANTS[2], _bars(closes), _daily(up=False), date(2026, 1, 20)) is None
    assert signal_for_session(VARIANTS[2], _bars(closes), _daily(up=True), date(2026, 1, 20)) is not None


def test_vertical_is_exactly_five_wide_and_uses_earliest_eligible_expiry() -> None:
    closes = {"QQQ": "101.2", "IWM": "100.3", "XLK": "100.8", "XLF": "100.4", "XLE": "100.2", "XLV": "100.1", "XLY": "100.5"}
    signal = signal_for_session(VARIANTS[0], _bars(closes), _daily(), date(2026, 1, 20))
    assert signal is not None
    contracts = (
        Contract("LATE", "QQQ", date(2026, 1, 30), Decimal("101"), "call"),
        Contract("LONG", "QQQ", date(2026, 1, 23), Decimal("101"), "call"),
        Contract("SHORT", "QQQ", date(2026, 1, 23), Decimal("106"), "call"),
        Contract("WRONG", "QQQ", date(2026, 1, 23), Decimal("105"), "call"),
    )
    vertical = select_vertical(signal, contracts)
    assert vertical.long.symbol == "LONG"
    assert vertical.short.symbol == "SHORT"
    assert vertical.width == Decimal("5")


def test_adverse_next_option_bar_fills_and_fees_are_applied() -> None:
    completed = datetime(2026, 1, 20, 15, 30, tzinfo=UTC)
    closes = {"QQQ": "101.2", "IWM": "100.3", "XLK": "100.8", "XLF": "100.4", "XLE": "100.2", "XLV": "100.1", "XLY": "100.5"}
    signal = signal_for_session(VARIANTS[0], _bars(closes), _daily(), date(2026, 1, 20))
    assert signal is not None
    long = Contract("LONG", "QQQ", date(2026, 1, 23), Decimal("101"), "call")
    short = Contract("SHORT", "QQQ", date(2026, 1, 23), Decimal("106"), "call")
    frames = []
    for index in range(9):
        timestamp = completed + timedelta(minutes=15 * index)
        if index == 0:
            long_bar = OptionBar("LONG", timestamp, Decimal("2.0"), Decimal("2.20"), Decimal("1.90"), Decimal("2.0"), 10)
            short_bar = OptionBar("SHORT", timestamp, Decimal("0.8"), Decimal("0.90"), Decimal("0.70"), Decimal("0.8"), 10)
        else:
            long_bar = OptionBar("LONG", timestamp, Decimal("2.6"), Decimal("2.70"), Decimal("2.50"), Decimal("2.6"), 10)
            short_bar = OptionBar("SHORT", timestamp, Decimal("0.9"), Decimal("1.00"), Decimal("0.80"), Decimal("0.9"), 10)
        frames.append(OptionFrame(timestamp, long_bar, short_bar))
    trade = simulate_trade(signal, long, short, tuple(frames), hold_bars=7, costs=Costs(Decimal("0.03"), Decimal("0.65")))
    assert trade.entry_at == completed
    assert trade.exit_at == completed + timedelta(minutes=105)
    assert trade.entry_debit == Decimal("1.56")
    assert trade.exit_credit == Decimal("1.44")
    assert trade.net_pnl == Decimal("-14.60")
    assert trade.return_r == Decimal("-14.60") / Decimal("157.30")


def test_non_overlapping_filter_rejects_a_second_open_position() -> None:
    start = datetime(2026, 1, 20, 15, 30, tzinfo=UTC)
    first = Trade(date(2026, 1, 20), "v", "bullish", "QQQ", "L", "S", start, start + timedelta(hours=2), Decimal("1"), Decimal("1.1"), Decimal("7.40"), Decimal("0.073"), Decimal("2.60"), Decimal("0.06"))
    overlap = Trade(date(2026, 1, 20), "v", "bearish", "IWM", "L2", "S2", start + timedelta(hours=1), start + timedelta(hours=3), Decimal("1"), Decimal("1"), Decimal("-2.60"), Decimal("-0.026"), Decimal("2.60"), Decimal("0.06"))
    later = Trade(date(2026, 1, 21), "v", "bullish", "QQQ", "L3", "S3", start + timedelta(days=1), start + timedelta(days=1, hours=1), Decimal("1"), Decimal("1"), Decimal("-2.60"), Decimal("-0.026"), Decimal("2.60"), Decimal("0.06"))
    assert enforce_non_overlapping((overlap, later, first)) == (first, later)


def test_summary_and_training_selection_are_hand_derived_and_ignore_holdout() -> None:
    training_dates = (date(2026, 1, 20), date(2026, 1, 21))
    rows = {
        "a": (
            ScoredTrade(training_dates[0], Decimal("0.10"), Decimal("10")),
            ScoredTrade(training_dates[1], Decimal("-0.02"), Decimal("-2")),
            ScoredTrade(date(2026, 8, 3), Decimal("99"), Decimal("9999")),
        ),
        "b": (
            ScoredTrade(training_dates[0], Decimal("0.03"), Decimal("3")),
            ScoredTrade(training_dates[1], Decimal("0.03"), Decimal("3")),
        ),
    }
    assert select_on_training(rows, training_dates, minimum_samples=2) == "a"
    metrics = summarize(rows["a"][:2])
    assert metrics.sample_count == 2
    assert metrics.net_pnl == Decimal("8.00")
    assert metrics.expectancy_r == Decimal("0.04")
    assert metrics.hit_rate == Decimal("0.5")
    assert metrics.max_drawdown == Decimal("2.00")
    assert metrics.profit_factor == Decimal("5")


def test_three_r_levels_and_target_exit_are_net_of_fees_and_slippage() -> None:
    costs = Costs(Decimal("0.03"), Decimal("0.65"))
    stop_credit, target_credit = target_stop_levels(Decimal("1.00"), costs)
    stop_net = (stop_credit - Decimal("1.00")) * Decimal(100) - Decimal("2.60")
    target_net = (target_credit - Decimal("1.00")) * Decimal(100) - Decimal("2.60")
    assert stop_credit == Decimal("0.78")
    assert target_credit == Decimal("1.77")
    assert target_net / abs(stop_net) >= Decimal("3")

    closes = {"QQQ": "101.2", "IWM": "100.3", "XLK": "100.8", "XLF": "100.4", "XLE": "100.2", "XLV": "100.1", "XLY": "100.5"}
    signal = signal_for_session(VARIANTS[0], _bars(closes), _daily(), date(2026, 1, 20))
    assert signal is not None
    long = Contract("LONG", "QQQ", date(2026, 1, 23), Decimal("101"), "call")
    short = Contract("SHORT", "QQQ", date(2026, 1, 23), Decimal("106"), "call")
    entry_time = signal.completed_at
    frames = (
        OptionFrame(
            entry_time,
            OptionBar("LONG", entry_time, Decimal("1.7"), Decimal("2.00"), Decimal("1.60"), Decimal("1.7"), 10),
            OptionBar("SHORT", entry_time, Decimal("1.10"), Decimal("1.20"), Decimal("1.06"), Decimal("1.10"), 10),
        ),
        OptionFrame(
            entry_time + timedelta(minutes=15),
            OptionBar("LONG", entry_time + timedelta(minutes=15), Decimal("3.10"), Decimal("3.20"), Decimal("3.05"), Decimal("3.10"), 10),
            OptionBar("SHORT", entry_time + timedelta(minutes=15), Decimal("1.10"), Decimal("1.20"), Decimal("1.00"), Decimal("1.10"), 10),
        ),
        *tuple(
            OptionFrame(
                entry_time + timedelta(minutes=15 * index),
                OptionBar("LONG", entry_time + timedelta(minutes=15 * index), Decimal("3.1"), Decimal("3.2"), Decimal("3.05"), Decimal("3.1"), 10),
                OptionBar("SHORT", entry_time + timedelta(minutes=15 * index), Decimal("1.1"), Decimal("1.2"), Decimal("1.0"), Decimal("1.1"), 10),
            )
            for index in range(2, 9)
        ),
    )
    trade = simulate_trade(signal, long, short, frames, hold_bars=7, costs=costs, exit_mode="target_stop_3r")
    assert trade.exit_at == entry_time + timedelta(minutes=15)
    assert trade.exit_credit == Decimal("1.77")
    assert trade.net_pnl == Decimal("74.40")
    assert trade.outcome == "target"
