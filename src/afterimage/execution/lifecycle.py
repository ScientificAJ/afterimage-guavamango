from __future__ import annotations

from datetime import UTC, datetime

from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import BrokerOrder, ExecutionWarrant
from afterimage.risk.warrant import WarrantAuthority
from afterimage.storage import Repository

from .alpaca_gateway import AlpacaGateway
from .client_ids import client_order_id
from .reconciler import Reconciler


class ExecutionError(RuntimeError):
    pass


class ExecutionService:
    def __init__(
        self,
        gateway: AlpacaGateway,
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
        try:
            raw = await self.gateway.place_option_order(consumed.intent, cid)
        except RuntimeError:
            reconciled = await self.reconciler.by_client_id(cid)
            if reconciled.order is None:
                raise ExecutionError("AMBIGUOUS_SUBMISSION")
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
            session_id, {**raw, "id": broker_id, "client_order_id": cid}, consumed.intent_hash
        )
        return order
