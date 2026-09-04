from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from afterimage.contracts.models import AccountSnapshot, ExecutionIntent

from .mcp_client import MCPClient


class PreflightFailure(RuntimeError):
    pass


class AccountPreflight(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account: AccountSnapshot
    market_open: bool
    clock: dict[str, Any]
    open_orders: tuple[dict[str, Any], ...]
    positions: tuple[dict[str, Any], ...]
    capabilities: dict[str, str]


class AlpacaGateway:
    DATA_REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {
            "get_option_contracts",
            "get_option_chain",
            "get_option_latest_quote",
            "get_stock_bars",
        }
    )
    TRADE_REQUIRED: ClassVar[frozenset[str]] = frozenset(
        {
            "get_account_info",
            "get_account_config",
            "get_orders",
            "get_order_by_client_id",
            "get_all_positions",
            "get_clock",
            "place_option_order",
            "replace_order_by_id",
            "cancel_order_by_id",
        }
    )

    def __init__(
        self,
        data_client: MCPClient,
        trade_client: MCPClient,
        execution_enabled: bool = False,
    ) -> None:
        self.data_client = data_client
        self.trade_client = trade_client
        self.execution_enabled = execution_enabled

    async def connect(self) -> None:
        await self.data_client.connect()
        await self.trade_client.connect()
        data_names = set(self.data_client.tool_schemas)
        trade_names = set(self.trade_client.tool_schemas)
        missing_data = self.DATA_REQUIRED - data_names
        missing_trade = self.TRADE_REQUIRED - trade_names
        if missing_data or missing_trade:
            raise PreflightFailure(
                f"MCP_CAPABILITY_MISMATCH data={sorted(missing_data)} trade={sorted(missing_trade)}"
            )
        if "place_option_order" in data_names:
            raise PreflightFailure("DATA_PROCESS_HAS_ORDER_AUTHORITY")

    async def close(self) -> None:
        await self.data_client.close()
        await self.trade_client.close()

    @staticmethod
    def _items(payload: dict[str, Any], reason: str) -> tuple[dict[str, Any], ...]:
        matched = [key for key in ("items", "orders", "positions") if key in payload]
        if len(matched) != 1:
            raise PreflightFailure(reason)
        value = payload[matched[0]]
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return tuple(value)
        raise PreflightFailure(reason)

    async def preflight(
        self,
        expected_account_id_hash: str,
        allow_existing_exposure: bool | None = None,
    ) -> AccountPreflight:
        account_payload = await self.trade_client.call("get_account_info")
        config = await self.trade_client.call("get_account_config")
        orders_payload = await self.trade_client.call(
            "get_orders", {"status": "open", "limit": 100}
        )
        positions_payload = await self.trade_client.call("get_all_positions")
        clock = await self.trade_client.call("get_clock")
        account_payload = account_payload.get(
            "account", account_payload.get("data", account_payload)
        )
        config = config.get("configuration", config.get("data", config))
        if not isinstance(account_payload, dict) or not isinstance(config, dict):
            raise PreflightFailure("MALFORMED_ACCOUNT_PREFLIGHT")
        if account_payload.get("last_equity") is None:
            raise PreflightFailure("ACCOUNT_LAST_EQUITY_MISSING")
        account_id = str(account_payload.get("id", account_payload.get("account_id", "")))
        account_id_hash = hashlib.sha256(account_id.encode()).hexdigest()
        if not account_id or account_id_hash != expected_account_id_hash:
            raise PreflightFailure("ACCOUNT_ID_MISMATCH")
        paper = os.getenv("ALPACA_PAPER_TRADE", "true").lower() == "true"
        if not paper:
            raise PreflightFailure("NOT_PAPER")
        approved_value = account_payload.get(
            "options_approved_level", config.get("max_options_trading_level", 0)
        )
        approved = int(approved_value or 0)
        effective = int(account_payload.get("options_trading_level", approved) or approved)
        if min(approved, effective) < 3:
            raise PreflightFailure("OPTIONS_LEVEL_3_REQUIRED")
        if str(account_payload.get("status", "UNKNOWN")).upper() != "ACTIVE":
            raise PreflightFailure("ACCOUNT_INACTIVE")
        if bool(account_payload.get("trading_blocked", config.get("suspend_trade", False))):
            raise PreflightFailure("TRADING_BLOCKED")
        open_orders = self._items(orders_payload, "MALFORMED_OPEN_ORDERS")
        positions = self._items(positions_payload, "MALFORMED_POSITIONS")
        allow_exposure = (
            allow_existing_exposure
            if allow_existing_exposure is not None
            else os.getenv("AFTERIMAGE_ALLOW_EXISTING_PAPER_EXPOSURE", "false").lower() == "true"
        )
        if not allow_exposure and (open_orders or positions):
            raise PreflightFailure(
                f"UNKNOWN_PAPER_EXPOSURE orders={len(open_orders)} positions={len(positions)}"
            )
        account = AccountSnapshot(
            account_id_hash=account_id_hash,
            paper=True,
            status=str(account_payload.get("status", "UNKNOWN")),
            equity=Decimal(str(account_payload.get("equity", "0"))),
            last_equity=Decimal(str(account_payload.get("last_equity", "0"))),
            cash=Decimal(str(account_payload.get("cash", "0"))),
            options_buying_power=Decimal(str(account_payload.get("options_buying_power", "0"))),
            options_approved_level=approved,
            options_trading_level=effective,
            trading_blocked=bool(
                account_payload.get("trading_blocked", config.get("suspend_trade", False))
            ),
            timestamp=datetime.now(UTC),
        )
        capabilities = {
            **self.data_client.tool_schemas,
            **self.trade_client.tool_schemas,
            "execution": "enabled" if self.execution_enabled else "disabled",
            "transport": "alpaca-mcp",
        }
        market_open = bool(clock.get("is_open", clock.get("open", False)))
        return AccountPreflight(
            account=account,
            market_open=market_open,
            clock=clock,
            open_orders=open_orders,
            positions=positions,
            capabilities=capabilities,
        )

    async def stock_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "5Min"
    ) -> list[dict[str, Any]]:
        payload = await self.data_client.call(
            "get_stock_bars",
            {
                "symbol": symbol,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "timeframe": timeframe,
                "feed": os.getenv("AFTERIMAGE_STOCK_FEED", "iex"),
            },
        )
        value: Any = payload.get("bars", payload.get("data", []))
        if isinstance(value, dict):
            value = value.get(symbol, [])
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise PreflightFailure("MALFORMED_STOCK_BARS")
        return value

    async def stock_snapshot(self, symbol: str) -> dict[str, Any]:
        if "get_stock_snapshot" not in self.data_client.tool_schemas:
            raise PreflightFailure("STOCK_SNAPSHOT_UNSUPPORTED_BY_MCP")
        return await self.data_client.call(
            "get_stock_snapshot",
            {"symbol": symbol.upper(), "feed": os.getenv("AFTERIMAGE_STOCK_FEED", "iex")},
        )

    async def option_contracts(self, symbol: str, **arguments: Any) -> list[dict[str, Any]]:
        payload = await self.data_client.call(
            "get_option_contracts", {"underlying_symbols": symbol, **arguments}
        )
        value: Any = payload.get(
            "option_contracts", payload.get("contracts", payload.get("data", []))
        )
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise PreflightFailure("MALFORMED_OPTION_CONTRACTS")
        return value

    async def option_chain(self, symbol: str, **arguments: Any) -> dict[str, Any]:
        return await self.data_client.call(
            "get_option_chain", {"underlying_symbol": symbol, **arguments}
        )

    async def option_quotes(self, **arguments: Any) -> dict[str, Any]:
        return await self.data_client.call("get_option_latest_quote", arguments)

    async def positions(self) -> tuple[dict[str, Any], ...]:
        return self._items(await self.trade_client.call("get_all_positions"), "MALFORMED_POSITIONS")

    async def place_option_order(
        self, intent: ExecutionIntent, client_order_id: str
    ) -> dict[str, Any]:
        if not self.execution_enabled:
            raise PreflightFailure("EXECUTION_DISABLED")
        legs = [
            {
                "symbol": leg.symbol,
                "ratio_qty": str(leg.ratio_qty),
                "side": leg.side,
                "position_intent": leg.position_intent,
            }
            for leg in intent.legs
        ]
        return await self.trade_client.call(
            "place_option_order",
            {
                "qty": str(intent.quantity),
                "type": "limit",
                "limit_price": str(intent.limit_price),
                "time_in_force": "day",
                "order_class": "mleg",
                "client_order_id": client_order_id,
                "legs": legs,
            },
        )

    async def place_order(self, intent: ExecutionIntent, client_order_id: str) -> dict[str, Any]:
        if intent.asset_class == "option":
            return await self.place_option_order(intent, client_order_id)
        if not self.execution_enabled:
            raise PreflightFailure("EXECUTION_DISABLED")
        if "place_stock_order" not in self.trade_client.tool_schemas:
            raise PreflightFailure("EQUITY_EXECUTION_UNSUPPORTED_BY_MCP")
        if intent.reduce_only:
            return await self.trade_client.call(
                "place_stock_order",
                {
                    "symbol": intent.symbol,
                    "qty": str(intent.quantity),
                    "side": intent.side,
                    "type": "market",
                    "time_in_force": "day",
                    "client_order_id": client_order_id,
                },
            )
        return await self.trade_client.call(
            "place_stock_order",
            {
                "symbol": intent.symbol,
                "qty": str(intent.quantity),
                "side": intent.side,
                "type": "limit",
                "limit_price": str(intent.limit_price),
                "time_in_force": "day",
                "order_class": "bracket",
                "take_profit": {"limit_price": str(intent.take_profit_price)},
                "stop_loss": {"stop_price": str(intent.stop_price)},
                "client_order_id": client_order_id,
            },
        )

    async def dry_run_option_order(
        self, intent: ExecutionIntent, client_order_id: str
    ) -> dict[str, Any]:
        """Construct the exact MCP request without invoking a mutation tool."""
        return {
            "dry_run": True,
            "transport": "alpaca-mcp-local-validation",
            "client_order_id": client_order_id,
            "order_class": intent.order_class,
            "type": intent.order_type,
            "time_in_force": intent.time_in_force,
            "qty": str(intent.quantity),
            "limit_price": str(intent.limit_price),
            "legs": [
                {
                    "symbol": leg.symbol,
                    "ratio_qty": str(leg.ratio_qty),
                    "side": leg.side,
                    "position_intent": leg.position_intent,
                }
                for leg in intent.legs
            ],
        }

    async def dry_run_order(self, intent: ExecutionIntent, client_order_id: str) -> dict[str, Any]:
        if intent.asset_class == "option":
            return await self.dry_run_option_order(intent, client_order_id)
        return {
            "dry_run": True,
            "transport": "alpaca-mcp-local-validation",
            "client_order_id": client_order_id,
            "asset_class": "equity",
            "symbol": intent.symbol,
            "side": intent.side,
            "order_class": "bracket",
            "type": intent.order_type,
            "time_in_force": intent.time_in_force,
            "qty": str(intent.quantity),
            "limit_price": str(intent.limit_price),
            "take_profit": {"limit_price": str(intent.take_profit_price)},
            "stop_loss": {"stop_price": str(intent.stop_price)},
        }

    async def order_by_client_id(self, client_order_id: str) -> dict[str, Any]:
        return await self.trade_client.call(
            "get_order_by_client_id", {"client_order_id": client_order_id}
        )

    async def replace_order(self, order_id: str, limit_price: Decimal) -> dict[str, Any]:
        if not self.execution_enabled:
            raise PreflightFailure("EXECUTION_DISABLED")
        return await self.trade_client.call(
            "replace_order_by_id", {"order_id": order_id, "limit_price": str(limit_price)}
        )

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        if not self.execution_enabled:
            raise PreflightFailure("EXECUTION_DISABLED")
        return await self.trade_client.call("cancel_order_by_id", {"order_id": order_id})
