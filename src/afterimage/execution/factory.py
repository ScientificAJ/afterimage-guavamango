from __future__ import annotations

import os

from .alpaca_gateway import AlpacaGateway, PreflightFailure
from .mcp_client import MCPClient, MCPProcess


def build_alpaca_gateway() -> AlpacaGateway:
    if os.getenv("ALPACA_PAPER_TRADE", "true").lower() != "true":
        raise PreflightFailure("ALPACA_PAPER_TRADE_MUST_BE_TRUE")
    shared = {
        "ALPACA_API_KEY": os.environ.get("ALPACA_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.environ.get("ALPACA_SECRET_KEY", ""),
        "ALPACA_PAPER_TRADE": "true",
    }
    if not shared["ALPACA_API_KEY"] or not shared["ALPACA_SECRET_KEY"]:
        raise PreflightFailure("ALPACA_CREDENTIALS_MISSING")
    server = os.getenv("AFTERIMAGE_ALPACA_MCP_PACKAGE", "alpaca-mcp-server==2.3.1")
    args = (server, "--transport", "stdio", "--env-file", os.getenv("AFTERIMAGE_ENV_FILE", ".env"))
    data = MCPClient(
        MCPProcess(
            command=os.getenv("AFTERIMAGE_UVX", "uvx"),
            args=args,
            env={**shared, "ALPACA_TOOLSETS": "assets,stock-data,options-data"},
        )
    )
    trade = MCPClient(
        MCPProcess(
            command=os.getenv("AFTERIMAGE_UVX", "uvx"),
            args=args,
            env={**shared, "ALPACA_TOOLSETS": "account,trading,assets"},
        )
    )
    return AlpacaGateway(data, trade)


def expected_account_id() -> str:
    value = os.getenv("ALPACA_EXPECTED_ACCOUNT_ID", "").strip()
    if not value:
        raise PreflightFailure("ALPACA_EXPECTED_ACCOUNT_ID_MISSING")
    return value
