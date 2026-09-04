from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from experiments.strategy_candidates.event_flow.engine import (
    Bar,
    Costs,
    Signal,
    StrategyParameters,
    bracket_levels,
    simulate_trade,
)


def _bar(minute: int, open_: str, high: str, low: str, close: str) -> Bar:
    return Bar(
        symbol="XLK",
        timestamp=datetime(2026, 1, 2, 14, minute, tzinfo=UTC),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=100_000,
    )


def test_bracket_target_is_at_least_three_times_after_cost_stop_risk() -> None:
    costs = Costs(slippage_bps=Decimal(1), fee_per_share_per_side=Decimal("0.005"))
    stop, target, risk, target_reward = bracket_levels(
        direction=1,
        raw_entry=Decimal(100),
        shares=100,
        stop_fraction=Decimal("0.002"),
        costs=costs,
    )

    assert stop < Decimal(100) < target
    assert risk > 0
    assert target_reward / risk >= Decimal(3)


def test_simulator_enters_next_bar_and_uses_stop_first_on_ambiguous_bar() -> None:
    signal = Signal(
        symbol="XLK",
        completed_at=datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
        direction=1,
        family="test",
        variant="test-v1",
    )
    bars = (
        _bar(30, "100", "100.1", "99.9", "100"),
        _bar(45, "100", "100.1", "99.9", "100"),
        _bar(59, "100", "101", "99", "100.5"),
    )
    params = StrategyParameters(stop_fraction=Decimal("0.002"), max_holding_bars=2)

    trade = simulate_trade(signal, bars, params, Costs())

    assert trade.entry_at == bars[1].timestamp
    assert trade.outcome == "stop"
    assert abs(trade.return_r - Decimal(-1)) < Decimal("0.001")


def test_simulator_rejects_same_bar_entry_when_no_next_completed_bar() -> None:
    signal = Signal(
        symbol="XLK",
        completed_at=datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
        direction=1,
        family="test",
        variant="test-v1",
    )

    with pytest.raises(ValueError, match="NEXT_BAR"):
        simulate_trade(
            signal, (_bar(30, "100", "101", "99", "100"),), StrategyParameters(), Costs()
        )
