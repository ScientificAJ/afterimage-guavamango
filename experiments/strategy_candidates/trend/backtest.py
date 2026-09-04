#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from strategy import (
    build_dry_run_order,
    candidate_decision,
    run_experiment,
    validate_option_signals,
)

from afterimage.execution import build_alpaca_gateway, expected_account_id_hash


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def _attach_real_options(
    results: dict[str, Any], scope: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    gateway = build_alpaca_gateway()
    try:
        await gateway.connect()
        preflight = await gateway.preflight(expected_account_id_hash())
        account = preflight.account
        results["alpaca_read_only_preflight"] = {
            "paper": account.paper,
            "status": account.status,
            "equity": str(account.equity),
            "cash": str(account.cash),
            "options_buying_power": str(account.options_buying_power),
            "options_approved_level": account.options_approved_level,
            "options_trading_level": account.options_trading_level,
            "open_orders": len(preflight.open_orders),
            "positions": len(preflight.positions),
            "execution": preflight.capabilities.get("execution", "disabled"),
            "transport": preflight.capabilities.get("transport", "unknown"),
        }
        if scope == "all":
            results["training_option_validation"] = await validate_option_signals(
                gateway, results["training"]["signals"]
            )
        results["oos_option_validation"] = await validate_option_signals(
            gateway, results["oos"]["signals"]
        )
    finally:
        await gateway.close()

    oos_results = results["oos_option_validation"]["results"]
    if not oos_results:
        return results, None
    example = oos_results[0]
    order_payload = build_dry_run_order(
        direction=example["direction"],
        long_symbol=example["long_symbol"],
        short_symbol=example["short_symbol"],
        quantity=1,
        limit_price=example["entry_debit"],
        client_order_id=f"afterimage-trend-historical-{example['session_date'].replace('-', '')}",
    )
    order_payload["historical_example_only"] = True
    order_payload["contract_status"] = "inactive_after_expiration"
    order_payload["submission_forbidden"] = True
    return results, order_payload


def _selected_folds(results: dict[str, Any]) -> list[dict[str, Any]]:
    selected_id = results["selection"]["selected_variant_id"]
    return next(
        row["walk_forward_folds"] for row in results["variants"] if row["variant_id"] == selected_id
    )


async def execute(
    dataset_path: Path,
    output_path: Path,
    order_payload_path: Path,
    option_scope: str,
) -> dict[str, Any]:
    dataset_bytes = dataset_path.read_bytes()
    dataset = json.loads(dataset_bytes)
    results = run_experiment(dataset)
    results["source_dataset"] = {
        "path": str(dataset_path),
        "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "embedded_dataset_hash": dataset.get("dataset_hash"),
        "provider": dataset.get("source"),
        "feed": dataset.get("feed"),
        "timeframe": dataset.get("timeframe"),
        "training_range": [dataset["training"]["start"], dataset["training"]["end"]],
        "embargo_sessions": dataset.get("embargo_sessions"),
        "holdout_range": [dataset["holdout"]["start"], dataset["holdout"]["end"]],
    }
    order_payload: dict[str, Any] | None = None
    if option_scope != "none":
        results, order_payload = await _attach_real_options(results, option_scope)
    else:
        results["oos_option_validation"] = {
            "sample_count": 0,
            "expectancy_r": 0.0,
            "coverage_rate": 0.0,
            "not_run": True,
        }
    results["candidate_decision"] = candidate_decision(
        training_proxy=results["training"],
        walk_forward_folds=_selected_folds(results),
        oos_options=results["oos_option_validation"],
    )
    results["holdout_protocol"] = {
        "selection_uses_holdout": False,
        "parameters_frozen_before_oos": True,
        "oos_reused_for_iteration": False,
        "note": "The runner is reproducible, but this research pass did not revise parameters after observing OOS.",
    }
    canonical = json.dumps(results, sort_keys=True, separators=(",", ":"))
    results["results_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    _write_json(output_path, results)
    if order_payload is not None:
        _write_json(order_payload_path, order_payload)
    return results


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Walk-forward SPY trend-family research with optional read-only Alpaca option validation."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(".afterimage/research/spy-real-v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/strategy_candidates/trend/results.json"),
    )
    parser.add_argument(
        "--order-payload",
        type=Path,
        default=Path("experiments/strategy_candidates/trend/order-payload.json"),
    )
    parser.add_argument(
        "--option-scope",
        choices=("none", "oos", "all"),
        default="none",
        help="Read-only historical option queries; 'all' validates selected training and OOS signals.",
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    args = parse_args(arguments)
    results = asyncio.run(execute(args.dataset, args.output, args.order_payload, args.option_scope))
    summary = {
        "selected_variant_id": results["selection"]["selected_variant_id"],
        "training": {
            key: results["training"][key]
            for key in (
                "sample_count",
                "net_pnl_dollars",
                "expectancy_r",
                "hit_rate",
                "max_drawdown_dollars",
            )
        },
        "oos": {
            key: results["oos"][key]
            for key in (
                "sample_count",
                "net_pnl_dollars",
                "expectancy_r",
                "hit_rate",
                "max_drawdown_dollars",
            )
        },
        "oos_options": results["oos_option_validation"],
        "candidate_decision": results["candidate_decision"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
