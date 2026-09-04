#!/usr/bin/env python3
"""Fresh cross-index relative-momentum pair attempt on an earlier partition."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.relative_value_pair import PairCosts, PairParameters, detect_relative_divergence
from experiments.strategy_candidates.mean_reversion.run_cross_index_trend import stock_page_rows
from experiments.strategy_candidates.mean_reversion.run_relative_value_pair import (
    PairVariant,
    _build_result,
    _evaluate,
)
from experiments.strategy_candidates.mean_reversion.run_research import PROFILE, _fetch_pages, _json_default, _sha256, _write_json


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "relative_momentum_pair"
DATA = OUTPUT / "data"
STOCK_CACHE = DATA / "multi_stock_5min.json"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
START = "2024-01-02T09:00:00Z"
END = "2024-05-01T00:00:00Z"
SYMBOLS = ("SPY", "QQQ", "IWM")
NEW_YORK = ZoneInfo("America/New_York")
BASE_COSTS = PairCosts(Decimal("1.0"), Decimal("0.005"))
STRESS_COSTS = PairCosts(Decimal("1.5"), Decimal("0.0075"))
VARIANTS = (
    PairVariant("rm_t1030_d10_h24", PairParameters(10 * 60 + 30, Decimal("0.0010")), 24),
    PairVariant("rm_t1100_d15_h36", PairParameters(11 * 60, Decimal("0.0015")), 36),
    PairVariant("rm_t1130_d20_h36", PairParameters(11 * 60 + 30, Decimal("0.0020")), 36),
    PairVariant("rm_t1200_d25_h48", PairParameters(12 * 60, Decimal("0.0025")), 48),
    PairVariant("rm_t1300_d35_h36", PairParameters(13 * 60, Decimal("0.0035")), 36),
    PairVariant("rm_t1400_d50_h24", PairParameters(14 * 60, Decimal("0.0050")), 24),
)


def fetch_stock() -> None:
    bars = {}
    page_counts = {}
    for symbol in SYMBOLS:
        pages = _fetch_pages(("data", "bars", "--symbol", symbol, "--start", START, "--end", END, "--timeframe", "5Min", "--feed", "iex", "--adjustment", "raw", "--sort", "asc", "--limit", "10000"))
        bars[symbol] = [row for page in pages for row in stock_page_rows(page, symbol)]
        page_counts[symbol] = len(pages)
    _write_json(STOCK_CACHE, {"provenance": {"source": "Alpaca CLI", "profile": PROFILE, "feed": "iex", "timeframe": "5Min", "start": START, "end": END, "page_counts": page_counts}, "bars": bars})


def _parse_stock() -> dict[str, tuple[Bar, ...]]:
    raw = json.loads(STOCK_CACHE.read_text(encoding="utf-8"))["bars"]
    output = {}
    for symbol in SYMBOLS:
        rows = []
        for item in raw[symbol]:
            timestamp = datetime.fromisoformat(item["t"].replace("Z", "+00:00"))
            local = timestamp.astimezone(NEW_YORK)
            minute = local.hour * 60 + local.minute
            if local.weekday() < 5 and 9 * 60 + 30 <= minute < 16 * 60:
                rows.append(Bar(timestamp, float(item["o"]), float(item["h"]), float(item["l"]), float(item["c"]), float(item["v"])))
        output[symbol] = tuple(sorted(rows, key=lambda row: row.timestamp))
    return output


def _dry_run(example: Mapping[str, Any] | None) -> dict[str, Any]:
    if not example:
        return {"submission_allowed": False, "reason": "no OOS trade"}
    payloads = [{"symbol": example["leader"], "qty": str(example["long_quantity"]), "side": "buy", "type": "limit", "limit_price": example["long_entry_price"], "time_in_force": "day"}, {"symbol": example["laggard"], "qty": str(example["short_quantity"]), "side": "sell", "type": "limit", "limit_price": example["short_entry_price"], "time_in_force": "day"}]
    commands = [["order", "submit", "--symbol", item["symbol"], "--qty", item["qty"], "--side", item["side"], "--type", "limit", "--limit-price", item["limit_price"], "--time-in-force", "day", "--quiet", "--dry-run"] for item in payloads]
    return {"submission_allowed": False, "atomic_pair_not_supported": True, "required_execution": "parent-approved serialized entry plus combined-PnL monitor", "payloads": payloads, "cli_arguments": commands}


def _report(result: Mapping[str, Any]) -> str:
    stats = result["oos"]["statistics"]
    lines = ["# Fresh cross-index relative-momentum pair", "", result["classification"], "", f"Rolling OOS: **{stats['sample_size']} trades**, **${stats['net_pnl']} net**, **{Decimal(str(stats['expectancy_r'])):.4f}R**, **PF {stats['profit_factor']}**, **{stats['max_drawdown_r']}R max drawdown**.", "", f"Admitted: **{result['admission']['admitted']}**.", "", "## Admission matrix", "", "| Criterion | Pass |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in result["admission"]["criteria"].items())
    lines.extend(["", "## Implementation contract", "", "- At a predeclared time, rank completed SPY/QQQ/IWM returns since the regular-session open. Long the leader and short the laggard only above the selected inner-validation divergence threshold.", "- Wait for the next aligned pair bar to close. Use about $20,000 per leg with 1 bp/side plus $0.005/share; apply a 1.5x cost stress.", "- Monitor combined pair P&L on completed aligned closes, stop at -$100 or worse, and cap the target at +$300 (3R). No asynchronous high/low combination is permitted.", "- Outer OOS dates are unique and embargoed; inner validation alone chooses time, divergence, and horizon. Neighbor/stress checks never become fresh training data.", "- The dry run contains two non-submitting legs. Live paper use would require parent-approved serialization, borrow confirmation, and a combined-PnL monitor because Alpaca does not offer atomic equity pairs here.", "", "## Limitations", "", "IEX is not SIP. Close-confirmed exits can lag intrabar thresholds. Short borrow and legging risk are not reconstructed and remain deployment blockers even if statistical gates pass.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch or not STOCK_CACHE.exists():
        fetch_stock()
    stock = _parse_stock()
    signals = {variant.name: detect_relative_divergence(stock, variant.signal) for variant in VARIANTS}
    base, missing = _evaluate(stock, signals, BASE_COSTS, VARIANTS, momentum=True, notional_per_leg=Decimal("20000"))
    stressed, _ = _evaluate(stock, signals, STRESS_COSTS, VARIANTS, momentum=True, notional_per_leg=Decimal("20000"))
    result = _build_result(stock, signals, base, stressed, missing, VARIANTS)
    result["attempt"] = "009_fresh_cross_index_relative_momentum"
    result["strategy"] = "fresh cross-index intraday relative-momentum pair"
    result["classification"] = "Fresh nested rolling OOS; family frozen before January-April 2024 acquisition."
    result["data"] = {"source": "Alpaca IEX five-minute bars", "start": START, "end": END, "symbols": SYMBOLS, "shared_sessions": result["data"]["shared_sessions"], "stock_cache_sha256": _sha256(STOCK_CACHE)}
    result["method"] = {"signal": "fixed-time return dispersion; long leader and short laggard", "execution": "$20,000 per leg after next completed aligned bar; close-confirmed combined P&L", "risk": "$100 after-cost stop / $300 target (3R)", "validation": "25-session rolling train, 2-session embargo, unique 10-session OOS with nested selection", "costs": asdict(BASE_COSTS), "stress_costs_1_5x": asdict(STRESS_COSTS)}
    _write_json(RESULTS, result)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(_report(result), encoding="utf-8")
    _write_json(ORDER_DRY_RUN, _dry_run(next(iter(result["oos"]["trades"]), None)))
    print(json.dumps({"statistics": result["oos"]["statistics"], "admission": result["admission"]}, default=_json_default))


if __name__ == "__main__":
    main()
