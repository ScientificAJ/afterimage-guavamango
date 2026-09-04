from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .protocols import OrderLookupGateway


@dataclass(frozen=True)
class ReconciliationResult:
    status: str
    order: dict[str, Any] | None
    attempts: int


class Reconciler:
    def __init__(self, gateway: OrderLookupGateway) -> None:
        self.gateway = gateway

    async def by_client_id(
        self, client_order_id: str, attempts: int = 4, delay_seconds: float = 0.25
    ) -> ReconciliationResult:
        for attempt in range(1, attempts + 1):
            try:
                order = await self.gateway.order_by_client_id(client_order_id)
                if order:
                    return ReconciliationResult(str(order.get("status", "unknown")), order, attempt)
            except RuntimeError:
                pass
            if attempt < attempts:
                await asyncio.sleep(delay_seconds)
        return ReconciliationResult("ambiguous", None, attempts)
