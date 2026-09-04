from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from candidate import Contract, OptionBar, SpreadFrame
from pivots import (
    CONDOR_FAMILIES,
    MOMENTUM_FAMILIES,
    STRANGLE_FAMILIES,
    CondorFrame,
    PivotTrade,
    condor_signal,
    expansion_signal,
    fixed_family_walk_forward,
    lagged_market_features,
    momentum_direction,
    promotion_gates,
    rolling_walk_forward,
    select_condor_legs,
    select_debit_pair,
    select_strangle_legs,
    simulate_condor,
    simulate_debit_vertical,
    simulate_long_option,
    simulate_long_strangle,
    summarize_pivots,
)


def bar(symbol: str, timestamp: str, low: str, high: str) -> OptionBar:
    return OptionBar(
        symbol=symbol,
        timestamp=datetime.fromisoformat(timestamp),
        open=Decimal(low),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(high),
        volume=100,
    )


def spread_frame(
    timestamp: str, long_low: str, long_high: str, short_low: str, short_high: str
) -> SpreadFrame:
    return SpreadFrame(
        timestamp=datetime.fromisoformat(timestamp),
        long=bar("LONG", timestamp, long_low, long_high),
        short=bar("SHORT", timestamp, short_low, short_high),
    )


def test_debit_vertical_enforces_three_to_one_target_after_costs() -> None:
    family = MOMENTUM_FAMILIES[0]
    result = simulate_debit_vertical(
        session_date="2026-05-01",
        symbol="SPY",
        family=family,
        direction="bullish",
        width=Decimal(5),
        frames=(
            spread_frame("2026-05-01T14:00:00+00:00", "1.40", "1.50", "0.50", "0.55"),
            spread_frame("2026-05-01T14:05:00+00:00", "2.00", "2.10", "0.15", "0.20"),
        ),
    )

    assert result.entry_value == Decimal("1.02")
    assert result.exit_value == Decimal("1.78")
    assert result.net_pnl == Decimal("75.88")
    assert result.modeled_fees == Decimal("0.12")
    assert result.modeled_slippage == Decimal("4.00")
    assert result.outcome == "target"
    assert result.target_dollars == result.stop_risk_dollars * Decimal(3)
    assert result.operational_target_stop == Decimal(3)


def test_iron_condor_enforces_three_to_one_target_after_costs() -> None:
    family = CONDOR_FAMILIES[0]
    at_entry = "2026-05-01T14:00:00+00:00"
    at_exit = "2026-05-01T14:05:00+00:00"
    result = simulate_condor(
        session_date="2026-05-01",
        symbol="SPY",
        family=family,
        width=Decimal(5),
        frames=(
            CondorFrame(
                timestamp=datetime.fromisoformat(at_entry),
                short_put=bar("SP", at_entry, "1.00", "1.10"),
                long_put=bar("LP", at_entry, "0.20", "0.30"),
                short_call=bar("SC", at_entry, "1.00", "1.10"),
                long_call=bar("LC", at_entry, "0.20", "0.30"),
            ),
            CondorFrame(
                timestamp=datetime.fromisoformat(at_exit),
                short_put=bar("SP", at_exit, "0.40", "0.50"),
                long_put=bar("LP", at_exit, "0.20", "0.25"),
                short_call=bar("SC", at_exit, "0.40", "0.50"),
                long_call=bar("LC", at_exit, "0.20", "0.25"),
            ),
        ),
    )

    assert result.entry_value == Decimal("1.36")
    assert result.exit_value == Decimal("0.64")
    assert result.net_pnl == Decimal("71.76")
    assert result.modeled_fees == Decimal("0.24")
    assert result.modeled_slippage == Decimal("8.00")
    assert result.outcome == "target"
    assert result.target_dollars == result.stop_risk_dollars * Decimal(3)


def test_lagged_features_ignore_current_session_values() -> None:
    closes = tuple((date(2026, 3, day), Decimal(100 + day)) for day in range(1, 22))
    baseline = lagged_market_features(closes, date(2026, 3, 22), trend_lookback=20)
    contaminated = lagged_market_features(
        closes + ((date(2026, 3, 22), Decimal(9999)),),
        date(2026, 3, 22),
        trend_lookback=20,
    )

    assert contaminated == baseline
    assert baseline.prior_close == Decimal(121)
    assert baseline.volatility_5 > 0
    assert baseline.volatility_20 > 0


