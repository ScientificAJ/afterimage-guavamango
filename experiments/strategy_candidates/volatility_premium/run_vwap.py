#!/usr/bin/env python3
"""Run the final causal, liquidity-screened VWAP reversal sensitivity."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from acquire import canonical_hash
from candidate import DataExclusion
from ledger import verify_ledger
from pivots import MOMENTUM_FAMILIES, PivotTrade
from run_pivots import _record_attempt, _write_attempt, build_attempt_result
from vwap import VwapOptionBar, simulate_causal_vwap_long

ET = ZoneInfo("America/New_York")


def _bar(raw: dict[str, Any]) -> VwapOptionBar:
    return VwapOptionBar(
        symbol=str(raw["symbol"]),
        timestamp=datetime.fromisoformat(str(raw["t"])),
        close=Decimal(str(raw["c"])),
        vwap=Decimal(str(raw["vw"])),
        volume=int(raw.get("v", 0)),
        trade_count=int(raw.get("n", 0)),
    )


def evaluate(
    cache: dict[str, Any],
) -> tuple[
    dict[str, tuple[PivotTrade, ...]],
    dict[str, tuple[dict[str, Any], ...]],
]:
    bars: dict[str, dict[datetime, VwapOptionBar]] = defaultdict(dict)
    for raw in cache["option_bars"]:
        try:
            parsed = _bar(raw)
        except (KeyError, TypeError, ValueError, ArithmeticError, DataExclusion):
            continue
        bars[parsed.symbol][parsed.timestamp] = parsed
    family_lookup = {item.name: item for item in MOMENTUM_FAMILIES}
    trades: dict[str, list[PivotTrade]] = {name: [] for name in family_lookup}
    exclusions: dict[str, list[dict[str, Any]]] = {name: [] for name in family_lookup}
    for selection in cache["selections"]:
        family_name = str(selection["family"])
        family = family_lookup[family_name]
        symbol = str(selection["symbol"])
        session_date = date.fromisoformat(str(selection["session_date"]))
        option_symbol = str(selection["legs"]["long"])
        start = datetime.combine(session_date, time(10), ET)
        end = datetime.combine(session_date, time(15, 40), ET)
        timestamps = sorted(
            timestamp
            for timestamp in bars[option_symbol]
            if start <= timestamp.astimezone(ET) <= end
        )
        try:
            trade = simulate_causal_vwap_long(
                session_date=session_date.isoformat(),
                symbol=symbol,
                family=family,
                direction=selection["direction"],  # type: ignore[arg-type]
                bars=tuple(bars[option_symbol][timestamp] for timestamp in timestamps),
            )
            trades[family_name].append(trade)
        except (DataExclusion, ArithmeticError, KeyError, ValueError) as exc:
            exclusions[family_name].append(
                {
                    "strategy": "causal_vwap_long_reversal",
                    "family": family_name,
                    "symbol": symbol,
                    "session_date": session_date.isoformat(),
                    "reason": str(exc),
                }
            )
    return (
        {family: tuple(rows) for family, rows in trades.items()},
        {family: tuple(rows) for family, rows in exclusions.items()},
    )


def run(cache_path: Path, output_path: Path, ledger_path: Path) -> dict[str, Any]:
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_body = {key: value for key, value in cache.items() if key != "content_hash"}
    if canonical_hash(cache_body) != cache.get("content_hash"):
        raise RuntimeError("REVERSAL_CACHE_HASH_MISMATCH")
    trades, exclusions = evaluate(cache)
    result = build_attempt_result(
        strategy="causal_vwap_long_reversal",
        trades_by_family=trades,
        exclusions=exclusions,
        source_hash=cache["content_hash"],
        fixed_family="momentum_fast",
    )
    result_body = {key: value for key, value in result.items() if key != "result_hash"}
    result_body["evaluation_label"] = (
        "researcher-visible fixed-fast monthly sensitivity; not untouched"
    )
    result_body["pricing_model"] = {
        "basis": "volume-screened 5-minute option trade VWAP; causal next-liquid-bar exit",
        "quotes_used": False,
        "minimum_entry_and_exit_volume": 10,
        "minimum_entry_and_exit_trade_count": 5,
        "slippage_per_contract_side": "0.02",
        "fee_per_contract_side": "0.03",
        "warning": "trade VWAP is not a historical bid/ask quote or guaranteed fill",
    }
    result = {**result_body, "result_hash": canonical_hash(result_body)}
    sha256 = _write_attempt(output_path, result)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not verify_ledger(ledger):
        raise RuntimeError("ATTEMPT_LEDGER_INVALID")
    ledger = _record_attempt(
        ledger,
        attempt_id="attempt-09-causal-vwap-reversal",
        artifact_path="results/attempt-09-causal-vwap-reversal.json",
        artifact_sha256=sha256,
        result=result,
    )
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=root / "data" / "reversal_cache.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "results" / "attempt-09-causal-vwap-reversal.json",
    )
    parser.add_argument("--ledger", type=Path, default=root / "results" / "attempt-ledger.json")
    args = parser.parse_args()
    result = run(args.cache, args.output, args.ledger)
    print(
        json.dumps({"verdict": result["verdict"], **result["rolling"]["metrics"]}, sort_keys=True)
    )


if __name__ == "__main__":
    main()
