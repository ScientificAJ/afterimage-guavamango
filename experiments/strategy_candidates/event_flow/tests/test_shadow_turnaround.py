from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from experiments.strategy_candidates.event_flow.engine import Trade
from experiments.strategy_candidates.event_flow.shadow_turnaround import (
    executed_shadow_trades,
    signal_blocked_through_exit_session,
)


def _trade(weekday_day: int) -> Trade:
    at = datetime(2026, 6, weekday_day, 14, 30, tzinfo=UTC)
    return Trade(
        family="shadow",
        variant="shadow",
        symbol="SPY",
        direction=1,
        signal_at=at,
        entry_at=at,
        exit_at=at,
        raw_entry=Decimal(100),
        entry_fill=Decimal(100),
        stop_price=Decimal(99),
        target_price=Decimal(103),
        raw_exit=Decimal(103),
        exit_fill=Decimal(103),
        shares=1,
        net_pnl=Decimal(3),
        risk_dollars=Decimal(1),
        return_r=Decimal(3),
        outcome="target",
        target_to_stop=Decimal(3),
        modeled_fees=Decimal(0),
        modeled_slippage=Decimal(0),
    )


def test_shadow_gate_executes_only_monday_through_wednesday() -> None:
    monday = _trade(1)
    thursday = _trade(4)

    assert executed_shadow_trades((monday, thursday), (0, 1, 2)) == (monday,)


def test_shadow_clock_blocks_new_signal_for_entire_exit_session() -> None:
    exit_at = datetime(2026, 6, 2, 14, 30, tzinfo=UTC)
    same_session_close = datetime(2026, 6, 2, 20, 0, tzinfo=UTC)
    following_session_close = datetime(2026, 6, 3, 20, 0, tzinfo=UTC)

    assert signal_blocked_through_exit_session(same_session_close, exit_at)
    assert not signal_blocked_through_exit_session(following_session_close, exit_at)