def test_momentum_and_condor_signals_use_fixed_filters() -> None:
    closes = tuple((date(2026, 3, day), Decimal(100 + day)) for day in range(1, 22))
    uptrend = lagged_market_features(closes, date(2026, 3, 22), trend_lookback=20)
    down_closes = tuple((date(2026, 3, day), Decimal(130 - day)) for day in range(1, 22))
    downtrend = lagged_market_features(down_closes, date(2026, 3, 22), trend_lookback=20)

    assert momentum_direction(MOMENTUM_FAMILIES[1], Decimal("0.006"), uptrend) == "bullish"
    assert momentum_direction(MOMENTUM_FAMILIES[1], Decimal("-0.006"), downtrend) == "bearish"
    assert momentum_direction(MOMENTUM_FAMILIES[1], Decimal("0.004"), uptrend) is None
    compressed = replace(uptrend, volatility_5=Decimal("0.007"), volatility_20=Decimal("0.01"))
    assert condor_signal(CONDOR_FAMILIES[0], Decimal("0.001"), compressed)
    assert not condor_signal(CONDOR_FAMILIES[0], Decimal("0.003"), compressed)


def test_fixed_contract_selectors_build_same_expiration_defined_risk_structures() -> None:
    expiration = date(2026, 5, 8)
    contracts = tuple(
        Contract(f"P{strike}", expiration, Decimal(strike), "put")
        for strike in (90, 93, 94, 95, 98, 99, 100)
    ) + tuple(
        Contract(f"C{strike}", expiration, Decimal(strike), "call")
        for strike in (100, 101, 105, 106, 110)
    )

    debit = select_debit_pair(
        MOMENTUM_FAMILIES[0],
        direction="bullish",
        session_date=date(2026, 5, 1),
        spot=Decimal(100),
        contracts=contracts,
    )
    condor = select_condor_legs(
        CONDOR_FAMILIES[0],
        session_date=date(2026, 5, 1),
        spot=Decimal(100),
        volatility_20=Decimal("0.01"),
        contracts=contracts,
    )

    assert debit.long.symbol == "C100"
    assert debit.short.symbol == "C105"
    assert debit.width == Decimal(5)
    assert {
        item.expiration
        for item in (condor.long_put, condor.short_put, condor.short_call, condor.long_call)
    } == {expiration}
    assert condor.short_put.symbol == "P99"
    assert condor.long_put.symbol == "P94"
    assert condor.short_call.symbol == "C101"
    assert condor.long_call.symbol == "C106"
    assert condor.width == Decimal(5)


def test_expansion_strangle_signal_selector_and_three_to_one_exit() -> None:
    family = STRANGLE_FAMILIES[0]
    expiration = date(2026, 5, 8)
    contracts = tuple(
        Contract(f"P{strike}", expiration, Decimal(strike), "put") for strike in (95, 98, 99, 100)
    ) + tuple(
        Contract(f"C{strike}", expiration, Decimal(strike), "call")
        for strike in (100, 101, 102, 105)
    )
    closes = tuple((date(2026, 3, day), Decimal(100 + day)) for day in range(1, 22))
    features = replace(
        lagged_market_features(closes, date(2026, 3, 22), trend_lookback=20),
        volatility_5=Decimal("0.012"),
        volatility_20=Decimal("0.010"),
    )

    assert expansion_signal(family, Decimal("0.008"), features)
    assert not expansion_signal(family, Decimal("0.004"), features)
    selection = select_strangle_legs(
        family,
        session_date=date(2026, 5, 1),
        spot=Decimal(100),
        contracts=contracts,
    )
    assert selection.put.symbol == "P99"
    assert selection.call.symbol == "C101"

    at_entry = "2026-05-01T14:00:00+00:00"
    at_exit = "2026-05-01T14:05:00+00:00"
    trade = simulate_long_strangle(
        session_date="2026-05-01",
        symbol="SPY",
        family=family,
        frames=(
            (
                bar("PUT", at_entry, "0.40", "0.50"),
                bar("CALL", at_entry, "0.40", "0.50"),
            ),
            (
                bar("PUT", at_exit, "0.20", "0.25"),
                bar("CALL", at_exit, "1.45", "1.55"),
            ),
        ),
    )
    assert trade.entry_value == Decimal("1.02")
    assert trade.exit_value == Decimal("1.63")
    assert trade.net_pnl == Decimal("60.88")
    assert trade.target_dollars == trade.stop_risk_dollars * Decimal(3)
    assert trade.operational_target_stop == Decimal(3)


def test_single_long_option_uses_adverse_bar_extremes_and_three_to_one_exit() -> None:
    family = MOMENTUM_FAMILIES[1]
    trade = simulate_long_option(
        session_date="2026-05-01",
        symbol="QQQ",
        family=family,
        direction="bullish",
        strategy="directional_long_reversal",
        bars=(
            bar("CALL", "2026-05-01T14:00:00+00:00", "0.90", "1.00"),
            bar("CALL", "2026-05-01T14:05:00+00:00", "1.80", "1.90"),
        ),
    )

    assert trade.entry_value == Decimal("1.01")
    assert trade.exit_value == Decimal("1.79")
    assert trade.net_pnl == Decimal("77.94")
    assert trade.modeled_fees == Decimal("0.06")
    assert trade.modeled_slippage == Decimal("2.00")
    assert trade.outcome == "target"
    assert trade.strategy == "directional_long_reversal"
    assert trade.operational_target_stop == Decimal(3)


