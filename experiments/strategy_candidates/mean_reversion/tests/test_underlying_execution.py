from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.underlying_execution import (
    EquityCosts,
    build_equity_dry_run_order,
    underlying_bracket,
)


def test_underlying_bracket_target_is_three_r_after_costs() -> None:
    completed = datetime(2025, 5, 1, 14, 5, tzinfo=UTC)
    rows = (
        Bar(completed, 100, 100.2, 99.8, 100, 10_000),
        Bar(completed + timedelta(minutes=5), 100, 103.2, 99.9, 103, 10_000),
    )

    trade = underlying_bracket(
        completed,
        rows,
        "bullish",
        EquityCosts(slippage_bps=Decimal(0), fee_per_share=Decimal(0)),
        risk_distance=Decimal("1"),
        quantity=10,
        target_r=Decimal("3"),
        max_holding_bars=3,
    )

    assert trade.entry_at == completed + timedelta(minutes=5)
    assert trade.exit_reason == "target"
    assert trade.net_pnl == Decimal("30.00")
    assert trade.return_r == Decimal("3.0000")
    assert trade.operational_target_stop == Decimal("3")


def test_same_bar_target_and_stop_resolves_to_stop() -> None:
    completed = datetime(2025, 5, 1, 14, 5, tzinfo=UTC)
    rows = (
        Bar(completed, 100, 100.2, 99.8, 100, 10_000),
        Bar(completed + timedelta(minutes=5), 100, 104, 98, 103, 10_000),
    )

    trade = underlying_bracket(
        completed,
        rows,
        "bullish",
        EquityCosts(Decimal(0), Decimal(0)),
        Decimal("1"),
        10,
        Decimal("3"),
        3,
    )

    assert trade.exit_reason == "stop"
    assert trade.net_pnl == Decimal("-10.00")


def test_equity_bracket_dry_run_is_exact_and_non_submitting() -> None:
    artifact = build_equity_dry_run_order(
        "SPY", "bullish", 10, Decimal("600.10"), Decimal("603.10"), Decimal("599.10")
    )

    assert artifact["submission_allowed"] is False
    assert artifact["cli_arguments"][-1] == "--dry-run"
    assert artifact["payload"]["order_class"] == "bracket"
    assert artifact["payload"]["take_profit"] == {"limit_price": "603.10"}
    assert artifact["payload"]["stop_loss"] == {"stop_price": "599.10"}
