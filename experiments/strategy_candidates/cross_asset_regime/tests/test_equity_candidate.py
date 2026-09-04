from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.cross_asset_regime.candidate import StockBar
from experiments.strategy_candidates.cross_asset_regime.equity_candidate import (
    EquityCosts,
    EquitySignal,
    EquityVariant,
    bracket_levels,
    simulate_equity_trade,
)


def test_bracket_prices_preserve_net_three_to_one_after_costs() -> None:
    costs = EquityCosts(Decimal("0.0001"), Decimal("0.005"))
    stop, target, risk = bracket_levels(
        direction="bullish", raw_entry=Decimal("100"), shares=100,
        stop_fraction=Decimal("0.0025"), costs=costs,
    )
    entry_fill = Decimal("100") * Decimal("1.0001")
    stop_net = (stop * Decimal("0.9999") - entry_fill) * 100 - Decimal("1.00")
    target_net = (target * Decimal("0.9999") - entry_fill) * 100 - Decimal("1.00")
    assert stop_net < 0
    assert target_net / abs(stop_net) >= Decimal("3")
    assert risk == abs(stop_net)


def test_next_bar_equity_execution_hits_target_and_reports_r() -> None:
    start = datetime(2026, 1, 20, 16, 45, tzinfo=UTC)
    signal = EquitySignal(date(2026, 1, 20), start, "bullish", "QQQ", Decimal("100"), "eq")
    bars = []
    for index in range(8):
        timestamp = start + timedelta(minutes=15 * index)
        high = Decimal("101.5") if index else Decimal("100.2")
        bars.append(StockBar("QQQ", timestamp, Decimal("100"), high, Decimal("99.9"), Decimal("100"), 1000))
    variant = EquityVariant("eq", 3, Decimal("0.0005"), Decimal("0.0025"))
    trade = simulate_equity_trade(signal, tuple(bars), variant, EquityCosts(Decimal("0.0001"), Decimal("0.005")))
    assert trade.outcome == "target"
    assert trade.shares == 99
    assert trade.return_r >= Decimal("3")
    assert trade.target_to_stop >= Decimal("3")