def pivot_trade(session: str, symbol: str, family: str, return_r: str, pnl: str) -> PivotTrade:
    at = datetime.fromisoformat(f"{session}T14:00:00+00:00")
    value = Decimal(pnl)
    return PivotTrade(
        session_date=session,
        symbol=symbol,
        strategy="directional_debit_momentum",
        family=family,
        direction="bullish",
        entry_at=at,
        exit_at=at,
        entry_value=Decimal(1),
        exit_value=Decimal(1),
        net_pnl=value,
        max_loss=Decimal(100),
        return_r=Decimal(return_r),
        outcome="target" if value > 0 else "stop",
        stop_risk_dollars=Decimal(10),
        target_dollars=Decimal(30),
        operational_target_stop=Decimal(3),
        modeled_fees=Decimal("0.12"),
        modeled_slippage=Decimal(4),
        synchronized_frames=2,
        leg_symbols=("LONG", "SHORT"),
    )


def test_rolling_walk_forward_selects_each_month_from_prior_months_only() -> None:
    families = tuple(item.name for item in MOMENTUM_FAMILIES)
    rows = {
        families[0]: (
            pivot_trade("2026-04-01", "SPY", families[0], "0.10", "10"),
            pivot_trade("2026-05-01", "SPY", families[0], "-0.10", "-10"),
        ),
        families[1]: (
            pivot_trade("2026-04-01", "SPY", families[1], "-0.10", "-10"),
            pivot_trade("2026-05-01", "SPY", families[1], "10", "1000"),
        ),
        families[2]: (),
    }

    rolling = rolling_walk_forward(rows, family_order=families, evaluation_months=("2026-05",))

    assert rolling.folds[0].selected_family == families[0]
    assert rolling.folds[0].training_end == date(2026, 4, 30)
    assert rolling.folds[0].evaluation_month == "2026-05"
    assert rolling.metrics.net_pnl == Decimal("-10.00")


def test_fixed_family_walk_forward_never_switches_after_fold_results() -> None:
    family = MOMENTUM_FAMILIES[2].name
    rows = (
        pivot_trade("2026-04-01", "SPY", family, "0.1", "10"),
        pivot_trade("2026-05-01", "SPY", family, "-0.1", "-10"),
        pivot_trade("2026-06-01", "QQQ", family, "0.2", "20"),
    )

    result = fixed_family_walk_forward(
        rows,
        family=family,
        evaluation_months=("2026-05", "2026-06"),
    )

    assert [fold.selected_family for fold in result.folds] == [family, family]
    assert result.metrics.sample_count == 2
    assert result.metrics.net_pnl == Decimal("10.00")


def test_profit_factor_and_cross_symbol_promotion_gates() -> None:
    family = MOMENTUM_FAMILIES[0].name
    rows = []
    for index in range(40):
        symbol = "SPY" if index % 2 == 0 else "QQQ"
        group = index // 4
        month = 5 + group % 4
        if index % 4 == (0 if group % 2 == 0 else 1):
            rows.append(
                pivot_trade(f"2026-{month:02d}-{index % 20 + 1:02d}", symbol, family, "-1", "-100")
            )
        else:
            rows.append(
                pivot_trade(f"2026-{month:02d}-{index % 20 + 1:02d}", symbol, family, "1", "100")
            )
    metrics = summarize_pivots(rows)
    neighbor_metrics = {
        family: metrics,
        MOMENTUM_FAMILIES[1].name: metrics,
        MOMENTUM_FAMILIES[2].name: summarize_pivots(()),
    }

    gates = promotion_gates(rows, neighbor_metrics=neighbor_metrics)

    assert metrics.profit_factor == Decimal(3)
    assert gates["operational_target_stop_at_least_3"]
    assert gates["profit_factor_at_least_2"]
    assert gates["minimum_pooled_sample"]
    assert gates["expectancy_at_least_quarter_r"]
    assert gates["max_drawdown_at_most_6r"]
    assert gates["positive_at_least_60_percent_months"]
    assert gates["cross_symbol_or_three_positive_regimes"]
    assert gates["profitable_at_one_and_half_costs"]
    assert gates["largest_trade_at_most_25_percent_profit"]
    assert gates["at_least_60_percent_positive_neighbors"]
    assert gates["promoted"]

    insufficient_cross_symbol = [item for item in rows if item.symbol == "SPY"]
    cross_symbol_gates = promotion_gates(
        insufficient_cross_symbol, neighbor_metrics=neighbor_metrics
    )
    assert not cross_symbol_gates["cross_symbol_or_three_positive_regimes"]
    assert not cross_symbol_gates["promoted"]

    bad_ratio = [replace(rows[0], operational_target_stop=Decimal("2.99")), *rows[1:]]
    ratio_gates = promotion_gates(bad_ratio, neighbor_metrics=neighbor_metrics)
    assert not ratio_gates["operational_target_stop_at_least_3"]
    assert not ratio_gates["promoted"]
