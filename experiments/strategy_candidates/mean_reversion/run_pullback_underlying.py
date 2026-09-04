#!/usr/bin/env python3
"""Fresh rolling-OOS cross-index pullback/resumption ETF experiment."""

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
from experiments.strategy_candidates.mean_reversion.pullback_trend import (
    PullbackParameters,
    detect_pullback_resumption,
)
from experiments.strategy_candidates.mean_reversion.run_cross_index_trend import stock_page_rows
from experiments.strategy_candidates.mean_reversion.run_research import PROFILE, _fetch_pages, _json_default, _sha256, _write_json
from experiments.strategy_candidates.mean_reversion.run_underlying_comparison import (
    UnderlyingVariant,
    evaluate_underlying,
)
from experiments.strategy_candidates.mean_reversion.underlying_execution import (
    EquityCosts,
    build_equity_dry_run_order,
)
from experiments.strategy_candidates.mean_reversion.underlying_research import (
    build_underlying_results,
    render_underlying_report,
)


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "pullback_underlying"
DATA = OUTPUT / "data"
STOCK_CACHE = DATA / "multi_stock_5min.json"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
START = "2026-05-01T08:00:00Z"
END = "2026-09-01T00:00:00Z"
SYMBOLS = ("SPY", "QQQ", "IWM")
NEW_YORK = ZoneInfo("America/New_York")
BASE_COSTS = EquityCosts(Decimal("1.0"), Decimal("0.005"))
STRESS_COSTS = EquityCosts(Decimal("1.5"), Decimal("0.0075"))
VARIANTS = (
    UnderlyingVariant("p_l06_m10_c2_v080_a2_h24", PullbackParameters(6, Decimal("0.0010"), 2, Decimal("0.80"), 10 * 60, 14 * 60 + 30), 12, Decimal("2"), 24),
    UnderlyingVariant("p_l06_m20_c3_v100_a2_h36", PullbackParameters(6, Decimal("0.0020"), 3, Decimal("1.00"), 10 * 60 + 30, 14 * 60 + 30), 12, Decimal("2"), 36),
    UnderlyingVariant("p_l12_m15_c2_v080_a2_h24", PullbackParameters(12, Decimal("0.0015"), 2, Decimal("0.80"), 10 * 60, 14 * 60 + 30), 24, Decimal("2"), 24),
    UnderlyingVariant("p_l12_m30_c3_v100_a3_h36", PullbackParameters(12, Decimal("0.0030"), 3, Decimal("1.00"), 10 * 60 + 30, 14 * 60), 24, Decimal("3"), 36),
    UnderlyingVariant("p_l18_m20_c2_v100_a3_h24", PullbackParameters(18, Decimal("0.0020"), 2, Decimal("1.00"), 11 * 60, 14 * 60 + 30), 36, Decimal("3"), 24),
    UnderlyingVariant("p_l18_m40_c3_v120_a3_h36", PullbackParameters(18, Decimal("0.0040"), 3, Decimal("1.20"), 11 * 60, 14 * 60), 36, Decimal("3"), 36),
)


def fetch_stock() -> None:
    bars: dict[str, list[Mapping[str, Any]]] = {}
    pages_by_symbol = {}
    for symbol in SYMBOLS:
        pages = _fetch_pages(("data", "bars", "--symbol", symbol, "--start", START, "--end", END, "--timeframe", "5Min", "--feed", "iex", "--adjustment", "raw", "--sort", "asc", "--limit", "10000"))
        bars[symbol] = [row for page in pages for row in stock_page_rows(page, symbol)]
        pages_by_symbol[symbol] = len(pages)
    _write_json(STOCK_CACHE, {"provenance": {"source": "Alpaca CLI", "profile": PROFILE, "feed": "iex", "timeframe": "5Min", "start": START, "end": END, "page_counts": pages_by_symbol}, "bars": bars})


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch or not STOCK_CACHE.exists():
        fetch_stock()
    stock = _parse_stock()
    signals = {
        variant.name: detect_pullback_resumption(stock, variant.signal)
        for variant in VARIANTS
    }
    base, missing = evaluate_underlying(stock, signals, BASE_COSTS, VARIANTS)
    stressed, _ = evaluate_underlying(stock, signals, STRESS_COSTS, VARIANTS)
    result = build_underlying_results(
        attempt="007_fresh_cross_index_pullback",
        strategy="Fresh cross-index pullback/resumption direct-ETF candidate",
        classification="Fresh nested rolling OOS; variant family frozen before May-August 2026 acquisition.",
        stock=stock,
        symbols=SYMBOLS,
        signals=signals,
        base=base,
        stressed=stressed,
        missing=missing,
        variants=VARIANTS,
        data={"source": "Alpaca IEX five-minute bars", "start": START, "end": END, "stock_cache_sha256": _sha256(STOCK_CACHE)},
        method={"signal": "completed counter-trend bar followed by completed engulfing resumption inside a cross-index VWAP/session/recent trend", "execution": "trade each confirming ETF after next bar completes", "risk": "ATR-scaled stop, about $100 initial risk, after-cost +3R target", "costs": asdict(BASE_COSTS), "stress_costs_1_5x": asdict(STRESS_COSTS), "validation": "25-session rolling train, 2-session embargo, unique 10-session OOS with nested selection"},
    )
    _write_json(RESULTS, result)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_underlying_report(result, ("Require SPY/QQQ/IWM completed-bar trend confirmation and an actual two-bar pullback/resumption event; only then trade each confirming ETF.", "Enter after the next five-minute bar closes with adverse slippage; ATR inputs end at the signal bar and position size targets about $100 risk.", "Solve stop/target for after-cost -1R/+3R, stop-first on same-bar ambiguity, worse gap stops, and no target improvement.", "Use non-overlapping outer OOS with embargoed nested selection; apply 1.5x-cost and neighbor checks without relabeling them as fresh.", "The exact Alpaca bracket artifact is non-submitting and ends in --dry-run.")), encoding="utf-8")
    example = next(iter(result["oos"]["trades"]), None)
    order = build_equity_dry_run_order(example["underlying"], example["direction"], example["quantity"], Decimal(example["entry_price"]), Decimal(example["target_price"]), Decimal(example["stop_price"])) if example else {"submission_allowed": False, "reason": "no OOS trade"}
    _write_json(ORDER_DRY_RUN, order)
    print(json.dumps({"statistics": result["oos"]["statistics"], "admission": result["admission"]}, default=_json_default))


if __name__ == "__main__":
    main()
