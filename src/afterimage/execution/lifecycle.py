from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from afterimage.contracts.enums import DecisionStatus
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import (
    BrokerOrder,
    ExecutionIntent,
    ExecutionWarrant,
    RiskDecision,
    RiskGate,
)
from afterimage.risk.warrant import WarrantAuthority
from afterimage.storage import Repository

from .client_ids import client_order_id
from .protocols import ExecutionGateway
from .reconciler import Reconciler
from .watchdog import WatchdogAction, WatchdogAssessment


class ExecutionError(RuntimeError):
    pass


class AmbiguousSubmission(ExecutionError):
    pass


class ExecutionService:
    def __init__(
        self,
        gateway: ExecutionGateway,
        authority: WarrantAuthority,
        repository: Repository,
    ) -> None:
        self.gateway = gateway
        self.authority = authority
        self.repository = repository
        self.reconciler = Reconciler(gateway)

    async def submit(self, session_id: str, warrant: ExecutionWarrant) -> BrokerOrder:
        if not self.authority.verify(warrant):
            raise ExecutionError("WARRANT_INVALID")
        consumed = self.authority.consume(warrant)
        cid = client_order_id(session_id, consumed.intent_hash)
        self.repository.save_broker_order(
            session_id,
            {
                "id": f"pending:{canonical_sha256(cid)[:32]}",
                "client_order_id": cid,
                "status": "submitting",
                "submission_observed": False,
            },
            consumed.intent_hash,
        )
        try:
            place_order = getattr(self.gateway, "place_order", None)
            if callable(place_order):
                raw = await place_order(consumed.intent, cid)
            elif consumed.intent.asset_class == "option":
                raw = await self.gateway.place_option_order(consumed.intent, cid)
            else:
                raise ExecutionError("EQUITY_EXECUTION_UNSUPPORTED_BY_GATEWAY")
        except RuntimeError:
            reconciled = await self.reconciler.by_client_id(cid)
            if reconciled.order is None:
                raise AmbiguousSubmission("AMBIGUOUS_SUBMISSION")
            raw = reconciled.order
        broker_id = str(raw.get("id", raw.get("order_id", "")))
        if not broker_id:
            raise ExecutionError("BROKER_ORDER_ID_MISSING")
        order = BrokerOrder(
            broker_order_id=broker_id,
            client_order_id=cid,
            status=str(raw.get("status", "unknown")),
            intent_hash=consumed.intent_hash,
            submitted_at=datetime.now(UTC),
            raw_hash=canonical_sha256(raw),
        )
        self.repository.save_broker_order(
            session_id,
            {
                **raw,
                "id": broker_id,
                "client_order_id": cid,
                "submission_observed": True,
            },
            consumed.intent_hash,
        )
        return order


EXIT_ACTIONS = {
    WatchdogAction.EXIT_TARGET,
    WatchdogAction.EXIT_STOP,
    WatchdogAction.EXIT_TIME,
}


def authorize_equity_position_exit(
    authority: WarrantAuthority,
    entry_warrant: ExecutionWarrant,
    quantity: int,
) -> tuple[ExecutionWarrant, RiskDecision]:
    """Authorize an exact market close for a currently observed equity position."""
    entry = entry_warrant.intent
    if (
        entry.asset_class != "equity"
        or entry.symbol is None
        or entry.side is None
        or quantity < 1
        or quantity > entry.quantity
    ):
        raise ExecutionError("EQUITY_EXIT_POSITION_INVALID")
    intent = ExecutionIntent(
        account_id_hash=entry.account_id_hash,
        strategy_manifest_hash=entry.strategy_manifest_hash,
        evidence_commit_hash=entry.evidence_commit_hash,
        risk_decision_id=uuid4(),
        asset_class="equity",
        symbol=entry.symbol,
        side="sell" if entry.side == "buy" else "buy",
        quantity=quantity,
        limit_price=0,
        order_class="simple",
        order_type="market",
        reduce_only=True,
    )
    quote_hash = canonical_sha256(intent.quote_material())
    decision = RiskDecision(
        decision_id=intent.risk_decision_id,
        status=DecisionStatus.PASS,
        gates=(
            RiskGate(
                name="risk_reducing_equity_exit",
                passed=True,
                observed=f"{intent.side} {quantity} {intent.symbol}",
                required="exact observed position close",
            ),
        ),
        quantity=quantity,
        modeled_max_loss=0,
        strategy_manifest_hash=entry.strategy_manifest_hash,
        evidence_commit_hash=entry.evidence_commit_hash,
        quote_hash=quote_hash,
        decided_at=datetime.now(UTC),
    )
    return authority.mint(intent, decision), decision


def authorize_position_exit(
    authority: WarrantAuthority,
    entry_warrant: ExecutionWarrant,
    assessment: WatchdogAssessment,
    quantity: int | None = None,
) -> tuple[ExecutionWarrant, RiskDecision]:
    """Mint a separately signed, short-lived warrant for an exact risk-reducing close."""
    if assessment.action not in EXIT_ACTIONS:
        raise ExecutionError("EXIT_ACTION_NOT_AUTHORIZED")
    if not assessment.position_matches or not assessment.exit_legs:
        raise ExecutionError("EXIT_POSITION_OR_QUOTES_INVALID")
    quote_hash = canonical_sha256([leg.model_dump(mode="json") for leg in assessment.exit_legs])
    decision = RiskDecision(
        status=DecisionStatus.PASS,
        gates=(
            RiskGate(
                name="risk_reducing_exit",
                passed=True,
                observed=assessment.action.value,
                required="EXIT_TARGET|EXIT_STOP|EXIT_TIME",
            ),
            RiskGate(
                name="position_match",
                passed=True,
                observed="True",
                required="True",
            ),
        ),
        quantity=quantity or entry_warrant.intent.quantity,
        modeled_max_loss=0,
        strategy_manifest_hash=entry_warrant.intent.strategy_manifest_hash,
        evidence_commit_hash=entry_warrant.intent.evidence_commit_hash,
        quote_hash=quote_hash,
        decided_at=assessment.observed_at,
    )
    intent = ExecutionIntent(
        account_id_hash=entry_warrant.intent.account_id_hash,
        strategy_manifest_hash=entry_warrant.intent.strategy_manifest_hash,
        evidence_commit_hash=entry_warrant.intent.evidence_commit_hash,
        risk_decision_id=decision.decision_id,
        legs=assessment.exit_legs,
        quantity=quantity or entry_warrant.intent.quantity,
        limit_price=assessment.exit_limit_price,
    )
    return authority.mint(intent, decision), decision
