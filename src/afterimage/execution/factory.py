from __future__ import annotations

import json
import os
from pathlib import Path

from .alpaca_gateway import AlpacaGateway, PreflightFailure
from .cli_gateway import AlpacaCLIGateway, SubprocessCLIRunner
from .mcp_client import MCPClient, MCPProcess
from .private_file import PrivateFileInvalid, PrivateFileMissing, read_private_text

PINNED_ALPACA_CLI_SHA256 = "f8181e5e84b15f8846690cdbceda7e2c81e7929cf2bba52ef5b82b730e69400f"


def _env_file_values(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _build_mcp_gateway() -> AlpacaGateway:
    if os.getenv("ALPACA_PAPER_TRADE", "true").lower() != "true":
        raise PreflightFailure("ALPACA_PAPER_TRADE_MUST_BE_TRUE")
    from_file = _env_file_values(os.getenv("AFTERIMAGE_ENV_FILE", ".env"))
    shared = {
        "ALPACA_API_KEY": os.environ.get("ALPACA_API_KEY", from_file.get("ALPACA_API_KEY", "")),
        "ALPACA_SECRET_KEY": os.environ.get(
            "ALPACA_SECRET_KEY", from_file.get("ALPACA_SECRET_KEY", "")
        ),
        "ALPACA_PAPER_TRADE": "true",
    }
    if not shared["ALPACA_API_KEY"] or not shared["ALPACA_SECRET_KEY"]:
        raise PreflightFailure("ALPACA_CREDENTIALS_MISSING")
    server = os.getenv("AFTERIMAGE_ALPACA_MCP_PACKAGE", "alpaca-mcp-server==2.3.1")
    args = (server, "--transport", "stdio")
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
    # MCP remains an optional read/dry-run transport. Production mutation uses
    # the official CLI because it can attest the selected paper endpoint.
    return AlpacaGateway(data, trade, execution_enabled=False)


def build_alpaca_gateway() -> AlpacaGateway | AlpacaCLIGateway:
    transport = os.getenv("AFTERIMAGE_ALPACA_TRANSPORT", "cli").strip().lower()
    if transport == "mcp":
        return _build_mcp_gateway()
    if transport != "cli":
        raise PreflightFailure("UNKNOWN_ALPACA_TRANSPORT")
    if os.getenv("ALPACA_PAPER_TRADE", "true").lower() != "true":
        raise PreflightFailure("ALPACA_PAPER_TRADE_MUST_BE_TRUE")
    executable = os.getenv("AFTERIMAGE_ALPACA_CLI", ".tools/bin/alpaca")
    profile = os.getenv("AFTERIMAGE_ALPACA_PROFILE", "afterimage-paper")
    execution_enabled = os.getenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "false").lower() == "true"
    return AlpacaCLIGateway(
        runner=SubprocessCLIRunner(
            executable,
            profile=profile,
            expected_sha256=os.getenv("AFTERIMAGE_ALPACA_CLI_SHA256", PINNED_ALPACA_CLI_SHA256),
        ),
        account_binding_path=os.getenv(
            "AFTERIMAGE_ACCOUNT_BINDING_PATH", ".afterimage/alpaca-account.sha256"
        ),
        execution_enabled=execution_enabled,
    )


def expected_account_id_hash() -> str:
    binding_path = Path(
        os.getenv("AFTERIMAGE_ACCOUNT_BINDING_PATH", ".afterimage/alpaca-account.sha256")
    )
    try:
        value = read_private_text(binding_path).strip()
    except PrivateFileMissing as exc:
        raise PreflightFailure("ALPACA_ACCOUNT_NOT_BOUND") from exc
    except PrivateFileInvalid as exc:
        raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID") from exc
    try:
        binding = json.loads(value)
    except ValueError as exc:
        raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID") from exc
    if not isinstance(binding, dict):
        raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID")
    account_hash = str(binding.get("account_id_hash", ""))
    endpoint = str(binding.get("trading_endpoint", ""))
    if len(account_hash) != 64 or endpoint != AlpacaCLIGateway.PAPER_TRADING_ENDPOINT:
        raise PreflightFailure("ALPACA_ACCOUNT_BINDING_INVALID")
    return account_hash


def expected_account_id() -> str:
    """Backward-compatible alias; values are hashes, never raw account identifiers."""
    return expected_account_id_hash()
