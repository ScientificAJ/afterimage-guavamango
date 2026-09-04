#!/usr/bin/env python3
"""Fresh-partition multi-day cross-index trend-carry experiment."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import Bar, Costs, build_dry_run_order
from experiments.strategy_candidates.mean_reversion.gap_expansion import UnderlyingSignal
from experiments.strategy_candidates.mean_reversion.multi_day_trend import CarryParameters, detect_multi_day_trend
from experiments.strategy_candidates.mean_reversion.research import contract_pair, pair_option_bars
from experiments.strategy_candidates.mean_reversion.run_cross_index_trend import stock_page_rows
from experiments.strategy_candidates.mean_reversion.run_gap_expansion import _metrics, _selected_oos
from experiments.strategy_candidates.mean_reversion.run_research import PROFILE, _chunks, _fetch_pages, _json_default, _sha256, _write_json
from experiments.strategy_candidates.mean_reversion.trend_confirmation import bracket_round_trip, make_rolling_folds


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "multi_day_trend"
DATA = OUTPUT / "data"
STOCK_CACHE = DATA / "multi_stock_5min.json"
OPTION_CACHE = DATA / "multi_option_15min.json"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
START = "2026-01-02T09:00:00Z"
END = "2026-05-01T00:00:00Z"
SYMBOLS = ("SPY", "QQQ", "IWM")
NEW_YORK = ZoneInfo("America/New_York")
BASE_COSTS = Costs(Decimal("0.03"), Decimal("0.65"))
STRESS_COSTS = Costs(Decimal("0.045"), Decimal("0.975"))


@dataclass(frozen=True)
class CarryVariant:
    name: str
    signal: CarryParameters
    risk_fraction: Decimal
    max_holding_bars: int


@dataclass(frozen=True)
class EvaluatedCarryTrade:
    session: date
    month: str
    variant: str
    underlying: str
    direction: str
    signal_at: datetime
    completed_at: datetime
    long_symbol: str
    short_symbol: str
    entry_at: datetime
    exit_at: datetime
    entry_debit: Decimal
    exit_credit: Decimal
    risk_dollars: Decimal
    net_pnl: Decimal
    return_r: Decimal
    exit_reason: str
    operational_target_stop: Decimal


VARIANTS = (
    CarryVariant("l03_m002_n2_r12_h40", CarryParameters(3, Decimal("0.002"), 2), Decimal("0.12"), 40),
    CarryVariant("l03_m005_n3_r15_h40", CarryParameters(3, Decimal("0.005"), 3), Decimal("0.15"), 40),
    CarryVariant("l05_m005_n2_r12_h52", CarryParameters(5, Decimal("0.005"), 2), Decimal("0.12"), 52),
    CarryVariant("l05_m010_n3_r15_h52", CarryParameters(5, Decimal("0.010"), 3), Decimal("0.15"), 52),
    CarryVariant("l10_m010_n2_r15_h52", CarryParameters(10, Decimal("0.010"), 2), Decimal("0.15"), 52),
    CarryVariant("l10_m020_n3_r20_h65", CarryParameters(10, Decimal("0.020"), 3), Decimal("0.20"), 65),
)


def fetch_stock() -> None:
    bars: dict[str, list[Mapping[str, Any]]] = {}
    page_counts = {}
    for symbol in SYMBOLS:
        pages = _fetch_pages(("data", "bars", "--symbol", symbol, "--start", START, "--end", END, "--timeframe", "5Min", "--feed", "iex", "--adjustment", "raw", "--sort", "asc", "--limit", "10000"))
        bars[symbol] = [row for page in pages for row in stock_page_rows(page, symbol)]
        page_counts[symbol] = len(pages)
    _write_json(STOCK_CACHE, {"provenance": {"source": "Alpaca CLI", "profile": PROFILE, "feed": "iex", "timeframe": "5Min", "start": START, "end": END, "page_counts": page_counts}, "bars": bars})


def _parse_stock() -> dict[str, tuple[Bar, ...]]:
    payload = json.loads(STOCK_CACHE.read_text(encoding="utf-8"))["bars"]
    output = {}
    for symbol in SYMBOLS:
        rows = []
        for item in payload[symbol]:
            timestamp = datetime.fromisoformat(item["t"].replace("Z", "+00:00"))
            local = timestamp.astimezone(NEW_YORK)
            minute = local.hour * 60 + local.minute
            if local.weekday() < 5 and 9 * 60 + 30 <= minute < 16 * 60:
                rows.append(Bar(timestamp, float(item["o"]), float(item["h"]), float(item["l"]), float(item["c"]), float(item["v"])))
        output[symbol] = tuple(sorted(rows, key=lambda row: row.timestamp))
    return output


def fetch_options(signals: Mapping[str, Sequence[UnderlyingSignal]]) -> None:
    symbols = sorted({contract for rows in signals.values() for item in rows for contract in contract_pair(item.signal, root=item.underlying, minimum_dte=7)})
    bars: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in symbols}
    page_count = 0
    for chunk in _chunks(symbols, 80):
        pages = _fetch_pages(("data", "option", "bars", "--symbols", ",".join(chunk), "--start", START, "--end", END, "--timeframe", "15Min", "--sort", "asc", "--limit", "10000"))
        page_count += len(pages)
        for page in pages:
            for symbol, rows in (page.get("bars") or {}).items():
                bars.setdefault(symbol, []).extend(rows)
    _write_json(OPTION_CACHE, {"provenance": {"source": "Alpaca CLI", "profile": PROFILE, "timeframe": "15Min", "start": START, "end": END, "minimum_dte": 7, "requested_symbol_count": len(symbols), "page_count": page_count}, "bars": bars})


def _evaluate(signals: Mapping[str, Sequence[UnderlyingSignal]], costs: Costs) -> tuple[dict[str, tuple[EvaluatedCarryTrade, ...]], dict[str, int]]:
    payload = json.loads(OPTION_CACHE.read_text(encoding="utf-8"))
    lookup = {variant.name: variant for variant in VARIANTS}
    output = {}
    missing = {}
    for name, rows in signals.items():
        evaluated = []
        missed = 0
        variant = lookup[name]
        for item in rows:
            signal = item.signal
            long_symbol, short_symbol = contract_pair(signal, root=item.underlying, minimum_dte=7)
            paired = pair_option_bars(payload, long_symbol, short_symbol)
            try:
                trade = bracket_round_trip(signal.completed_at, paired, costs, variant.risk_fraction, Decimal("3"), variant.max_holding_bars, bar_minutes=15)
            except ValueError:
                missed += 1
                continue
            evaluated.append(EvaluatedCarryTrade(signal.signal_bar_start.date(), signal.signal_bar_start.strftime("%Y-%m"), name, item.underlying, signal.direction, signal.signal_bar_start, signal.completed_at, long_symbol, short_symbol, trade.entry_at, trade.exit_at, trade.entry_debit, trade.exit_credit, trade.risk_dollars, trade.net_pnl, trade.return_r, trade.exit_reason, trade.operational_target_stop))
        output[name] = tuple(evaluated)
        missing[name] = missed
    return output, missing


def _build_results(stock: Mapping[str, Sequence[Bar]], signals: Mapping[str, Sequence[UnderlyingSignal]], base: Mapping[str, Sequence[EvaluatedCarryTrade]], stressed: Mapping[str, Sequence[EvaluatedCarryTrade]], missing: Mapping[str, int]) -> dict[str, Any]:
    sessions = tuple(sorted(set.intersection(*(set(row.timestamp.date() for row in stock[symbol]) for symbol in SYMBOLS))))
    folds = make_rolling_folds(sessions, 25, 2, 10, 10)
    oos, fold_results = _selected_oos(base, folds)
    stress_oos = [row for source, reported in zip(folds, fold_results, strict=True) for row in stressed.get(reported["selected_variant"], ()) if row.session in set(source.test)]
    oos_dates = {day for fold in folds for day in fold.test}
    neighbors = {name: _metrics(tuple(row for row in rows if row.session in oos_dates)) for name, rows in base.items()}
    by_underlying = {symbol: _metrics(tuple(row for row in oos if row.underlying == symbol)) for symbol in SYMBOLS}
    months = sorted({row.month for row in oos})
    by_month = {month: _metrics(tuple(row for row in oos if row.month == month)) for month in months}
    stats = _metrics(oos)
    stress_stats = _metrics(stress_oos)
    gross_profit = Decimal(stats["gross_profit"])
    max_win = max((row.net_pnl for row in oos if row.net_pnl > 0), default=Decimal(0))
    positive_folds = sum(Decimal(fold["oos"]["net_pnl"]) > 0 for fold in fold_results)
    positive_months = sum(Decimal(metric["net_pnl"]) > 0 for metric in by_month.values())
    positive_neighbors = sum(Decimal(metric["net_pnl"]) > 0 for metric in neighbors.values())
    criteria = {
        "target_stop_gte_3": bool(oos) and all(row.operational_target_stop >= 3 for row in oos),
        "profit_factor_gte_2": stats["profit_factor"] is not None and Decimal(stats["profit_factor"]) >= 2,
        "expectancy_gte_quarter_r": Decimal(stats["expectancy_r"]) >= Decimal("0.25"),
        "closed_oos_trades_gte_30": len(oos) >= 30,
        "max_drawdown_lte_6r": Decimal(stats["max_drawdown_r"]) <= 6,
        "positive_on_two_underlyings": sum(Decimal(metric["net_pnl"]) > 0 for metric in by_underlying.values()) >= 2,
        "positive_in_60pct_folds": bool(fold_results) and Decimal(positive_folds) / len(fold_results) >= Decimal("0.60"),
        "positive_in_60pct_months": bool(months) and Decimal(positive_months) / len(months) >= Decimal("0.60"),
        "profitable_at_1_5x_costs": Decimal(stress_stats["net_pnl"]) > 0,
        "at_least_60pct_neighbors_positive": Decimal(positive_neighbors) / len(neighbors) >= Decimal("0.60"),
        "no_single_trade_gt_25pct_gross_profit": gross_profit > 0 and max_win <= gross_profit * Decimal("0.25"),
    }
    return {"schema_version": 1, "attempt": "004_multi_day_cross_index_trend", "strategy": "multi-day cross-index trend carry", "data": {"start": START, "end": END, "symbols": SYMBOLS, "shared_sessions": len(sessions), "stock_bars": {symbol: len(stock[symbol]) for symbol in SYMBOLS}, "stock_cache_sha256": _sha256(STOCK_CACHE), "option_cache_sha256": _sha256(OPTION_CACHE)}, "method": {"signal": "14:45 New York completed-bar N-session return, confirmed by >=2 indices", "instrument": "trade each confirming SPY/QQQ/IWM 7+DTE $5 debit vertical", "execution": "wait for a fully post-signal synchronized 15-minute option bar, then hold into following sessions", "bracket": "after-cost +3R target / -1R stop threshold; adverse stop gaps retained", "validation": "25-session rolling train, 2-session embargo, unique 10-session OOS with nested selection", "base_costs": asdict(BASE_COSTS), "stress_costs_1_5x": asdict(STRESS_COSTS)}, "variants": {variant.name: {"signal": asdict(variant.signal), "risk_fraction": variant.risk_fraction, "max_holding_bars": variant.max_holding_bars, "signals": len(signals[variant.name]), "missing_or_illiquid": missing[variant.name], "neighbor_oos": neighbors[variant.name]} for variant in VARIANTS}, "folds": fold_results, "oos": {"statistics": stats, "by_underlying": by_underlying, "by_month": by_month, "trades": [asdict(row) for row in oos]}, "stress_1_5x_cost_oos": {"statistics": stress_stats, "trades": [asdict(row) for row in stress_oos]}, "admission": {"criteria": criteria, "admitted": all(criteria.values())}}


def _report(result: Mapping[str, Any]) -> str:
    stats = result["oos"]["statistics"]
    lines = ["# Multi-day cross-index trend carry", "", "## Rolling-OOS decision", "", f"**{stats['sample_size']} trades**, **${stats['net_pnl']} net**, **{Decimal(str(stats['expectancy_r'])):.4f}R expectancy**, **PF {stats['profit_factor']}**, **{stats['max_drawdown_r']}R / ${stats['max_drawdown']} max drawdown**.", "", f"Admitted: **{result['admission']['admitted']}**.", "", "## Admission matrix", "", "| Criterion | Pass |", "|---|---:|"]
    lines.extend(f"| {name} | {value} |" for name, value in result["admission"]["criteria"].items())
    lines.extend(["", "## Implementation contract", "", "- At 14:45 New York time, use only that completed five-minute bar and prior completed sessions. Require the configured N-session return direction in at least two of SPY/QQQ/IWM, then trade every confirming underlying.", "- Construct a directional one-lot $5-wide debit vertical with the first weekday expiry at least seven calendar days out. Wait until the first entirely post-signal synchronized 15-minute option bar has closed before entry.", "- Apply $0.03 adverse slippage per leg per side and $0.65/contract/side. Stop at -1R and target +3R after all costs; preserve worse stop gaps and grant no target improvement. Timeout may extend into following sessions.", "- Outer OOS dates never overlap. Variant selection occurs only inside rolling, embargoed inner validation slices. The 1.5x cost and neighbor checks reuse frozen OOS only as stress diagnostics, never as fresh tuning data.", "- The dry-run artifact is non-submitting and real paper execution remains parent-serialized behind repository risk/warrant gates.", "", "## Limitations", "", "IEX is not SIP, and Alpaca option trade bars lack NBBO. Sparse/missing synchronized leg bars are counted and excluded rather than imputed. Calendar construction skips weekends but unavailable holiday contracts naturally fail coverage.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch or not STOCK_CACHE.exists():
        fetch_stock()
    stock = _parse_stock()
    signals = {variant.name: detect_multi_day_trend(stock, variant.signal) for variant in VARIANTS}
    if args.fetch or not OPTION_CACHE.exists():
        fetch_options(signals)
    base, missing = _evaluate(signals, BASE_COSTS)
    stressed, _ = _evaluate(signals, STRESS_COSTS)
    result = _build_results(stock, signals, base, stressed, missing)
    _write_json(RESULTS, result)
    REPORT.write_text(_report(result), encoding="utf-8")
    example = next(iter(result["oos"]["trades"]), None)
    order = build_dry_run_order(example["direction"], example["long_symbol"], example["short_symbol"], Decimal(example["entry_debit"]), "multi-day-trend-research-dry-run") if example else {"submission_allowed": False, "reason": "no rolling-OOS trade"}
    _write_json(ORDER_DRY_RUN, order)
    print(json.dumps({"statistics": result["oos"]["statistics"], "admission": result["admission"]}, default=_json_default))


if __name__ == "__main__":
    main()
