#!/usr/bin/env python3
"""Build and invoke an official Alpaca CLI MLEG dry run; never submit an order."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from acquire import canonical_hash


def build_entry_payload(
    *, short_symbol: str, long_symbol: str, credit: Decimal, client_order_id: str
) -> dict[str, Any]:
    if not short_symbol or not long_symbol or short_symbol == long_symbol:
        raise ValueError("TWO_DISTINCT_OPTION_SYMBOLS_REQUIRED")
    if not credit.is_finite() or credit <= 0:
        raise ValueError("POSITIVE_CREDIT_REQUIRED")
    normalized_credit = credit.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return {
        "client_order_id": client_order_id,
        "order_class": "mleg",
        "qty": "1",
        "type": "limit",
        "limit_price": str(-normalized_credit),
        "time_in_force": "day",
        "legs": [
            {
                "symbol": short_symbol,
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
            {
                "symbol": long_symbol,
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
        ],
    }


def build_cli_arguments(payload: dict[str, Any]) -> list[str]:
    return [
        "order",
        "submit",
        "--qty",
        str(payload["qty"]),
        "--type",
        str(payload["type"]),
        "--limit-price",
        str(payload["limit_price"]),
        "--time-in-force",
        str(payload["time_in_force"]),
        "--order-class",
        str(payload["order_class"]),
        "--client-order-id",
        str(payload["client_order_id"]),
        "--legs",
        json.dumps(payload["legs"], separators=(",", ":")),
        "--dry-run",
    ]


def validate_dry_run_arguments(arguments: Sequence[str]) -> None:
    values = tuple(arguments)
    if values[:2] != ("order", "submit") or values[-1:] != ("--dry-run",):
        raise ValueError("DRY_RUN_FLAG_REQUIRED")
    if values.count("--dry-run") != 1:
        raise ValueError("DRY_RUN_FLAG_REQUIRED")


def public_account_capabilities(
    account: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
    approved = int(
        account.get("options_approved_level", configuration.get("max_options_trading_level", 0))
        or 0
    )
    effective = int(account.get("options_trading_level", approved) or approved)
    blocked = bool(account.get("trading_blocked", configuration.get("suspend_trade", False)))
    status = str(account.get("status", "UNKNOWN"))
    return {
        "paper": True,
        "status": status,
        "options_approved_level": approved,
        "options_trading_level": effective,
        "trading_blocked": blocked,
        "level_3_eligible": status == "ACTIVE" and min(approved, effective) >= 3 and not blocked,
    }


def _run_json(
    executable: Path, profile: str, arguments: Sequence[str], *, dry_run: bool = False
) -> dict[str, Any]:
    if dry_run:
        validate_dry_run_arguments(arguments)
    elif tuple(arguments[:2]) not in {
        ("account", "get"),
        ("account", "config"),
        ("data", "option"),
    }:
        raise ValueError("UNAPPROVED_DRY_RUN_SUPPORT_COMMAND")
    command = [str(executable), "--profile", profile, *arguments]
    if not dry_run:
        command.append("--quiet")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ALPACA_CLI_COMMAND_FAILED:{' '.join(arguments[:2])}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ALPACA_CLI_NON_JSON_RESPONSE") from exc
    if not isinstance(result, dict):
        raise TypeError("ALPACA_CLI_OBJECT_REQUIRED")
    return result


def create_artifact(
    *,
    executable: Path,
    profile: str,
    short_symbol: str,
    long_symbol: str,
    client_order_id: str,
    output: Path,
) -> dict[str, Any]:
    account = _run_json(executable, profile, ("account", "get"))
    configuration = _run_json(executable, profile, ("account", "config", "get"))
    capabilities = public_account_capabilities(account, configuration)
    if not capabilities["level_3_eligible"]:
        raise RuntimeError("PAPER_ACCOUNT_LEVEL_3_REQUIRED")
    quotes_payload = _run_json(
        executable,
        profile,
        ("data", "option", "latest-quotes", "--symbols", f"{short_symbol},{long_symbol}"),
    )
    quotes = quotes_payload.get("quotes", {})
    try:
        short_quote = quotes[short_symbol]
        long_quote = quotes[long_symbol]
        short_bid = Decimal(str(short_quote["bp"]))
        long_ask = Decimal(str(long_quote["ap"]))
        quote_credit = (short_bid - long_ask).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise RuntimeError("LIVE_OPTION_QUOTE_MALFORMED") from exc
    payload = build_entry_payload(
        short_symbol=short_symbol,
        long_symbol=long_symbol,
        credit=quote_credit,
        client_order_id=client_order_id,
    )
    arguments = build_cli_arguments(payload)
    response = _run_json(executable, profile, arguments, dry_run=True)
    body = {
        "schema_version": "afterimage-volatility-premium-alpaca-dry-run-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "transport": "official Alpaca CLI 0.0.14",
        "paper_endpoint": "https://paper-api.alpaca.markets",
        "account_capabilities": capabilities,
        "live_quote_inputs": {
            "short_symbol": short_symbol,
            "short_bid": str(short_bid),
            "short_quote_at": str(short_quote.get("t", "")),
            "long_symbol": long_symbol,
            "long_ask": str(long_ask),
            "long_quote_at": str(long_quote.get("t", "")),
            "net_credit": str(quote_credit),
        },
        "request_payload": payload,
        "cli_arguments": arguments,
        "cli_response": response,
        "submitted": False,
        "validation_scope": "client-side CLI request serialization only; no POST was sent",
        "official_reference": "https://docs.alpaca.markets/us/reference/postorder",
    }
    artifact = {**body, "artifact_hash": canonical_hash(body)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short-symbol", required=True)
    parser.add_argument("--long-symbol", required=True)
    parser.add_argument("--client-order-id", default="aft-vrp-20260904-dry-run")
    parser.add_argument(
        "--output", type=Path, default=root / "results" / "alpaca_mleg_dry_run.json"
    )
    parser.add_argument("--alpaca-cli", type=Path, default=Path(".tools/bin/alpaca"))
    parser.add_argument("--profile", default="afterimage-paper")
    args = parser.parse_args()
    artifact = create_artifact(
        executable=args.alpaca_cli,
        profile=args.profile,
        short_symbol=args.short_symbol,
        long_symbol=args.long_symbol,
        client_order_id=args.client_order_id,
        output=args.output,
    )
    print(
        json.dumps(
            {
                "artifact_hash": artifact["artifact_hash"],
                "submitted": False,
                "request_payload": artifact["request_payload"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
