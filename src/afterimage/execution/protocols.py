from __future__ import annotations

from typing import Any, Protocol

from afterimage.contracts.models import ExecutionIntent


class OrderLookupGateway(Protocol):
    async def order_by_client_id(self, client_order_id: str) -> dict[str, Any]: ...


class ExecutionGateway(OrderLookupGateway, Protocol):
    async def place_order(
        self, intent: ExecutionIntent, client_order_id: str
    ) -> dict[str, Any]: ...

    async def place_option_order(
        self, intent: ExecutionIntent, client_order_id: str
    ) -> dict[str, Any]: ...
