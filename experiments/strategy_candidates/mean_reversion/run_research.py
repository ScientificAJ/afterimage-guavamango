#!/usr/bin/env python3
"""Reproduce the SPY failed-auction option-spread walk-forward experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from experiments.strategy_candidates.mean_reversion.candidate import (
    Bar,
    Costs,
    Parameters,
    Signal,
    build_dry_run_order,
    conservative_round_trip,
    detect_signals,
    make_walk_forward_folds,
    summarize,
)
from experiments.strategy_candidates.mean_reversion.research import (
    ScoredTrade,
    contract_pair,
    pair_option_bars,
    select_variant,
)


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = HERE / "data"
STOCK_CACHE = DATA / "spy_5min_2025-01-02_2025-04-30.json"
OPTION_CACHE = DATA / "option_5min_by_symbol.json"
RESULTS = HERE / "results.json"
REPORT = HERE / "report.md"
ORDER_DRY_RUN = HERE / "order_dry_run.json"
NEW_YORK = ZoneInfo("America/New_York")
PROFILE = "afterimage-paper"
START = "2025-01-02T09:00:00Z"
END = "2025-05-01T00:00:00Z"


@dataclass(frozen=True)
class Variant:
    name: str
    parameters: Parameters
    holding_bars: int


@dataclass(frozen=True)
class EvaluatedTrade:
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
    net_pnl: Decimal
    return_r: Decimal


VARIANTS = (
    Variant(
        "lb06_z1.50_w35_v100_r125_h03",
        Parameters(6, Decimal("1.50"), Decimal("0.35"), 30, 300, True, Decimal("1.00"), Decimal("1.25")),
        3,
    ),
    Variant(
        "lb06_z1.75_w40_v110_r100_h06",
        Parameters(6, Decimal("1.75"), Decimal("0.40"), 30, 300, True, Decimal("1.10"), Decimal("1.00")),
        6,
    ),
    Variant(
        "lb12_z1.50_w35_v100_r125_h03",
        Parameters(12, Decimal("1.50"), Decimal("0.35"), 30, 300, True, Decimal("1.00"), Decimal("1.25")),
        3,
    ),
    Variant(
        "lb12_z1.75_w40_v110_r100_h06",
        Parameters(12, Decimal("1.75"), Decimal("0.40"), 30, 300, True, Decimal("1.10"), Decimal("1.00")),
        6,
    ),
    Variant(
        "lb18_z1.75_w35_v100_r125_h06",
        Parameters(18, Decimal("1.75"), Decimal("0.35"), 30, 300, True, Decimal("1.00"), Decimal("1.25")),
        6,
    ),
    Variant(
        "lb18_z2.00_w45_v120_r100_h12",
        Parameters(18, Decimal("2.00"), Decimal("0.45"), 30, 300, True, Decimal("1.20"), Decimal("1.00")),
        12,
    ),
)
COSTS = Costs(slippage_per_leg=Decimal("0.03"), fee_per_contract=Decimal("0.65"))


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _alpaca_json(arguments: Sequence[str]) -> Mapping[str, Any]:
    command = [str(REPO / ".tools/bin/alpaca"), "--profile", PROFILE, *arguments, "--quiet"]
    completed = subprocess.run(
        command,
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        timeout=90,
    )
    return json.loads(completed.stdout)


def _fetch_pages(arguments: Sequence[str]) -> list[Mapping[str, Any]]:
    pages: list[Mapping[str, Any]] = []
    page_token: str | None = None
    while True:
        request = list(arguments)
        if page_token:
            request.extend(("--page-token", page_token))
        page = _alpaca_json(request)
        pages.append(page)
        page_token = page.get("next_page_token")
        if not page_token:
            return pages


def fetch_stock() -> None:
    pages = _fetch_pages(
        (
            "data",
            "bars",
            "--symbol",
            "SPY",
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
        page_bars = page.get("bars") or {}
        rows.extend(page_bars.get("SPY", []) if isinstance(page_bars, dict) else page_bars)
    _write_json(
        STOCK_CACHE,
        {
            "provenance": {
                "source": "Alpaca CLI historical stock bars",
                "profile": PROFILE,
                "feed": "iex",
                "adjustment": "raw",
                "timeframe": "5Min",
                "start": START,
                "end": END,
                "page_count": len(pages),
            },
            "bars": {"SPY": rows},
        },
    )


def _parse_stock() -> tuple[Bar, ...]:
    payload = json.loads(STOCK_CACHE.read_text(encoding="utf-8"))
    rows = payload["bars"]["SPY"]
    bars: list[Bar] = []
    for row in rows:
        timestamp = datetime.fromisoformat(row["t"].replace("Z", "+00:00"))
        local = timestamp.astimezone(NEW_YORK)
        minutes = local.hour * 60 + local.minute
        if local.weekday() >= 5 or not (9 * 60 + 30 <= minutes < 16 * 60):
            continue
        bars.append(
            Bar(
                timestamp=timestamp,
                open=float(row["o"]),
                high=float(row["h"]),
                low=float(row["l"]),
                close=float(row["c"]),
                volume=float(row["v"]),
            )
        )
    return tuple(sorted(bars, key=lambda item: item.timestamp))


def _eligible_signals(bars: Sequence[Bar], variant: Variant) -> tuple[Signal, ...]:
    return detect_signals(bars, variant.parameters)


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def fetch_options(signals_by_variant: Mapping[str, Sequence[Signal]]) -> None:
    symbols = sorted(
        {
            symbol
            for signals in signals_by_variant.values()
            for signal in signals
            for symbol in contract_pair(signal)
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
    fill_model: str,
) -> tuple[dict[str, tuple[EvaluatedTrade, ...]], dict[str, int]]:
    option_payload = json.loads(OPTION_CACHE.read_text(encoding="utf-8"))
    variant_lookup = {variant.name: variant for variant in VARIANTS}
    evaluated: dict[str, tuple[EvaluatedTrade, ...]] = {}
    missing: dict[str, int] = {}
    for name, signals in signals_by_variant.items():
        rows: list[EvaluatedTrade] = []
        missed = 0
        for signal in signals:
            long_symbol, short_symbol = contract_pair(signal)
            paired = pair_option_bars(option_payload, long_symbol, short_symbol)
            try:
                trade = conservative_round_trip(
                    signal.completed_at,
                    paired,
                    COSTS,
                    variant_lookup[name].holding_bars,
                    fill_model=fill_model,
                )
            except ValueError:
                missed += 1
                continue
            if trade.entry_debit <= 0 or trade.entry_debit >= Decimal("5"):
                missed += 1
                continue
            rows.append(
                EvaluatedTrade(
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
                    net_pnl=trade.net_pnl,
                    return_r=trade.return_r,
                )
            )
        evaluated[name] = tuple(rows)
        missing[name] = missed
    return evaluated, missing


def _statistics(rows: Sequence[EvaluatedTrade]) -> dict[str, Any]:
    stats = summarize(
        tuple(row.net_pnl for row in rows),
        tuple(row.return_r for row in rows),
    )
    return asdict(stats)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_results(
    stock: Sequence[Bar],
    signals_by_variant: Mapping[str, Sequence[Signal]],
    evaluated: Mapping[str, Sequence[EvaluatedTrade]],
    stress_evaluated: Mapping[str, Sequence[EvaluatedTrade]],
    missing: Mapping[str, int],
) -> dict[str, Any]:
    sessions = tuple(sorted({bar.timestamp.date() for bar in stock}))
    folds = make_walk_forward_folds(sessions, min_train=25, test_size=10, embargo=3)
    scored = {
        name: tuple(ScoredTrade(row.session, row.return_r, row.net_pnl) for row in rows)
        for name, rows in evaluated.items()
    }
    oos: list[EvaluatedTrade] = []
    stress_oos: list[EvaluatedTrade] = []
    fold_results: list[dict[str, Any]] = []
    for number, fold in enumerate(folds, start=1):
        chosen = select_variant(scored, fold.train, minimum_samples=5)
        test_rows = (
            tuple(row for row in evaluated[chosen] if row.session in set(fold.test))
            if chosen
            else ()
        )
        oos.extend(test_rows)
        stress_test_rows = (
            tuple(row for row in stress_evaluated[chosen] if row.session in set(fold.test))
            if chosen
            else ()
        )
        stress_oos.extend(stress_test_rows)
        fold_results.append(
            {
                "fold": number,
                "train": {"start": fold.train[0], "end": fold.train[-1], "sessions": len(fold.train)},
                "embargo": {
                    "start": fold.embargo[0],
                    "end": fold.embargo[-1],
                    "sessions": len(fold.embargo),
                },
                "test": {"start": fold.test[0], "end": fold.test[-1], "sessions": len(fold.test)},
                "selected_variant": chosen,
                "oos": _statistics(test_rows),
                "bar_extreme_stress_oos": _statistics(stress_test_rows),
            }
        )
    variant_results: dict[str, Any] = {}
    for variant in VARIANTS:
        rows = evaluated[variant.name]
        variant_results[variant.name] = {
            "parameters": {
                **asdict(variant.parameters),
                "holding_bars": variant.holding_bars,
            },
            "signals": len(signals_by_variant[variant.name]),
            "unscored_missing_or_illiquid": missing[variant.name],
            "full_sample_diagnostic_not_selection_oos": _statistics(rows),
        }
    return {
        "schema_version": 1,
        "strategy": "SPY intraday failed-auction mean reversion via 3+DTE $5 debit verticals",
        "data": {
            "stock_source": "Alpaca IEX 5-minute historical bars, raw adjustment",
            "option_source": "Alpaca 5-minute historical option trade bars",
            "start": START,
            "end": END,
            "stock_regular_session_bars": len(stock),
            "sessions": len(sessions),
            "stock_cache_sha256": _sha256(STOCK_CACHE),
            "option_cache_sha256": _sha256(OPTION_CACHE),
        },
        "method": {
            "signal": "first same-session z-score band excursion and wick rejection; signal known at bar end",
            "signal_window_new_york": "10:00-14:30",
            "entry": "close of first synchronized option 5-minute bar after signal completion",
            "entry_fill": "next-bar close on both legs plus $0.03 adverse slippage per leg",
            "exit_fill": "configured future-bar close on both legs plus $0.03 adverse slippage per leg",
            "fees": "$0.65 per contract per side ($2.60 round trip)",
            "stress_fill": "entry long high/short low and exit long low/short high, plus slippage and fees",
            "walk_forward": "expanding train, 3-session embargo, 10-session chronological OOS",
            "selection": "highest training-only expectancy/R, then net P&L, min 5 trades",
        },
        "variants": variant_results,
        "folds": fold_results,
        "oos": {
            "statistics": _statistics(oos),
            "trades": [asdict(row) for row in oos],
        },
        "bar_extreme_stress_oos": {
            "statistics": _statistics(stress_oos),
            "trades": [asdict(row) for row in stress_oos],
        },
    }


def _render_report(results: Mapping[str, Any]) -> str:
    oos = results["oos"]["statistics"]
    stress = results["bar_extreme_stress_oos"]["statistics"]
    lines = [
        "# Failed-auction mean-reversion option candidate",
        "",
        "## Decision-grade result",
        "",
        f"Chronological walk-forward OOS produced **{oos['sample_size']} trades**, "
        f"**${oos['net_pnl']} net P&L**, **{Decimal(str(oos['expectancy_r'])):.4f} R expectancy**, "
        f"**{Decimal(str(oos['hit_rate'])):.1%} hit rate**, and "
        f"**${oos['max_drawdown']} max drawdown**.",
        "",
        "This result is reported as measured, including if it is negative. It is a research candidate, not approval to submit an order.",
        "",
        f"The punitive bar-extreme stress case produced **{stress['sample_size']} trades**, "
        f"**${stress['net_pnl']} net P&L**, **{Decimal(str(stress['expectancy_r'])):.4f} R expectancy**, "
        f"and **${stress['max_drawdown']} max drawdown**.",
        "",
        "## Walk-forward folds",
        "",
        "| Fold | Train | Embargo | OOS | Selected | n | Net P&L | Exp/R | Hit | Max DD |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for fold in results["folds"]:
        stats = fold["oos"]
        lines.append(
            f"| {fold['fold']} | {fold['train']['start']}..{fold['train']['end']} | "
            f"{fold['embargo']['start']}..{fold['embargo']['end']} | "
            f"{fold['test']['start']}..{fold['test']['end']} | {fold['selected_variant']} | "
            f"{stats['sample_size']} | ${stats['net_pnl']} | {Decimal(str(stats['expectancy_r'])):.4f} | "
            f"{Decimal(str(stats['hit_rate'])):.1%} | ${stats['max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## Variant robustness (full-sample diagnostic only)",
            "",
            "Full-sample rows below are parameter-sensitivity diagnostics and were not used as OOS results.",
            "",
            "| Variant | Signals | Scored | Missing/illiquid | Net P&L | Exp/R | Hit | Max DD |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, variant in results["variants"].items():
        stats = variant["full_sample_diagnostic_not_selection_oos"]
        lines.append(
            f"| {name} | {variant['signals']} | {stats['sample_size']} | "
            f"{variant['unscored_missing_or_illiquid']} | ${stats['net_pnl']} | "
            f"{Decimal(str(stats['expectancy_r'])):.4f} | {Decimal(str(stats['hit_rate'])):.1%} | "
            f"${stats['max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## Implementation contract",
            "",
            "- Input: completed SPY 5-minute regular-session bars. Signal evaluation occurs only after the candidate bar closes.",
            "- Signal: first daily failed auction between 10:00 and 14:30 New York time; the bar must breach a trailing same-session z-band, close back inside it, and show the configured rejection wick.",
            "- Instrument: one-lot SPY $5-wide call debit spread for bullish signals or put debit spread for bearish signals; expiry is the first weekday at least three calendar days out.",
            "- Fill model: wait for the next synchronized option bar to complete, use both leg closes with $0.03 adverse slippage per leg and $0.65/contract/side fees. Missing paired bars are not imputed. A separate punitive stress case uses adverse high/low extremes on every leg.",
            "- Validation: expanding chronological training, three complete-session embargo, parameter selection on training trades only, then untouched ten-session OOS slices.",
            "- Execution: `order_dry_run.json` is non-submitting (`submission_allowed=false`, CLI ends in `--dry-run`). Any live paper submission remains serialized behind parent selection and the repository warrant/risk gates.",
            "",
            "## Limitations",
            "",
            "Alpaca option trade bars do not provide contemporaneous bid/ask or NBBO. The adverse high/low fill model is deliberately punitive, but it is not a substitute for quote-level replay. IEX stock bars are not the full SIP. Contract selection assumes standard weekday expiries and naturally records unavailable/holiday contracts as unscored rather than fabricating prices.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="refresh authenticated Alpaca caches")
    arguments = parser.parse_args()
    if arguments.fetch or not STOCK_CACHE.exists():
        fetch_stock()
    stock = _parse_stock()
    signals_by_variant = {
        variant.name: _eligible_signals(stock, variant) for variant in VARIANTS
    }
    if arguments.fetch or not OPTION_CACHE.exists():
        fetch_options(signals_by_variant)
    evaluated, missing = _evaluate(signals_by_variant, "next_bar_close")
    stress_evaluated, _ = _evaluate(signals_by_variant, "bar_extremes")
    results = _build_results(
        stock, signals_by_variant, evaluated, stress_evaluated, missing
    )
    _write_json(RESULTS, results)
    REPORT.write_text(_render_report(results), encoding="utf-8")

    example = next(iter(results["oos"]["trades"]), None)
    if example:
        limit_price = Decimal(example["entry_debit"])
        order = build_dry_run_order(
            example["direction"],
            example["long_symbol"],
            example["short_symbol"],
            limit_price,
            "mean-reversion-research-dry-run",
        )
    else:
        order = {
            "submission_allowed": False,
            "reason": "No OOS trade exists from which to construct a historical dry-run payload.",
        }
    _write_json(ORDER_DRY_RUN, order)
    print(json.dumps(results["oos"]["statistics"], default=_json_default))


if __name__ == "__main__":
    main()
