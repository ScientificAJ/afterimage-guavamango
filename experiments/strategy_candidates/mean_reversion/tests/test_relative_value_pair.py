from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.relative_value_pair import (
    PairBar,
    PairCosts,
    PairParameters,
    detect_relative_divergence,
    pair_bracket,
)


def _rows(open_price: float, target_price: float) -> tuple[Bar, ...]:
    start = datetime(2024, 9, 3, 13, 30, tzinfo=UTC)
    return tuple(
        Bar(start + timedelta(minutes=5 * index), open_price, target_price + .1, open_price - .1, open_price + (target_price - open_price) * index / 18, 10_000)
        for index in range(19)
    )


def test_divergence_signal_is_completed_and_independent_of_future_bars() -> None:
    bars = {
        "SPY": _rows(100, 100.2),
        "QQQ": _rows(100, 101),
        "IWM": _rows(100, 99.8),
    }
    params = PairParameters(11 * 60, Decimal("0.005"))

    original = detect_relative_divergence(bars, params)
    future = Bar(datetime(2024, 9, 3, 15, 5, tzinfo=UTC), 100, 200, 50, 60, 100_000)
    with_future = detect_relative_divergence(
        {symbol: (*rows, future) for symbol, rows in bars.items()}, params
    )

    assert len(original) == 1
    assert original[0].leader == "QQQ"
    assert original[0].laggard == "IWM"
    assert original[0].completed_at == datetime(2024, 9, 3, 15, 5, tzinfo=UTC)
    assert with_future == original


def test_pair_target_is_three_r_after_all_leg_costs() -> None:
    completed = datetime(2024, 9, 3, 15, 5, tzinfo=UTC)
    rows = (
        PairBar(completed, 100, 100, 100, 100, 100, 100, 100, 100),
        PairBar(completed + timedelta(minutes=5), 100, 102, 100, 102, 100, 100, 99, 99),
    )

    trade = pair_bracket(
        completed,
        rows,
        PairCosts(Decimal(0), Decimal(0)),
        notional_per_leg=Decimal("10000"),
        risk_dollars=Decimal("100"),
        target_r=Decimal("3"),
        max_holding_bars=3,
    )

    assert trade.exit_reason == "target"
    assert trade.net_pnl == Decimal("300.00")
    assert trade.return_r == Decimal("3.0000")
    assert trade.operational_target_stop == Decimal("3")


def test_pair_waits_for_completed_closes_instead_of_combining_async_extremes() -> None:
    completed = datetime(2024, 9, 3, 15, 5, tzinfo=UTC)
    rows = (
        PairBar(completed, 100, 100, 100, 100, 100, 100, 100, 100),
        PairBar(completed + timedelta(minutes=5), 100, 105, 95, 100, 100, 105, 95, 100),
    )

    trade = pair_bracket(
        completed,
        rows,
        PairCosts(Decimal(0), Decimal(0)),
        Decimal("10000"),
        Decimal("100"),
        Decimal("3"),
        3,
    )

    assert trade.exit_reason == "timeout"
    assert trade.net_pnl == Decimal("0.00")
