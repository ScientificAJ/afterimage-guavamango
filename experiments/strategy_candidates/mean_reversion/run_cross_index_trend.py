#!/usr/bin/env python3
"""Nested rolling walk-forward for cross-index VWAP trend persistence."""

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

from experiments.strategy_candidates.mean_reversion.candidate import (
    Bar,
    Costs,
    Signal,
    build_dry_run_order,
)
from experiments.strategy_candidates.mean_reversion.research import (
    contract_pair,
    pair_option_bars,
)
from experiments.strategy_candidates.mean_reversion.run_research import (
    PROFILE,
    REPO,
    _chunks,
    _fetch_pages,
    _json_default,
    _sha256,
    _write_json,
)
from experiments.strategy_candidates.mean_reversion.trend_confirmation import (
    BracketTrade,
    TrendParameters,
    bracket_round_trip,
    detect_cross_index_trend,
    make_rolling_folds,
    performance,
)


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "cross_index"
DATA = OUTPUT / "data"
STOCK_CACHE = DATA / "spy_qqq_iwm_5min_2025-05-01_2025-08-29.json"
OPTION_CACHE = DATA / "spy_option_5min.json"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
START = "2025-05-01T08:00:00Z"
END = "2025-08-30T00:00:00Z"
SYMBOLS = ("SPY", "QQQ", "IWM")
NEW_YORK = ZoneInfo("America/New_York")
COSTS = Costs(Decimal("0.03"), Decimal("0.65"))


@dataclass(frozen=True)
class TrendVariant:
    name: str
    parameters: TrendParameters


@dataclass(frozen=True)
class EvaluatedTrendTrade:
    session: date
    variant: str
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
    TrendVariant(
        "t1130_m15_c2_l06_r10_h24",
        TrendParameters(11 * 60 + 30, 6, Decimal("0.0015"), 2, Decimal("0.10"), Decimal("3"), 24),
    ),
    TrendVariant(
        "t1200_m10_c3_l06_r08_h36",
        TrendParameters(12 * 60, 6, Decimal("0.0010"), 3, Decimal("0.08"), Decimal("3"), 36),
    ),
    TrendVariant(
        "t1230_m20_c2_l12_r10_h24",
        TrendParameters(12 * 60 + 30, 12, Decimal("0.0020"), 2, Decimal("0.10"), Decimal("3"), 24),
    ),
    TrendVariant(
        "t1300_m30_c3_l06_r12_h24",
        TrendParameters(13 * 60, 6, Decimal("0.0030"), 3, Decimal("0.12"), Decimal("3"), 24),
    ),
    TrendVariant(
        "t1330_m40_c3_l12_r12_h18",
        TrendParameters(13 * 60 + 30, 12, Decimal("0.0040"), 3, Decimal("0.12"), Decimal("3"), 18),
    ),
    TrendVariant(
        "t1400_m50_c2_l12_r15_h18",
        TrendParameters(14 * 60, 12, Decimal("0.0050"), 2, Decimal("0.15"), Decimal("3"), 18),
    ),
)


def stock_page_rows(page: Mapping[str, Any], symbol: str) -> list[Mapping[str, Any]]:
    bars = page.get("bars") or []
    if isinstance(bars, dict):
        return list(bars.get(symbol, []))
    return list(bars)


def fetch_stock() -> None:
    combined: dict[str, list[Mapping[str, Any]]] = {}
    page_counts: dict[str, int] = {}
    for symbol in SYMBOLS:
        pages = _fetch_pages(
            (
                "data",
                "bars",
                "--symbol",
                symbol,
                "--start",
                START,
                "--end",
                END,
                "--timeframe",
                "5Min",
                "--feed",
                "iex",
                "--adjustment",
                "raw",
                "--sort",
                "asc",
                "--limit",
                "10000",
            )
        )
        rows: list[Mapping[str, Any]] = []
        for page in pages:
            rows.extend(stock_page_rows(page, symbol))
        combined[symbol] = rows
        page_counts[symbol] = len(pages)
    _write_json(
        STOCK_CACHE,
        {
            "provenance": {
                "source": "Alpaca CLI historical stock bars",
                "profile": PROFILE,
                "feed": "iex",
                "timeframe": "5Min",
                "adjustment": "raw",
                "start": START,
                "end": END,
                "page_counts": page_counts,
            },
            "bars": combined,
        },
    )


