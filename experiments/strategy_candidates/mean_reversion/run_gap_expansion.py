#!/usr/bin/env python3
"""Nested rolling multi-underlying compression-to-gap expansion experiment."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import Bar, Costs, build_dry_run_order
from experiments.strategy_candidates.mean_reversion.gap_expansion import (
    GapParameters,
    UnderlyingSignal,
    detect_gap_expansion,
)
from experiments.strategy_candidates.mean_reversion.research import contract_pair, pair_option_bars
from experiments.strategy_candidates.mean_reversion.run_cross_index_trend import stock_page_rows
from experiments.strategy_candidates.mean_reversion.run_research import (
    PROFILE,
    _chunks,
    _fetch_pages,
    _json_default,
    _sha256,
    _write_json,
)
from experiments.strategy_candidates.mean_reversion.trend_confirmation import (
    bracket_round_trip,
    make_rolling_folds,
    performance,
)


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "gap_expansion"
DATA = OUTPUT / "data"
STOCK_CACHE = DATA / "multi_stock_5min.json"
OPTION_CACHE = DATA / "multi_option_5min.json"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
START = "2025-09-02T08:00:00Z"
END = "2026-01-01T00:00:00Z"
SYMBOLS = ("SPY", "QQQ", "IWM")
NEW_YORK = ZoneInfo("America/New_York")
BASE_COSTS = Costs(Decimal("0.03"), Decimal("0.65"))
STRESS_COSTS = Costs(Decimal("0.045"), Decimal("0.975"))


@dataclass(frozen=True)
class GapVariant:
    name: str
    signal: GapParameters
    risk_fraction: Decimal
    max_holding_bars: int


@dataclass(frozen=True)
class EvaluatedGapTrade:
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
    GapVariant("c080_g000_i10_n2_r08_h48", GapParameters(10, Decimal("0.80"), Decimal("0"), Decimal("0.0010"), 2), Decimal("0.08"), 48),
    GapVariant("c100_g005_i10_n2_r10_h36", GapParameters(10, Decimal("1.00"), Decimal("0.0005"), Decimal("0.0010"), 2), Decimal("0.10"), 36),
    GapVariant("c120_g010_i15_n2_r10_h48", GapParameters(10, Decimal("1.20"), Decimal("0.0010"), Decimal("0.0015"), 2), Decimal("0.10"), 48),
    GapVariant("c100_g000_i20_n3_r08_h36", GapParameters(10, Decimal("1.00"), Decimal("0"), Decimal("0.0020"), 3), Decimal("0.08"), 36),
    GapVariant("c080_g015_i20_n2_r12_h48", GapParameters(10, Decimal("0.80"), Decimal("0.0015"), Decimal("0.0020"), 2), Decimal("0.12"), 48),
    GapVariant("c120_g020_i25_n3_r10_h60", GapParameters(10, Decimal("1.20"), Decimal("0.0020"), Decimal("0.0025"), 3), Decimal("0.10"), 60),
)


def fetch_stock() -> None:
    bars: dict[str, list[Mapping[str, Any]]] = {}
    pages_by_symbol: dict[str, int] = {}
    for symbol in SYMBOLS:
        pages = _fetch_pages(("data", "bars", "--symbol", symbol, "--start", START, "--end", END, "--timeframe", "5Min", "--feed", "iex", "--adjustment", "raw", "--sort", "asc", "--limit", "10000"))
        bars[symbol] = [row for page in pages for row in stock_page_rows(page, symbol)]
        pages_by_symbol[symbol] = len(pages)
    _write_json(STOCK_CACHE, {"provenance": {"source": "Alpaca CLI", "profile": PROFILE, "feed": "iex", "timeframe": "5Min", "start": START, "end": END, "page_counts": pages_by_symbol}, "bars": bars})


def _parse_stock() -> dict[str, tuple[Bar, ...]]:
    raw = json.loads(STOCK_CACHE.read_text(encoding="utf-8"))["bars"]
    parsed: dict[str, tuple[Bar, ...]] = {}
    for symbol in SYMBOLS:
        rows = []
        for item in raw[symbol]:
            timestamp = datetime.fromisoformat(item["t"].replace("Z", "+00:00"))
            local = timestamp.astimezone(NEW_YORK)
            minute = local.hour * 60 + local.minute
            if local.weekday() < 5 and 9 * 60 + 30 <= minute < 16 * 60:
                rows.append(Bar(timestamp, float(item["o"]), float(item["h"]), float(item["l"]), float(item["c"]), float(item["v"])))
        parsed[symbol] = tuple(sorted(rows, key=lambda row: row.timestamp))
    return parsed


def fetch_options(signals_by_variant: Mapping[str, Sequence[UnderlyingSignal]]) -> None:
    symbols = sorted({contract for signals in signals_by_variant.values() for item in signals for contract in contract_pair(item.signal, root=item.underlying)})
    combined: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in symbols}
    pages_total = 0
    for chunk in _chunks(symbols, 80):
        pages = _fetch_pages(("data", "option", "bars", "--symbols", ",".join(chunk), "--start", START, "--end", END, "--timeframe", "5Min", "--sort", "asc", "--limit", "10000"))
        pages_total += len(pages)
        for page in pages:
            for symbol, rows in (page.get("bars") or {}).items():
                combined.setdefault(symbol, []).extend(rows)
    _write_json(OPTION_CACHE, {"provenance": {"source": "Alpaca CLI", "profile": PROFILE, "timeframe": "5Min", "start": START, "end": END, "requested_symbol_count": len(symbols), "page_count": pages_total}, "bars": combined})


def _evaluate(signals_by_variant: Mapping[str, Sequence[UnderlyingSignal]], costs: Costs) -> tuple[dict[str, tuple[EvaluatedGapTrade, ...]], dict[str, int]]:
    payload = json.loads(OPTION_CACHE.read_text(encoding="utf-8"))
    lookup = {variant.name: variant for variant in VARIANTS}
    output: dict[str, tuple[EvaluatedGapTrade, ...]] = {}
    missing: dict[str, int] = {}
    for name, signals in signals_by_variant.items():
        rows = []
        missed = 0
        variant = lookup[name]
        for item in signals:
            signal = item.signal
            long_symbol, short_symbol = contract_pair(signal, root=item.underlying)
            paired = pair_option_bars(payload, long_symbol, short_symbol)
            try:
                trade = bracket_round_trip(signal.completed_at, paired, costs, variant.risk_fraction, Decimal("3"), variant.max_holding_bars)
            except ValueError:
                missed += 1
                continue
            rows.append(EvaluatedGapTrade(signal.signal_bar_start.date(), signal.signal_bar_start.strftime("%Y-%m"), name, item.underlying, signal.direction, signal.signal_bar_start, signal.completed_at, long_symbol, short_symbol, trade.entry_at, trade.exit_at, trade.entry_debit, trade.exit_credit, trade.risk_dollars, trade.net_pnl, trade.return_r, trade.exit_reason, trade.operational_target_stop))
        output[name] = tuple(rows)
        missing[name] = missed
    return output, missing


def _metrics(rows: Sequence[EvaluatedGapTrade]) -> dict[str, Any]:
    result = performance(tuple(row.net_pnl for row in rows))
    returns = tuple(row.return_r for row in rows)
    result["expectancy_r"] = sum(returns, Decimal(0)) / len(returns) if returns else Decimal(0)
    equity_r = peak_r = drawdown_r = Decimal(0)
    for value in returns:
        equity_r += value
        peak_r = max(peak_r, equity_r)
        drawdown_r = max(drawdown_r, peak_r - equity_r)
    result["max_drawdown_r"] = drawdown_r
    result["exit_reasons"] = dict(Counter(row.exit_reason for row in rows))
    return result


def _choose(evaluated: Mapping[str, Sequence[EvaluatedGapTrade]], validation: Sequence[date]) -> tuple[str | None, dict[str, Any]]:
    allowed = set(validation)
    diagnostics = {}
    scores = []
    for name, all_rows in evaluated.items():
        rows = tuple(row for row in all_rows if row.session in allowed)
        metric = _metrics(rows)
        diagnostics[name] = metric
        if len(rows) >= 3:
            scores.append((Decimal(metric["expectancy_r"]), Decimal(metric["net_pnl"]), name))
    if not scores:
        return None, diagnostics
    scores.sort(key=lambda value: (-value[0], -value[1], value[2]))
    return scores[0][2], diagnostics


def _selected_oos(evaluated: Mapping[str, Sequence[EvaluatedGapTrade]], folds: Sequence[Any]) -> tuple[list[EvaluatedGapTrade], list[dict[str, Any]]]:
    oos = []
    fold_results = []
    for number, fold in enumerate(folds, start=1):
        inner = make_rolling_folds(fold.train, 12, 2, 5, 5)
        validation = tuple(day for inner_fold in inner for day in inner_fold.test)
        selected, diagnostics = _choose(evaluated, validation)
        rows = tuple(row for row in evaluated[selected] if row.session in set(fold.test)) if selected else ()
        oos.extend(rows)
        fold_results.append({"fold": number, "train": {"start": fold.train[0], "end": fold.train[-1], "sessions": len(fold.train)}, "embargo": {"start": fold.embargo[0], "end": fold.embargo[-1], "sessions": len(fold.embargo)}, "test": {"start": fold.test[0], "end": fold.test[-1], "sessions": len(fold.test)}, "inner_validation_dates": validation, "selected_variant": selected, "inner_diagnostics": diagnostics, "oos": _metrics(rows)})
    return oos, fold_results


def _build_results(stock: Mapping[str, Sequence[Bar]], signals: Mapping[str, Sequence[UnderlyingSignal]], evaluated: Mapping[str, Sequence[EvaluatedGapTrade]], stress_evaluated: Mapping[str, Sequence[EvaluatedGapTrade]], missing: Mapping[str, int]) -> dict[str, Any]:
    sessions = tuple(sorted(set.intersection(*(set(row.timestamp.date() for row in stock[symbol]) for symbol in SYMBOLS))))
    folds = make_rolling_folds(sessions, 25, 2, 10, 10)
    oos, fold_results = _selected_oos(evaluated, folds)
    stress_oos = [
        row
        for source_fold, reported_fold in zip(folds, fold_results, strict=True)
        for row in stress_evaluated.get(reported_fold["selected_variant"], ())
        if row.session in set(source_fold.test)
    ]
    oos_dates = set(day for fold in folds for day in fold.test)
    neighboring = {name: _metrics(tuple(row for row in rows if row.session in oos_dates)) for name, rows in evaluated.items()}
    by_underlying = {symbol: _metrics(tuple(row for row in oos if row.underlying == symbol)) for symbol in SYMBOLS}
    months = sorted({row.month for row in oos})
    by_month = {month: _metrics(tuple(row for row in oos if row.month == month)) for month in months}
    stats = _metrics(oos)
    stress_stats = _metrics(stress_oos)
    positive_folds = sum(Decimal(fold["oos"]["net_pnl"]) > 0 for fold in fold_results)
    positive_months = sum(Decimal(metric["net_pnl"]) > 0 for metric in by_month.values())
    gross_profit = Decimal(stats["gross_profit"])
    max_win = max((row.net_pnl for row in oos if row.net_pnl > 0), default=Decimal(0))
    criteria = {
        "target_stop_gte_3": bool(oos) and all(row.operational_target_stop >= 3 for row in oos),
        "profit_factor_gte_2": stats["profit_factor"] is not None and Decimal(stats["profit_factor"]) >= 2,
        "expectancy_gte_quarter_r": Decimal(stats["expectancy_r"]) >= Decimal("0.25"),
        "closed_oos_trades_gte_30": len(oos) >= 30,
        "max_drawdown_lte_6r": Decimal(stats["max_drawdown_r"]) <= 6,
        "positive_on_two_underlyings": sum(Decimal(value["net_pnl"]) > 0 for value in by_underlying.values()) >= 2,
        "positive_in_60pct_folds": bool(fold_results) and Decimal(positive_folds) / len(fold_results) >= Decimal("0.60"),
        "positive_in_60pct_months": bool(months) and Decimal(positive_months) / len(months) >= Decimal("0.60"),
        "profitable_at_1_5x_costs": Decimal(stress_stats["net_pnl"]) > 0,
        "at_least_60pct_neighbor_variants_positive": Decimal(sum(Decimal(value["net_pnl"]) > 0 for value in neighboring.values())) / len(neighboring) >= Decimal("0.60"),
        "no_single_trade_gt_25pct_gross_profit": gross_profit > 0 and max_win <= gross_profit * Decimal("0.25"),
    }
    return {"schema_version": 1, "attempt": "003_multi_underlying_gap_expansion", "strategy": "multi-underlying prior-compression opening gap expansion", "data": {"start": START, "end": END, "symbols": SYMBOLS, "shared_sessions": len(sessions), "stock_bars": {symbol: len(stock[symbol]) for symbol in SYMBOLS}, "stock_cache_sha256": _sha256(STOCK_CACHE), "option_cache_sha256": _sha256(OPTION_CACHE)}, "method": {"signal": "compressed prior daily range plus same-direction opening gap and completed first-bar impulse on >=2 indices", "execution": "trade every confirming underlying using a 3+DTE $5 debit vertical; enter only after next option bar completes", "bracket": "after-cost +3R target / -1R stop threshold; target no improvement, stop gaps retained", "validation": "25-session outer rolling train, 2-session embargo, unique 10-session OOS; nested 12/2/5 selection", "base_costs": asdict(BASE_COSTS), "stress_costs_1_5x": asdict(STRESS_COSTS)}, "variants": {variant.name: {"signal_parameters": asdict(variant.signal), "risk_fraction": variant.risk_fraction, "max_holding_bars": variant.max_holding_bars, "signals": len(signals[variant.name]), "missing_or_illiquid": missing[variant.name], "neighbor_oos": neighboring[variant.name]} for variant in VARIANTS}, "folds": fold_results, "oos": {"statistics": stats, "by_underlying": by_underlying, "by_month": by_month, "trades": [asdict(row) for row in oos]}, "stress_1_5x_cost_oos": {"statistics": stress_stats, "trades": [asdict(row) for row in stress_oos]}, "admission": {"criteria": criteria, "admitted": all(criteria.values())}}


def _render_report(result: Mapping[str, Any]) -> str:
    stats = result["oos"]["statistics"]
    criteria = result["admission"]["criteria"]
    lines = ["# Multi-underlying compression-to-gap expansion", "", "## Rolling-OOS result", "", f"Closed OOS trades: **{stats['sample_size']}**; net: **${stats['net_pnl']}**; expectancy: **{Decimal(str(stats['expectancy_r'])):.4f}R**; PF: **{stats['profit_factor']}**; max drawdown: **{stats['max_drawdown_r']}R / ${stats['max_drawdown']}**.", "", f"Admitted: **{result['admission']['admitted']}**.", "", "## Fixed admission bar", "", "| Criterion | Pass |", "|---|---:|"]
    lines.extend(f"| {name} | {passed} |" for name, passed in criteria.items())
    lines.extend(["", "## Per-underlying OOS", "", "| Underlying | n | Net | PF | Exp/R | DD R |", "|---|---:|---:|---:|---:|---:|"])
    for symbol, metric in result["oos"]["by_underlying"].items():
        lines.append(f"| {symbol} | {metric['sample_size']} | ${metric['net_pnl']} | {metric['profit_factor']} | {Decimal(str(metric['expectancy_r'])):.4f} | {metric['max_drawdown_r']} |")
    lines.extend(["", "## Implementation contract", "", "- Read only completed, aligned IEX bars. Prior-day compression uses only sessions ending before the signal day; gap uses the opening print; impulse uses the completed 09:30-09:35 New York bar.", "- Require at least two of SPY/QQQ/IWM to align, then trade each confirming underlying. Use the first weekday expiry at least three calendar days out and a directional $5 debit spread.", "- Wait for the first synchronized option bar after signal completion to itself close. Apply adverse leg slippage and per-contract fees on entry and exit.", "- Stop is -1R and target +3R after modeled total costs. Gap-through stops retain the worse close; targets are capped at the threshold. Missing leg bars are excluded, never imputed.", "- Outer test dates are unique. Selection occurs only on embargoed inner validation slices. Double-cost and parameter-neighbor checks use the same frozen outer dates and do not relabel them as fresh.", "- `order_dry_run.json` cannot submit and ends with `--dry-run`; real paper execution remains parent-serialized behind normal gates.", "", "## Limitations", "", "IEX is not SIP and historical option trade bars have no NBBO. Close-plus-adverse-slippage is a conservative proxy, not quote replay. Standard weekday expiry construction records holiday/unavailable contracts as missing.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch or not STOCK_CACHE.exists():
        fetch_stock()
    stock = _parse_stock()
    signals = {variant.name: detect_gap_expansion(stock, variant.signal) for variant in VARIANTS}
    if args.fetch or not OPTION_CACHE.exists():
        fetch_options(signals)
    evaluated, missing = _evaluate(signals, BASE_COSTS)
    stressed, _ = _evaluate(signals, STRESS_COSTS)
    result = _build_results(stock, signals, evaluated, stressed, missing)
    _write_json(RESULTS, result)
    REPORT.write_text(_render_report(result), encoding="utf-8")
    example = next(iter(result["oos"]["trades"]), None)
    order = build_dry_run_order(example["direction"], example["long_symbol"], example["short_symbol"], Decimal(example["entry_debit"]), "gap-expansion-research-dry-run") if example else {"submission_allowed": False, "reason": "no rolling-OOS trade"}
    _write_json(ORDER_DRY_RUN, order)
    print(json.dumps({"statistics": result["oos"]["statistics"], "admission": result["admission"]}, default=_json_default))


if __name__ == "__main__":
    main()
