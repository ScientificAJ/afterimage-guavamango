from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from experiments.strategy_candidates.event_flow.engine import Trade
from experiments.strategy_candidates.event_flow.walkforward import select_for_fold


def _trade(variant: str, year: int, month: int, day: int, result: str) -> Trade:
    at = datetime(year, month, day, 14, 30, tzinfo=UTC)
    return Trade(
        family="test",
        variant=variant,
        symbol="SPY",
        direction=1,
        signal_at=at,
        entry_at=at,
        exit_at=at,
        raw_entry=Decimal(100),
        entry_fill=Decimal(100),
        stop_price=Decimal(99),
        target_price=Decimal(103),
        raw_exit=Decimal(100),
        exit_fill=Decimal(100),
        shares=1,
        net_pnl=Decimal(result),
        risk_dollars=Decimal(1),
        return_r=Decimal(result),
        outcome="time",
        target_to_stop=Decimal(3),
        modeled_fees=Decimal(0),
        modeled_slippage=Decimal(0),
    )


def test_fold_selection_cannot_see_trades_from_fold_or_future() -> None:
    rows = {
        "stable": tuple(_trade("stable", 2025, 12, day, "0.3") for day in range(1, 13)),
        "future_star": (
            *(_trade("future_star", 2025, 12, day, "0.1") for day in range(1, 13)),
            _trade("future_star", 2026, 1, 2, "3"),
        ),
    }
    fold_start = datetime(2026, 1, 1, tzinfo=UTC)

    selected = select_for_fold(rows, fold_start, minimum_samples=10)

    assert selected == "stable"