def _parse_stock() -> dict[str, tuple[Bar, ...]]:
    payload = json.loads(STOCK_CACHE.read_text(encoding="utf-8"))
    parsed: dict[str, tuple[Bar, ...]] = {}
    for symbol in SYMBOLS:
        rows: list[Bar] = []
        for raw in payload["bars"][symbol]:
            timestamp = datetime.fromisoformat(raw["t"].replace("Z", "+00:00"))
            local = timestamp.astimezone(NEW_YORK)
            minute = local.hour * 60 + local.minute
            if local.weekday() >= 5 or not (9 * 60 + 30 <= minute < 16 * 60):
                continue
            rows.append(
                Bar(
                    timestamp,
                    float(raw["o"]),
                    float(raw["h"]),
                    float(raw["l"]),
                    float(raw["c"]),
                    float(raw["v"]),
                )
            )
        parsed[symbol] = tuple(sorted(rows, key=lambda row: row.timestamp))
    return parsed


def fetch_options(signals_by_variant: Mapping[str, Sequence[Signal]]) -> None:
    symbols = sorted(
        {
            contract
            for signals in signals_by_variant.values()
            for signal in signals
            for contract in contract_pair(signal)
        }
    )
    combined: dict[str, list[Mapping[str, Any]]] = {symbol: [] for symbol in symbols}
    page_count = 0
    for chunk in _chunks(symbols, 80):
        pages = _fetch_pages(
            (
                "data",
                "option",
                "bars",
                "--symbols",
                ",".join(chunk),
                "--start",
                START,
                "--end",
                END,
                "--timeframe",
                "5Min",
                "--sort",
                "asc",
                "--limit",
                "10000",
            )
        )
        page_count += len(pages)
        for page in pages:
            for symbol, rows in (page.get("bars") or {}).items():
                combined.setdefault(symbol, []).extend(rows)
    _write_json(
        OPTION_CACHE,
        {
            "provenance": {
                "source": "Alpaca CLI historical option bars",
                "profile": PROFILE,
                "timeframe": "5Min",
                "start": START,
                "end": END,
                "requested_symbol_count": len(symbols),
                "page_count": page_count,
            },
            "bars": combined,
        },
    )


def _evaluate(
    signals_by_variant: Mapping[str, Sequence[Signal]],
) -> tuple[dict[str, tuple[EvaluatedTrendTrade, ...]], dict[str, int]]:
    payload = json.loads(OPTION_CACHE.read_text(encoding="utf-8"))
    lookup = {variant.name: variant for variant in VARIANTS}
    evaluated: dict[str, tuple[EvaluatedTrendTrade, ...]] = {}
    missing: dict[str, int] = {}
    for name, signals in signals_by_variant.items():
        rows: list[EvaluatedTrendTrade] = []
        missed = 0
        for signal in signals:
            long_symbol, short_symbol = contract_pair(signal)
            paired = pair_option_bars(payload, long_symbol, short_symbol)
            params = lookup[name].parameters
            try:
                trade: BracketTrade = bracket_round_trip(
                    signal.completed_at,
                    paired,
                    COSTS,
                    params.risk_fraction,
                    params.target_r,
                    params.max_holding_bars,
                )
            except ValueError:
                missed += 1
                continue
            rows.append(
                EvaluatedTrendTrade(
                    session=signal.signal_bar_start.date(),
                    variant=name,
                    direction=signal.direction,
                    signal_at=signal.signal_bar_start,
                    completed_at=signal.completed_at,
                    long_symbol=long_symbol,
                    short_symbol=short_symbol,
                    entry_at=trade.entry_at,
                    exit_at=trade.exit_at,
                    entry_debit=trade.entry_debit,
                    exit_credit=trade.exit_credit,
                    risk_dollars=trade.risk_dollars,
                    net_pnl=trade.net_pnl,
                    return_r=trade.return_r,
                    exit_reason=trade.exit_reason,
                    operational_target_stop=trade.operational_target_stop,
                )
            )
        evaluated[name] = tuple(rows)
        missing[name] = missed
    return evaluated, missing


def _metrics(rows: Sequence[EvaluatedTrendTrade]) -> dict[str, Any]:
    result = performance(tuple(row.net_pnl for row in rows))
    result["expectancy_r"] = (
        sum((row.return_r for row in rows), Decimal(0)) / len(rows)
        if rows
        else Decimal(0)
    )
    wins = tuple(row.net_pnl for row in rows if row.net_pnl > 0)
    losses = tuple(-row.net_pnl for row in rows if row.net_pnl < 0)
    result["average_win"] = sum(wins, Decimal(0)) / len(wins) if wins else None
    result["average_loss"] = sum(losses, Decimal(0)) / len(losses) if losses else None
    result["realized_win_loss_ratio"] = (
        result["average_win"] / result["average_loss"] if wins and losses else None
    )
    result["exit_reasons"] = dict(Counter(row.exit_reason for row in rows))
    return result


