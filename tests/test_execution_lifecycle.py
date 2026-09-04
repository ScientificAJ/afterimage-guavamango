from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from test_warrant_authority import intent_and_decision

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import ExecutionIntent, ExitPlan, RiskDecision
from afterimage.execution.lifecycle import (
    ExecutionError,
    ExecutionService,
    authorize_equity_position_exit,
    authorize_position_exit,
)
from afterimage.execution.watchdog import PositionWatchdog
from afterimage.risk.warrant import WarrantAuthority, WarrantError
from afterimage.storage import Database, Repository


class AmbiguousGateway:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.lookup_calls = 0

    async def place_option_order(self, intent: object, client_order_id: str) -> dict[str, object]:
        del intent, client_order_id
        self.submit_calls += 1
        raise RuntimeError("transport disconnected after request")

    async def order_by_client_id(self, client_order_id: str) -> dict[str, object]:
        self.lookup_calls += 1
        if self.lookup_calls < 2:
            return {}
        return {"id": "paper-order-1", "client_order_id": client_order_id, "status": "accepted"}


class ExitGateway:
    async def positions(self) -> tuple[dict[str, object], ...]:
        return (
            {"symbol": "SPY260908P00650000", "qty": "1"},
            {"symbol": "SPY260908P00644000", "qty": "-1"},
        )

    async def option_quotes(self, **_: object) -> dict[str, object]:
        return {
            "quotes": {
                "SPY260908P00650000": {"bp": "1.80", "ap": "1.82", "t": "2026-09-04T14:00:00Z"},
                "SPY260908P00644000": {"bp": "0.10", "ap": "0.12", "t": "2026-09-04T14:00:00Z"},
            }
        }


class NeverObservedGateway:
    async def place_option_order(self, intent: object, client_order_id: str) -> dict[str, object]:
        del intent, client_order_id
        raise RuntimeError("transport disconnected after request")

    async def order_by_client_id(self, client_order_id: str) -> dict[str, object]:
        del client_order_id
        return {}


class InstrumentNeutralGateway:
    def __init__(self) -> None:
        self.asset_classes: list[str] = []

    async def place_order(self, intent: ExecutionIntent, client_order_id: str) -> dict[str, object]:
        self.asset_classes.append(intent.asset_class)
        return {"id": "equity-order", "client_order_id": client_order_id, "status": "accepted"}

    async def order_by_client_id(self, client_order_id: str) -> dict[str, object]:
        del client_order_id
        return {}


@pytest.mark.asyncio
async def test_ambiguous_submit_reconciles_by_client_id_without_resubmitting(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'execution.db'}")
    database.create()
    authority = WarrantAuthority(tmp_path / "warrant.pem", database)
    intent, decision = intent_and_decision()
    warrant = authority.mint(intent, decision)
    gateway = AmbiguousGateway()
    service = ExecutionService(gateway, authority, Repository(database))  # type: ignore[arg-type]

    order = await service.submit("session", warrant)

    assert order.broker_order_id == "paper-order-1"
    assert gateway.submit_calls == 1
    assert gateway.lookup_calls == 2

    with pytest.raises(WarrantError, match="already consumed"):
        await service.submit("session", warrant)
    assert gateway.submit_calls == 1


@pytest.mark.asyncio
async def test_indeterminate_submit_persists_client_id_before_network_call(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'indeterminate.db'}")
    database.create()
    authority = WarrantAuthority(tmp_path / "warrant.pem", database)
    intent, decision = intent_and_decision()
    warrant = authority.mint(intent, decision)
    repository = Repository(database)
    service = ExecutionService(  # type: ignore[arg-type]
        NeverObservedGateway(), authority, repository
    )

    with pytest.raises(ExecutionError, match="AMBIGUOUS_SUBMISSION"):
        await service.submit("session", warrant)

    orders = repository.broker_orders("session")
    assert len(orders) == 1
    assert orders[0]["status"] == "submitting"
    assert orders[0]["id"].startswith("pending:")
    assert orders[0]["client_order_id"].startswith("afterimage-")


@pytest.mark.asyncio
async def test_execution_service_submits_equity_through_instrument_neutral_gateway(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'equity.db'}")
    database.create()
    authority = WarrantAuthority(tmp_path / "warrant.pem", database)
    intent = ExecutionIntent(
        account_id_hash="a" * 64,
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=uuid4(),
        asset_class="equity",
        symbol="QQQ",
        side="buy",
        quantity=10,
        limit_price=Decimal(100),
        take_profit_price=Decimal("103.4"),
        stop_price=Decimal(99),
        order_class="bracket",
    )
    decision = RiskDecision(
        decision_id=intent.risk_decision_id,
        status="PASS",
        gates=(),
        quantity=10,
        modeled_max_loss=Decimal(11),
        strategy_manifest_hash=intent.strategy_manifest_hash,
        evidence_commit_hash=intent.evidence_commit_hash,
        quote_hash=canonical_sha256(intent.quote_material()),
        decided_at=datetime.now(UTC),
    )
    gateway = InstrumentNeutralGateway()
    service = ExecutionService(gateway, authority, Repository(database))  # type: ignore[arg-type]

    order = await service.submit("equity-session", authority.mint(intent, decision))

    assert order.broker_order_id == "equity-order"
    assert gateway.asset_classes == ["equity"]


def test_equity_time_exit_gets_a_separate_reduce_only_warrant(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'equity-exit.db'}")
    database.create()
    authority = WarrantAuthority(tmp_path / "warrant.pem", database)
    intent = ExecutionIntent(
        account_id_hash="a" * 64,
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=uuid4(),
        asset_class="equity",
        symbol="QQQ",
        side="buy",
        quantity=10,
        limit_price=Decimal(100),
        take_profit_price=Decimal("103.4"),
        stop_price=Decimal(99),
        order_class="bracket",
    )
    decision = RiskDecision(
        decision_id=intent.risk_decision_id,
        status="PASS",
        gates=(),
        quantity=10,
        modeled_max_loss=Decimal(11),
        strategy_manifest_hash=intent.strategy_manifest_hash,
        evidence_commit_hash=intent.evidence_commit_hash,
        quote_hash=canonical_sha256(intent.quote_material()),
        decided_at=datetime.now(UTC),
    )
    entry = authority.mint(intent, decision)

    warrant, exit_decision = authorize_equity_position_exit(authority, entry, 7)

    assert exit_decision.status == "PASS"
    assert warrant.intent.side == "sell"
    assert warrant.intent.quantity == 7
    assert warrant.intent.reduce_only is True
    assert authority.verify(warrant)


@pytest.mark.asyncio
async def test_exit_requires_a_fresh_separately_signed_closing_warrant(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite:///{tmp_path / 'exit.db'}")
    database.create()
    authority = WarrantAuthority(tmp_path / "warrant.pem", database)
    intent, decision = intent_and_decision()
    entry_warrant = authority.mint(intent, decision)
    now = intent.legs[0].quote_at
    assessment = await PositionWatchdog(ExitGateway()).assess(
        intent,
        ExitPlan(target_r=3, stop_r=-1, exit_at=now),
        target_profit=0,
        stop_loss=50,
        now=now,
    )

    exit_warrant, exit_decision = authorize_position_exit(authority, entry_warrant, assessment)

    assert exit_decision.status == "PASS"
    assert authority.verify(exit_warrant)
    assert [leg.position_intent for leg in exit_warrant.intent.legs] == [
        "sell_to_close",
        "buy_to_close",
    ]
    assert exit_warrant.intent_hash != entry_warrant.intent_hash
