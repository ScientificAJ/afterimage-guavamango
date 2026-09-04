from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from test_warrant_authority import intent_and_decision

from afterimage.contracts.models import ExitPlan
from afterimage.execution.watchdog import PositionWatchdog, WatchdogAction


class WatchdogGateway:
    async def positions(self) -> tuple[dict[str, Any], ...]:
        return (
            {"symbol": "SPY260908P00650000", "qty": "1"},
            {"symbol": "SPY260908P00644000", "qty": "-1"},
        )

    async def option_quotes(self, **_: Any) -> dict[str, Any]:
        return {
            "quotes": {
                "SPY260908P00650000": {
                    "bp": "1.80",
                    "ap": "1.82",
                    "t": "2026-09-04T14:00:00Z",
                },
                "SPY260908P00644000": {
                    "bp": "0.10",
                    "ap": "0.12",
                    "t": "2026-09-04T14:00:00Z",
                },
            }
        }


@pytest.mark.asyncio
async def test_watchdog_uses_broker_positions_and_executable_exit_quotes() -> None:
    intent, _ = intent_and_decision()
    now = datetime(2026, 9, 4, 14, 0, 1, tzinfo=UTC)
    plan = ExitPlan(target_r=Decimal(3), stop_r=Decimal(-1), exit_at=now + timedelta(hours=1))

    assessment = await PositionWatchdog(WatchdogGateway()).assess(
        intent,
        plan,
        target_profit=Decimal(100),
        stop_loss=Decimal(50),
        now=now,
    )

    assert assessment.position_matches is True
    assert assessment.current_profit == Decimal(100)
    assert assessment.action == WatchdogAction.EXIT_TARGET
    assert assessment.exit_limit_price == Decimal("1.68")
    assert [leg.position_intent for leg in assessment.exit_legs] == [
        "sell_to_close",
        "buy_to_close",
    ]


@pytest.mark.asyncio
async def test_watchdog_halts_before_pnl_rules_when_positions_do_not_match() -> None:
    intent, _ = intent_and_decision()

    class MismatchGateway(WatchdogGateway):
        async def positions(self) -> tuple[dict[str, Any], ...]:
            return ()

    now = datetime(2026, 9, 4, 14, 0, 1, tzinfo=UTC)
    assessment = await PositionWatchdog(MismatchGateway()).assess(
        intent,
        ExitPlan(target_r=Decimal(3), stop_r=Decimal(-1), exit_at=now + timedelta(hours=1)),
        target_profit=Decimal(100),
        stop_loss=Decimal(50),
        now=now,
    )

    assert assessment.action == WatchdogAction.HALT_POSITION_MISMATCH


@pytest.mark.asyncio
async def test_watchdog_rejects_expected_legs_plus_unknown_exposure() -> None:
    intent, _ = intent_and_decision()

    class ExtraPositionGateway(WatchdogGateway):
        async def positions(self) -> tuple[dict[str, Any], ...]:
            return (*await super().positions(), {"symbol": "QQQ", "qty": "1"})

    now = datetime(2026, 9, 4, 14, 0, 1, tzinfo=UTC)
    assessment = await PositionWatchdog(ExtraPositionGateway()).assess(
        intent,
        ExitPlan(target_r=Decimal(3), stop_r=Decimal(-1), exit_at=now + timedelta(hours=1)),
        target_profit=Decimal(100),
        stop_loss=Decimal(50),
        now=now,
    )

    assert assessment.action == WatchdogAction.HALT_POSITION_MISMATCH


def test_watchdog_recognizes_an_exact_proportional_partial_fill() -> None:
    intent, _ = intent_and_decision()
    intended = intent.model_copy(update={"quantity": 5})
    positions = (
        {"symbol": "SPY260908P00650000", "qty": "2"},
        {"symbol": "SPY260908P00644000", "qty": "-2"},
    )

    assert PositionWatchdog.matched_quantity(intended, positions) == 2