def _choose_nested(
    evaluated: Mapping[str, Sequence[EvaluatedTrendTrade]],
    validation_dates: Sequence[date],
    minimum_samples: int = 2,
) -> tuple[str | None, dict[str, Any]]:
    allowed = set(validation_dates)
    diagnostics: dict[str, Any] = {}
    scores: list[tuple[Decimal, Decimal, str]] = []
    for name, all_rows in evaluated.items():
        rows = tuple(row for row in all_rows if row.session in allowed)
        metrics = _metrics(rows)
        diagnostics[name] = metrics
        if len(rows) < minimum_samples:
            continue
        expectancy = Decimal(metrics["expectancy_r"])
        net_pnl = Decimal(metrics["net_pnl"])
        scores.append((expectancy, net_pnl, name))
    if not scores:
        return None, diagnostics
    scores.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return scores[0][2], diagnostics


def _build_results(
    stock: Mapping[str, Sequence[Bar]],
    signals_by_variant: Mapping[str, Sequence[Signal]],
    evaluated: Mapping[str, Sequence[EvaluatedTrendTrade]],
    missing: Mapping[str, int],
) -> dict[str, Any]:
    sessions = tuple(
        sorted(
            set.intersection(
                *(set(row.timestamp.date() for row in stock[symbol]) for symbol in SYMBOLS)
            )
        )
    )
    outer_folds = make_rolling_folds(sessions, 30, 2, 10, 10)
    oos: list[EvaluatedTrendTrade] = []
    fold_results: list[dict[str, Any]] = []
    for number, fold in enumerate(outer_folds, start=1):
        inner_folds = make_rolling_folds(fold.train, 15, 2, 5, 5)
        validation_dates = tuple(day for inner in inner_folds for day in inner.test)
        selected, diagnostics = _choose_nested(evaluated, validation_dates)
        test_rows = (
            tuple(row for row in evaluated[selected] if row.session in set(fold.test))
            if selected
            else ()
        )
        oos.extend(test_rows)
        fold_results.append(
            {
                "fold": number,
                "train": {"start": fold.train[0], "end": fold.train[-1], "sessions": len(fold.train)},
                "outer_embargo": {
                    "start": fold.embargo[0],
                    "end": fold.embargo[-1],
                    "sessions": len(fold.embargo),
                },
                "test": {"start": fold.test[0], "end": fold.test[-1], "sessions": len(fold.test)},
                "inner_validation_dates": validation_dates,
                "selected_variant": selected,
                "inner_validation_diagnostics": diagnostics,
                "oos": _metrics(test_rows),
            }
        )
    variants = {}
    for variant in VARIANTS:
        rows = evaluated[variant.name]
        variants[variant.name] = {
            "parameters": asdict(variant.parameters),
            "signals": len(signals_by_variant[variant.name]),
            "unscored_missing_or_illiquid": missing[variant.name],
            "full_sample_diagnostic_not_oos": _metrics(rows),
        }
    return {
        "schema_version": 1,
        "attempt": "002_cross_index_vwap_trend",
        "strategy": "SPY 3+DTE debit verticals on cross-index VWAP trend persistence",
        "data": {
            "start": START,
            "end": END,
            "symbols": SYMBOLS,
            "stock_source": "Alpaca IEX 5-minute bars",
            "option_source": "Alpaca 5-minute option trade bars",
            "shared_sessions": len(sessions),
            "stock_bars": {symbol: len(stock[symbol]) for symbol in SYMBOLS},
            "stock_cache_sha256": _sha256(STOCK_CACHE),
            "option_cache_sha256": _sha256(OPTION_CACHE),
        },
        "method": {
            "signal": "fixed-time SPY session return + recent trend + VWAP side, confirmed by QQQ/IWM",
            "timing": "signal known at completed stock bar; enter after next synchronized option bar completes",
            "instrument": "one-lot directional SPY $5-wide debit vertical, first weekday expiry >=3 calendar DTE",
            "costs": "$0.03 adverse slippage per option leg per side and $0.65/contract/side",
            "bracket": "stop threshold -1R and target +3R after all modeled fees; close-confirmed, adverse stop gaps retained",
            "outer_validation": "30-session rolling train, 2-session embargo, unique 10-session OOS, step 10",
            "nested_selection": "two inner 15-train/2-embargo/5-validation rolls; choose validation expectancy/R, min 2",
        },
        "variants": variants,
        "folds": fold_results,
        "oos": {"statistics": _metrics(oos), "trades": [asdict(row) for row in oos]},
        "criteria": {
            "operational_target_stop_minimum": Decimal("3"),
            "profit_factor_target": Decimal("3"),
            "meets_operational_target_stop": all(row.operational_target_stop >= 3 for row in oos),
            "meets_profit_factor_target": (
                _metrics(oos)["profit_factor"] is not None
                and _metrics(oos)["profit_factor"] >= 3
            ),
        },
    }


