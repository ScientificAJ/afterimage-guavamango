#!/usr/bin/env python3
"""Create an exact official Alpaca CLI MLEG dry run; never submit."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Sequence

try:
    from .candidate import Costs, target_stop_levels
    from .run_research import BACKTEST, PROFILE, REPO, assert_read_only_arguments, canonical_hash
except ImportError:
    from candidate import Costs, target_stop_levels  # type: ignore[no-redef]
    from run_research import BACKTEST, PROFILE, REPO, assert_read_only_arguments, canonical_hash  # type: ignore[no-redef]


OUTPUT = Path(__file__).resolve().parent / "results" / "alpaca_mleg_dry_run.json"


def build_debit_payload(
    *, long_symbol: str, short_symbol: str, debit: Decimal, client_order_id: str
) -> dict[str, Any]:
    if not long_symbol or not short_symbol or long_symbol == short_symbol:
        raise ValueError("TWO_DISTINCT_OPTION_SYMBOLS_REQUIRED")
    if not debit.is_finite() or debit <= 0:
        raise ValueError("POSITIVE_DEBIT_REQUIRED")
    normalized = debit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "client_order_id": client_order_id,
        "order_class": "mleg",
        "qty": "1",
        "type": "limit",
        "limit_price": str(normalized),
        "time_in_force": "day",
        "legs": [
            {
                "symbol": long_symbol,
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": short_symbol,
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ],
    }


def build_cli_arguments(payload: dict[str, Any]) -> list[str]:
    return [
        "order", "submit",
        "--qty", str(payload["qty"]),
        "--type", str(payload["type"]),
        "--limit-price", str(payload["limit_price"]),
        "--time-in-force", str(payload["time_in_force"]),
        "--order-class", str(payload["order_class"]),
        "--client-order-id", str(payload["client_order_id"]),
        "--legs", json.dumps(payload["legs"], separators=(",", ":")),
        "--dry-run",
    ]


def validate_dry_run_arguments(arguments: Sequence[str]) -> None:
    values = tuple(arguments)
    if values[:2] != ("order", "submit") or values[-1:] != ("--dry-run",):
        raise ValueError("TERMINAL_DRY_RUN_FLAG_REQUIRED")
    if values.count("--dry-run") != 1:
        raise ValueError("EXACTLY_ONE_DRY_RUN_FLAG_REQUIRED")


def public_account_capabilities(
    account: dict[str, Any], configuration: dict[str, Any]
) -> dict[str, Any]:
    approved = int(account.get("options_approved_level", configuration.get("max_options_trading_level", 0)) or 0)
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
    executable: Path,
    profile: str,
    arguments: Sequence[str],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        validate_dry_run_arguments(arguments)
    else:
        assert_read_only_arguments(arguments)
    command = [str(executable), "--profile", profile, *arguments]
    if not dry_run:
        command.append("--quiet")
    completed = subprocess.run(
        command,
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ALPACA_CLI_COMMAND_FAILED:{' '.join(arguments[:2])}:{completed.stderr.strip()}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ALPACA_CLI_NON_JSON_RESPONSE") from exc
    if not isinstance(result, dict):
        raise RuntimeError("ALPACA_CLI_OBJECT_REQUIRED")
    return result


def _historical_example(backtest: dict[str, Any]) -> tuple[str, str, str]:
    selected = str(backtest.get("frozen_candidate", {}).get("variant") or "")
    selected_rows = backtest.get("untouched_oos", {}).get("trades") or []
    candidates = [(str(row.get("session", "")), row, selected) for row in selected_rows if selected.endswith("_3r")]
    for name, result in backtest.get("variants", {}).items():
        if not name.endswith("_3r"):
            continue
        rows = result.get("untouched_oos_trades") or []
        candidates.extend((str(row.get("session", "")), row, str(name)) for row in rows)
    if candidates:
        _, row, name = sorted(candidates, key=lambda item: (item[0], item[2]))[-1]
        return str(row["long_symbol"]), str(row["short_symbol"]), name
    raise RuntimeError("NO_HISTORICAL_THREE_R_VERTICAL_FOR_DRY_RUN")


def create_artifact(
    *,
    executable: Path,
    profile: str,
    backtest_path: Path,
    output: Path,
    client_order_id: str,
) -> dict[str, Any]:
    backtest = json.loads(backtest_path.read_text(encoding="utf-8"))
    long_symbol, short_symbol, variant = _historical_example(backtest)
    account = _run_json(executable, profile, ("account", "get"))
    configuration = _run_json(executable, profile, ("account", "config", "get"))
    capabilities = public_account_capabilities(account, configuration)
    if not capabilities["level_3_eligible"]:
        raise RuntimeError("PAPER_ACCOUNT_LEVEL_3_REQUIRED")
    quote_payload = _run_json(
        executable,
        profile,
        ("data", "option", "latest-quotes", "--symbols", f"{long_symbol},{short_symbol}"),
    )
    try:
        quotes = quote_payload["quotes"]
        long_quote = quotes[long_symbol]
        short_quote = quotes[short_symbol]
        long_ask = Decimal(str(long_quote["ap"]))
        short_bid = Decimal(str(short_quote["bp"]))
        debit = (long_ask - short_bid).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise RuntimeError("LIVE_OPTION_QUOTE_MALFORMED") from exc
    if debit <= 0:
        raise RuntimeError("LIVE_VERTICAL_DEBIT_NOT_POSITIVE")
    payload = build_debit_payload(
        long_symbol=long_symbol,
        short_symbol=short_symbol,
        debit=debit,
        client_order_id=client_order_id,
    )
    arguments = build_cli_arguments(payload)
    response = _run_json(executable, profile, arguments, dry_run=True)
    stop_credit, target_credit = target_stop_levels(debit, Costs(Decimal("0.03"), Decimal("0.65")))
    stop_net = (stop_credit - debit) * Decimal(100) - Decimal("2.60")
    target_net = (target_credit - debit) * Decimal(100) - Decimal("2.60")
    body = {
        "schema_version": "afterimage-cross-asset-alpaca-mleg-dry-run-v1",
        "created_at": datetime.now().astimezone().isoformat(),
        "transport": "official Alpaca CLI 0.0.14",
        "paper_endpoint": "https://paper-api.alpaca.markets",
        "source_variant": variant,
        "account_capabilities": capabilities,
        "live_quote_inputs": {
            "long_symbol": long_symbol,
            "long_ask": str(long_ask),
            "long_quote_at": str(long_quote.get("t", "")),
            "short_symbol": short_symbol,
            "short_bid": str(short_bid),
            "short_quote_at": str(short_quote.get("t", "")),
            "net_debit": str(debit),
        },
        "exit_contract": {
            "stop_credit": str(stop_credit),
            "target_credit": str(target_credit),
            "net_stop_dollars": str(stop_net),
            "net_target_dollars": str(target_net),
            "target_to_stop_ratio": str(target_net / abs(stop_net)),
            "fees_and_slippage_included": True,
        },
        "request_payload": payload,
        "cli_arguments": arguments,
        "cli_response": response,
        "submitted": False,
        "validation_scope": "client-side official CLI request serialization only; --dry-run prevented POST",
        "official_reference": "https://docs.alpaca.markets/us/reference/postorder",
    }
    artifact = {**body, "artifact_hash": canonical_hash(body)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpaca-cli", type=Path, default=REPO / ".tools" / "bin" / "alpaca")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--backtest", type=Path, default=BACKTEST)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--client-order-id", default="aft-cross-asset-20260904-dry-run")
    arguments = parser.parse_args()
    artifact = create_artifact(
        executable=arguments.alpaca_cli,
        profile=arguments.profile,
        backtest_path=arguments.backtest,
        output=arguments.output,
        client_order_id=arguments.client_order_id,
    )
    print(json.dumps({"artifact_hash": artifact["artifact_hash"], "submitted": False, "request_payload": artifact["request_payload"]}, sort_keys=True))


if __name__ == "__main__":
    main()
