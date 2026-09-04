#!/usr/bin/env python3
"""Fresh nested rolling-OOS cross-index relative-value convergence research."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.relative_value_pair import (
    PairBar,
    PairCosts,
    PairParameters,
    PairSignal,
    detect_relative_divergence,
    pair_bracket,
)
from experiments.strategy_candidates.mean_reversion.run_cross_index_trend import stock_page_rows
from experiments.strategy_candidates.mean_reversion.run_gap_expansion import _metrics, _selected_oos
from experiments.strategy_candidates.mean_reversion.run_research import PROFILE, _fetch_pages, _json_default, _sha256, _write_json
from experiments.strategy_candidates.mean_reversion.trend_confirmation import make_rolling_folds


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "relative_value_pair"
DATA = OUTPUT / "data"
STOCK_CACHE = DATA / "multi_stock_5min.json"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
START = "2024-09-03T08:00:00Z"
END = "2025-01-01T00:00:00Z"
SYMBOLS = ("SPY", "QQQ", "IWM")
NEW_YORK = ZoneInfo("America/New_York")
BASE_COSTS = PairCosts(Decimal("1.0"), Decimal("0.005"))
STRESS_COSTS = PairCosts(Decimal("1.5"), Decimal("0.0075"))


@dataclass(frozen=True)
class PairVariant:
    name: str
    signal: PairParameters
    max_holding_bars: int


@dataclass(frozen=True)
class EvaluatedPairTrade:
    session: date
    month: str
    variant: str
    underlying: str
    leader: str
    laggard: str
    divergence: Decimal
    signal_at: datetime
    completed_at: datetime
    entry_at: datetime
    exit_at: datetime
    long_quantity: int
    short_quantity: int
    long_entry_price: Decimal
    short_entry_price: Decimal
    risk_dollars: Decimal
    net_pnl: Decimal
    return_r: Decimal
    exit_reason: str
    operational_target_stop: Decimal


VARIANTS = (
    PairVariant("rv_t1030_d20_h24", PairParameters(10 * 60 + 30, Decimal("0.0020")), 24),
    PairVariant("rv_t1100_d30_h36", PairParameters(11 * 60, Decimal("0.0030")), 36),
    PairVariant("rv_t1130_d40_h36", PairParameters(11 * 60 + 30, Decimal("0.0040")), 36),
    PairVariant("rv_t1200_d50_h48", PairParameters(12 * 60, Decimal("0.0050")), 48),
    PairVariant("rv_t1300_d60_h36", PairParameters(13 * 60, Decimal("0.0060")), 36),
    PairVariant("rv_t1400_d80_h24", PairParameters(14 * 60, Decimal("0.0080")), 24),
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


def _pair_rows(
    stock: Mapping[str, Sequence[Bar]], signal: PairSignal, momentum: bool = False
) -> tuple[PairBar, ...]:
    long_symbol = signal.leader if momentum else signal.laggard
    short_symbol = signal.laggard if momentum else signal.leader
    long_rows = {row.timestamp: row for row in stock[long_symbol]}
    short_rows = {row.timestamp: row for row in stock[short_symbol]}
    return tuple(
        PairBar(timestamp, Decimal(str(long_rows[timestamp].open)), Decimal(str(long_rows[timestamp].high)), Decimal(str(long_rows[timestamp].low)), Decimal(str(long_rows[timestamp].close)), Decimal(str(short_rows[timestamp].open)), Decimal(str(short_rows[timestamp].high)), Decimal(str(short_rows[timestamp].low)), Decimal(str(short_rows[timestamp].close)))
        for timestamp in sorted(long_rows.keys() & short_rows.keys())
        if timestamp >= signal.completed_at
    )


def _evaluate(
    stock: Mapping[str, Sequence[Bar]],
    signals: Mapping[str, Sequence[PairSignal]],
    costs: PairCosts,
    variants: Sequence[PairVariant] = VARIANTS,
    momentum: bool = False,
    notional_per_leg: Decimal = Decimal("10000"),
) -> tuple[dict[str, tuple[EvaluatedPairTrade, ...]], dict[str, int]]:
    lookup = {variant.name: variant for variant in variants}
    output = {}
    missing = {}
    for name, rows in signals.items():
        evaluated = []
        missed = 0
        for signal in rows:
            try:
                trade = pair_bracket(signal.completed_at, _pair_rows(stock, signal, momentum), costs, notional_per_leg, Decimal("100"), Decimal("3"), lookup[name].max_holding_bars)
            except ValueError:
                missed += 1
                continue
            long_symbol = signal.leader if momentum else signal.laggard
            short_symbol = signal.laggard if momentum else signal.leader
            evaluated.append(EvaluatedPairTrade(signal.session, signal.session.strftime("%Y-%m"), name, f"{long_symbol}_LONG__{short_symbol}_SHORT", signal.leader, signal.laggard, signal.divergence, signal.signal_at, signal.completed_at, trade.entry_at, trade.exit_at, trade.long_quantity, trade.short_quantity, trade.long_entry_price, trade.short_entry_price, trade.risk_dollars, trade.net_pnl, trade.return_r, trade.exit_reason, trade.operational_target_stop))
        output[name] = tuple(evaluated)
        missing[name] = missed
    return output, missing


def _build_result(stock: Mapping[str, Sequence[Bar]], signals: Mapping[str, Sequence[PairSignal]], base: Mapping[str, Sequence[EvaluatedPairTrade]], stressed: Mapping[str, Sequence[EvaluatedPairTrade]], missing: Mapping[str, int], variants: Sequence[PairVariant] = VARIANTS) -> dict[str, Any]:
    sessions = tuple(sorted(set.intersection(*(set(row.timestamp.date() for row in stock[symbol]) for symbol in SYMBOLS))))
    folds = make_rolling_folds(sessions, 25, 2, 10, 10)
    oos, fold_results = _selected_oos(base, folds)
    stress_oos = [row for source, reported in zip(folds, fold_results, strict=True) for row in stressed.get(reported["selected_variant"], ()) if row.session in set(source.test)]
    oos_dates = {day for fold in folds for day in fold.test}
    neighbors = {name: _metrics(tuple(row for row in rows if row.session in oos_dates)) for name, rows in base.items()}
    months = sorted({row.month for row in oos})
    by_month = {month: _metrics(tuple(row for row in oos if row.month == month)) for month in months}
    by_pair = {pair: _metrics(tuple(row for row in oos if row.underlying == pair)) for pair in sorted({row.underlying for row in oos})}
    stats = _metrics(oos)
    stress_stats = _metrics(stress_oos)
    positive_folds = sum(Decimal(row["oos"]["net_pnl"]) > 0 for row in fold_results)
    positive_months = sum(Decimal(row["net_pnl"]) > 0 for row in by_month.values())
    positive_neighbors = sum(Decimal(row["net_pnl"]) > 0 for row in neighbors.values())
    positive_pairs = sum(Decimal(row["net_pnl"]) > 0 for row in by_pair.values())
    gross_profit = Decimal(stats["gross_profit"])
    max_win = max((row.net_pnl for row in oos if row.net_pnl > 0), default=Decimal(0))
    criteria = {"target_stop_gte_3": bool(oos) and all(row.operational_target_stop >= 3 for row in oos), "profit_factor_gte_2": stats["profit_factor"] is not None and Decimal(stats["profit_factor"]) >= 2, "expectancy_gte_quarter_r": Decimal(stats["expectancy_r"]) >= Decimal("0.25"), "closed_oos_trades_gte_30": len(oos) >= 30, "max_drawdown_lte_6r": Decimal(stats["max_drawdown_r"]) <= 6, "positive_on_two_pair_compositions_or_three_month_regimes": positive_pairs >= 2 or positive_months >= 3, "positive_in_60pct_folds": bool(fold_results) and Decimal(positive_folds) / len(fold_results) >= Decimal("0.60"), "positive_in_60pct_months": bool(months) and Decimal(positive_months) / len(months) >= Decimal("0.60"), "profitable_at_1_5x_costs": Decimal(stress_stats["net_pnl"]) > 0, "at_least_60pct_neighbors_positive": Decimal(positive_neighbors) / len(neighbors) >= Decimal("0.60"), "no_single_trade_gt_25pct_gross_profit": gross_profit > 0 and max_win <= gross_profit * Decimal("0.25")}
    return {"schema_version": 1, "attempt": "008_fresh_cross_index_relative_value", "strategy": "fresh cross-index intraday relative-value convergence pair", "classification": "Fresh nested rolling OOS; family frozen before September-December 2024 acquisition.", "data": {"source": "Alpaca IEX five-minute bars", "start": START, "end": END, "symbols": SYMBOLS, "shared_sessions": len(sessions), "stock_cache_sha256": _sha256(STOCK_CACHE)}, "method": {"signal": "fixed-time return dispersion; long laggard and short leader when divergence exceeds threshold", "execution": "$10,000 per leg, wait for next completed pair bar, close-confirmed combined-PnL exits", "risk": "$100 after-cost stop and $300 target (3R), adverse leg slippage and per-share fees", "validation": "25-session rolling train, 2-session embargo, unique 10-session OOS with nested selection", "costs": asdict(BASE_COSTS), "stress_costs_1_5x": asdict(STRESS_COSTS)}, "variants": {variant.name: {"signal": asdict(variant.signal), "max_holding_bars": variant.max_holding_bars, "signals": len(signals[variant.name]), "missing": missing[variant.name], "neighbor_oos": neighbors[variant.name]} for variant in variants}, "folds": fold_results, "oos": {"statistics": stats, "by_month": by_month, "by_pair": by_pair, "trades": [asdict(row) for row in oos]}, "stress_1_5x_cost_oos": {"statistics": stress_stats, "trades": [asdict(row) for row in stress_oos]}, "admission": {"criteria": criteria, "admitted": all(criteria.values())}}


def _dry_run(example: Mapping[str, Any] | None) -> dict[str, Any]:
    if not example:
        return {"submission_allowed": False, "reason": "no OOS trade"}
    payloads = [{"symbol": example["laggard"], "qty": str(example["long_quantity"]), "side": "buy", "type": "limit", "limit_price": example["long_entry_price"], "time_in_force": "day"}, {"symbol": example["leader"], "qty": str(example["short_quantity"]), "side": "sell", "type": "limit", "limit_price": example["short_entry_price"], "time_in_force": "day"}]
    commands = [["order", "submit", "--symbol", payload["symbol"], "--qty", payload["qty"], "--side", payload["side"], "--type", "limit", "--limit-price", payload["limit_price"], "--time-in-force", "day", "--quiet", "--dry-run"] for payload in payloads]
    return {"submission_allowed": False, "atomic_pair_not_supported": True, "required_execution": "serialize both dry-run legs; live paper pair requires parent-approved paired execution and combined-PnL monitor", "payloads": payloads, "cli_arguments": commands}


def _report(result: Mapping[str, Any]) -> str:
    stats = result["oos"]["statistics"]
    lines = ["# Cross-index relative-value convergence", "", result["classification"], "", f"Rolling OOS: **{stats['sample_size']} trades**, **${stats['net_pnl']} net**, **{Decimal(str(stats['expectancy_r'])):.4f}R**, **PF {stats['profit_factor']}**, **{stats['max_drawdown_r']}R max drawdown**.", "", f"Admitted: **{result['admission']['admitted']}**.", "", "## Admission matrix", "", "| Criterion | Pass |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in result["admission"]["criteria"].items())
    lines.extend(["", "## Implementation contract", "", "- At one predeclared New York time, compute each completed ETF return since its own regular-session open. Long the laggard and short the leader only when dispersion exceeds the selected inner-validation threshold.", "- Wait for the next aligned five-minute pair bar to close, use roughly $10,000 per leg, and apply 1 bp per side plus $0.005/share (1.5x stress separately).", "- Monitor combined after-cost pair P&L only on completed aligned closes. Stop at -$100 or worse and target exactly +$300, ensuring a 3R operational ratio without asynchronously combining leg extremes.", "- Outer OOS dates are unique and embargoed; only inner validation selects time/divergence/horizon. Neighbor and cost stress reuse frozen OOS solely as diagnostics.", "- Alpaca has no atomic equity-pair order in this CLI. The dry-run artifact therefore contains two non-submitting serialized entry payloads; any real paper pair requires parent-approved pairing and a combined-PnL monitor.", "", "## Limitations", "", "IEX is not SIP. Close-confirmed exits may react later than intrabar thresholds but avoid impossible asynchronous leg extremes. Short borrow and legging risk are not reconstructed and count against deployment readiness.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch or not STOCK_CACHE.exists():
        fetch_stock()
    stock = _parse_stock()
    signals = {variant.name: detect_relative_divergence(stock, variant.signal) for variant in VARIANTS}
    base, missing = _evaluate(stock, signals, BASE_COSTS)
    stressed, _ = _evaluate(stock, signals, STRESS_COSTS)
    result = _build_result(stock, signals, base, stressed, missing)
    _write_json(RESULTS, result)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(_report(result), encoding="utf-8")
    _write_json(ORDER_DRY_RUN, _dry_run(next(iter(result["oos"]["trades"]), None)))
    print(json.dumps({"statistics": result["oos"]["statistics"], "admission": result["admission"]}, default=_json_default))


if __name__ == "__main__":
    main()