def _render_report(results: Mapping[str, Any]) -> str:
    stats = results["oos"]["statistics"]
    criteria = results["criteria"]
    profit_factor = stats["profit_factor"] if stats["profit_factor"] is not None else "undefined"
    lines = [
        "# Cross-index VWAP trend-persistence option candidate",
        "",
        "## Rolling OOS decision",
        "",
        f"Nested rolling OOS: **{stats['sample_size']} trades**, **${stats['net_pnl']} net P&L**, "
        f"**{Decimal(str(stats['expectancy_r'])):.4f} R expectancy**, "
        f"**{Decimal(str(stats['hit_rate'])):.1%} hit rate**, **{profit_factor} profit factor**, "
        f"and **${stats['max_drawdown']} max drawdown**.",
        "",
        f"Operational target:stop is 3.0 after modeled costs: **{criteria['meets_operational_target_stop']}**. "
        f"Rolling-OOS profit factor target >=3.0: **{criteria['meets_profit_factor_target']}**.",
        "",
        "## Outer rolling folds",
        "",
        "| Fold | Train | Embargo | OOS | Selected | n | Net | Exp/R | PF | Hit | DD |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for fold in results["folds"]:
        metric = fold["oos"]
        pf = metric["profit_factor"] if metric["profit_factor"] is not None else "n/a"
        lines.append(
            f"| {fold['fold']} | {fold['train']['start']}..{fold['train']['end']} | "
            f"{fold['outer_embargo']['start']}..{fold['outer_embargo']['end']} | "
            f"{fold['test']['start']}..{fold['test']['end']} | {fold['selected_variant']} | "
            f"{metric['sample_size']} | ${metric['net_pnl']} | {Decimal(str(metric['expectancy_r'])):.4f} | "
            f"{pf} | {Decimal(str(metric['hit_rate'])):.1%} | ${metric['max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## Implementation contract",
            "",
            "- At each predeclared time, SPY must agree with the required count of SPY/QQQ/IWM on session return direction, recent return direction, and side of session VWAP. All inputs are completed, timestamp-aligned five-minute bars.",
            "- The next synchronized SPY option bar is allowed to complete before entry. Both legs receive $0.03 adverse slippage on entry and exit plus $2.60 total contract fees.",
            "- The stop credit encodes -1R and target credit +3R after total costs. Stop gaps use the worse observed close; target fills receive no price improvement. Timeout exits retain observed adverse-slippage credit.",
            "- Each outer OOS slice is unique. Parameter selection uses only inner rolling validation dates inside the preceding rolling training window, separated by two-session inner and outer embargoes.",
            "- `order_dry_run.json` is non-submitting and ends in `--dry-run`. Any eventual paper order must wait for parent selection and normal warrant/risk gates.",
            "",
            "## Data limitations",
            "",
            "IEX is not the consolidated SIP. Alpaca historical option trade bars contain no bid/ask NBBO, so close plus explicit adverse leg slippage is a conservative proxy rather than quote replay. Unsynchronized/missing legs are excluded and counted; prices are never imputed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    arguments = parser.parse_args()
    if arguments.fetch or not STOCK_CACHE.exists():
        fetch_stock()
    stock = _parse_stock()
    signals = {
        variant.name: detect_cross_index_trend(stock, variant.parameters)
        for variant in VARIANTS
    }
    if arguments.fetch or not OPTION_CACHE.exists():
        fetch_options(signals)
    evaluated, missing = _evaluate(signals)
    results = _build_results(stock, signals, evaluated, missing)
    _write_json(RESULTS, results)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(_render_report(results), encoding="utf-8")
    example = next(iter(results["oos"]["trades"]), None)
    order = (
        build_dry_run_order(
            example["direction"],
            example["long_symbol"],
            example["short_symbol"],
            Decimal(example["entry_debit"]),
            "cross-index-trend-research-dry-run",
        )
        if example
        else {"submission_allowed": False, "reason": "no rolling-OOS trade"}
    )
    _write_json(ORDER_DRY_RUN, order)
    print(json.dumps(results["oos"]["statistics"], default=_json_default))


if __name__ == "__main__":
    main()
