#!/usr/bin/env python3
"""Acquire and evaluate the frozen attempt-006 family once on 2024 outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import DataExclusion, StockBar, UNIVERSE, enforce_non_overlapping, summarize
    from .equity_candidate import EquityCosts, EquityTrade, simulate_equity_trade
    from .qqq_regime_candidate import FOCAL_VARIANT, VARIANTS, QQQRegimeSignal, QQQRegimeVariant, qqq_regime_signal
    from .run_gap_research import _max_drawdown_r, _profit_concentration, admission_criteria
    from .run_research import ATTEMPT_LEDGER, ET, PROFILE, REPO, _paged_rows, _stock_objects, _write_json, canonical_hash
except ImportError:
    from candidate import DataExclusion, StockBar, UNIVERSE, enforce_non_overlapping, summarize  # type: ignore[no-redef]
    from equity_candidate import EquityCosts, EquityTrade, simulate_equity_trade  # type: ignore[no-redef]
    from qqq_regime_candidate import FOCAL_VARIANT, VARIANTS, QQQRegimeSignal, QQQRegimeVariant, qqq_regime_signal  # type: ignore[no-redef]
    from run_gap_research import _max_drawdown_r, _profit_concentration, admission_criteria  # type: ignore[no-redef]
    from run_research import ATTEMPT_LEDGER, ET, PROFILE, REPO, _paged_rows, _stock_objects, _write_json, canonical_hash  # type: ignore[no-redef]


HERE = Path(__file__).resolve().parent
FROZEN_FAMILY = HERE / "results" / "attempt006_frozen_family.json"
CACHE = HERE / "data" / "attempt006_market_cache.json"
OUTPUT = HERE / "results" / "attempt006_backtest.json"
REPORT = HERE / "ATTEMPT_006_REPORT.md"
CLI = REPO / ".tools" / "bin" / "alpaca"
ACQUISITION_START = datetime(2023, 11, 15, tzinfo=UTC)
ACQUISITION_END = datetime(2025, 1, 1, tzinfo=UTC)
VALIDATION_START = date(2024, 1, 2)
VALIDATION_END = date(2024, 12, 31)
STOCK_SYMBOLS = ("SPY", *UNIVERSE)
BASE_COSTS = EquityCosts(Decimal("0.0001"), Decimal("0.005"))
STRESSED_COSTS = EquityCosts(Decimal("0.00015"), Decimal("0.0075"))
PLUS_TWO_BPS_COSTS = EquityCosts(Decimal("0.0003"), Decimal("0.005"))


def _family_body(artifact: Mapping[str, Any]) -> dict[str, Any]:
    ignored = {"family_hash", "family_hash_scope", "source_hashes"}
    return {key: value for key, value in artifact.items() if key not in ignored}


def validate_family(artifact: Mapping[str, Any]) -> None:
    if canonical_hash(_family_body(artifact)) != str(artifact.get("family_hash", "")):
        raise ValueError("FROZEN_FAMILY_HASH_MISMATCH")
    for name, expected in artifact.get("source_hashes", {}).items():
        observed = hashlib.sha256((HERE / str(name)).read_bytes()).hexdigest()
        if observed != str(expected):
            raise ValueError("FROZEN_SOURCE_HASH_MISMATCH")


def _validate_cache(cache: Mapping[str, Any]) -> None:
    body = {key: value for key, value in cache.items() if key != "content_hash"}
    if canonical_hash(body) != str(cache.get("content_hash", "")):
        raise ValueError("MARKET_CACHE_HASH_MISMATCH")


def acquire(*, executable: Path, profile: str, output: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    commands: list[list[str]] = []
    for symbol in STOCK_SYMBOLS:
        received, used = _paged_rows(
            executable,
            profile,
            (
                "data", "bars", "--symbol", symbol,
                "--start", ACQUISITION_START.isoformat(), "--end", ACQUISITION_END.isoformat(),
                "--timeframe", "15Min", "--feed", "iex", "--adjustment", "raw",
                "--sort", "asc", "--limit", "10000",
            ),
            result_key="bars",
        )
        rows.extend(received)
        commands.extend(used)
    body = {
        "schema_version": "afterimage-attempt006-market-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only data/bars endpoint",
        "feed": "iex",
        "timeframe": "15Min",
        "adjustment": "raw",
        "acquisition_window": {"start": ACQUISITION_START, "end_exclusive": ACQUISITION_END},
        "validation_window": {"start": VALIDATION_START, "end": VALIDATION_END},
        "bars": sorted(rows, key=lambda item: (str(item.get("t")), str(item.get("symbol")))),
        "source_commands": commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    _write_json(output, result)
    return result


def _spy_closes(stock: Sequence[StockBar]) -> tuple[tuple[date, Decimal], ...]:
    grouped: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        if bar.symbol == "SPY":
            grouped[bar.timestamp.astimezone(ET).date()].append(bar)
    return tuple(
        (session, max(rows, key=lambda item: item.timestamp).close)
        for session, rows in sorted(grouped.items())
    )


def _signals(stock: Sequence[StockBar]) -> dict[str, tuple[QQQRegimeSignal, ...]]:
    by_date: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        if bar.symbol in UNIVERSE:
            by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    daily = _spy_closes(stock)
    dates = sorted(by_date)
    result: dict[str, list[QQQRegimeSignal]] = {variant.name: [] for variant in VARIANTS}
    for index, session in enumerate(dates):
        if index == 0 or not VALIDATION_START <= session <= VALIDATION_END:
            continue
        window = (*by_date[dates[index - 1]], *by_date[session])
        for variant in VARIANTS:
            try:
                signal = qqq_regime_signal(variant, window, daily, session)
            except DataExclusion:
                continue
            if signal is not None:
                result[variant.name].append(signal)
    return {name: tuple(rows) for name, rows in result.items()}


def _evaluate(
    signals: Mapping[str, Sequence[QQQRegimeSignal]],
    stock: Sequence[StockBar],
    costs: EquityCosts,
    *,
    delay_bars: int = 0,
) -> dict[str, tuple[EquityTrade, ...]]:
    by_date: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    lookup = {variant.name: variant for variant in VARIANTS}
    result: dict[str, tuple[EquityTrade, ...]] = {}
    for name, items in signals.items():
        trades: list[EquityTrade] = []
        for signal in items:
            delayed = replace(signal, completed_at=signal.completed_at + timedelta(minutes=15 * delay_bars))
            try:
                trades.append(simulate_equity_trade(delayed, by_date[signal.session], lookup[name], costs))  # type: ignore[arg-type]
            except DataExclusion:
                continue
        result[name] = enforce_non_overlapping(trades)  # type: ignore[arg-type,assignment]
    return result


def _metrics(rows: Sequence[EquityTrade]) -> dict[str, Any]:
    return {
        **asdict(summarize(rows)),
        "max_drawdown_r": _max_drawdown_r(rows),  # type: ignore[arg-type]
        "largest_win_fraction_of_gross_profit": _profit_concentration(rows),  # type: ignore[arg-type]
        "minimum_after_cost_target_to_stop": min((row.target_to_stop for row in rows), default=Decimal(0)),
    }


def _month_metrics(rows: Sequence[EquityTrade]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[EquityTrade]] = defaultdict(list)
    for row in rows:
        grouped[row.session.strftime("%Y-%m")].append(row)
    return {key: _metrics(values) for key, values in sorted(grouped.items())}


def _regime_metrics(
    rows: Sequence[EquityTrade], signals: Sequence[QQQRegimeSignal]
) -> dict[str, dict[str, Any]]:
    regimes = {signal.session: signal.regime for signal in signals}
    grouped: dict[str, list[EquityTrade]] = defaultdict(list)
    for row in rows:
        grouped[regimes[row.session]].append(row)
    return {key: _metrics(values) for key, values in sorted(grouped.items())}


def evaluate(cache: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    validate_family(artifact)
    _validate_cache(cache)
    stock = _stock_objects(cache["bars"])
    signals = _signals(stock)
    base = _evaluate(signals, stock, BASE_COSTS)
    stressed = _evaluate(signals, stock, STRESSED_COSTS)
    plus_two_bps = _evaluate(signals, stock, PLUS_TWO_BPS_COSTS)
    delayed = _evaluate(signals, stock, BASE_COSTS, delay_bars=1)
    focal = base[FOCAL_VARIANT.name]
    focal_metrics = _metrics(focal)
    months = _month_metrics(focal)
    regimes = _regime_metrics(focal, signals[FOCAL_VARIANT.name])
    positive_month_fraction = Decimal(sum(row["net_pnl"] > 0 for row in months.values())) / Decimal(len(months) or 1)
    positive_regimes = sum(row["net_pnl"] > 0 for row in regimes.values())
    neighbors = [variant for variant in VARIANTS if variant.name != FOCAL_VARIANT.name]
    positive_neighbor_fraction = Decimal(sum(_metrics(base[item.name])["net_pnl"] > 0 for item in neighbors)) / Decimal(len(neighbors))
    stress_metrics = _metrics(stressed[FOCAL_VARIANT.name])
    admission = admission_criteria(
        target_stop_ratio=Decimal(str(focal_metrics["minimum_after_cost_target_to_stop"])),
        profit_factor=Decimal(str(focal_metrics["profit_factor"])),
        expectancy_r=Decimal(str(focal_metrics["expectancy_r"])),
        sample_count=int(focal_metrics["sample_count"]),
        max_drawdown_r=Decimal(str(focal_metrics["max_drawdown_r"])),
        positive_underlyings=1 if focal_metrics["net_pnl"] > 0 else 0,
        positive_regimes=positive_regimes,
        positive_month_fraction=positive_month_fraction,
        stressed_net_pnl=Decimal(str(stress_metrics["net_pnl"])),
        positive_neighbor_fraction=positive_neighbor_fraction,
        largest_win_fraction=Decimal(str(focal_metrics["largest_win_fraction_of_gross_profit"])),
    )
    variants = {}
    for variant in VARIANTS:
        variants[variant.name] = {
            "parameters": asdict(variant),
            "role": "focal" if variant == FOCAL_VARIANT else "neighbor_only_no_selection",
            "fresh_2024_metrics": _metrics(base[variant.name]),
            "fresh_2024_trades": [asdict(row) for row in base[variant.name]],
            "stressed_1_5x_costs": _metrics(stressed[variant.name]),
        }
    result = {
        "schema_version": "afterimage-attempt006-fresh-outcome-validation-v1",
        "attempt_id": "qqq_regime_gap_v6",
        "family": "QQQ-only regime-conditioned sector-confirmed overnight-gap continuation",
        "family_hash": artifact["family_hash"],
        "focal_variant": FOCAL_VARIANT.name,
        "provenance": {
            "label": "fresh 2024 outcome validation; no 2024 trade outcome or metric used in design; not untouched-data validation",
            "caveat": artifact["fresh_outcome_validation"]["provenance_caveat"],
            "window": {"start": VALIDATION_START, "end": VALIDATION_END},
            "evaluations": 1,
            "source": cache["source"],
            "cache_hash": cache["content_hash"],
            "feed": cache["feed"],
            "timeframe": cache["timeframe"],
            "selection_on_2024": False,
        },
        "focal": {
            "metrics": focal_metrics,
            "month_metrics": months,
            "positive_month_fraction": positive_month_fraction,
            "regime_metrics": regimes,
            "positive_regime_count": positive_regimes,
            "stressed_1_5x_costs": stress_metrics,
            "plus_two_bps_slippage_each_side": _metrics(plus_two_bps[FOCAL_VARIANT.name]),
            "one_extra_15_minute_entry_bar": _metrics(delayed[FOCAL_VARIANT.name]),
        },
        "neighbor_positive_fraction": positive_neighbor_fraction,
        "variants": variants,
        "admission": admission,
        "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "limitations": [
            "Some late-2024 bars existed previously as warm-up inputs, though no 2024 trade outcome or metric was evaluated before the family freeze.",
            "This is a backward outcome validation, not chronological forward OOS.",
            "IEX 15-minute OHLC is not SIP and lacks intrabar ordering; stop-first is conservative.",
            "Historical QQQ short availability, borrow fees, market impact, and queue position are not modeled.",
        ],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _fmt(value: Any, digits: int = 2) -> str:
    return f"{Decimal(str(value)):.{digits}f}"


def report(result: Mapping[str, Any]) -> str:
    focal = result["focal"]["metrics"]
    lines = [
        "# Attempt 006 — QQQ regime-conditioned gap continuation",
        "",
        f"**{result['decision']}**. Frozen focal `{result['focal_variant']}` on the once-evaluated 2024 outcomes: n={focal['sample_count']}, net=${focal['net_pnl']}, expectancy={_fmt(focal['expectancy_r'], 3)}R, PF={_fmt(focal['profit_factor'])}, hit={Decimal(str(focal['hit_rate'])):.1%}, max DD={_fmt(focal['max_drawdown_r'])}R.",
        "",
        f"Family hash: `{result['family_hash']}`. {result['provenance']['label']}.",
        "",
        "## Admission audit",
        "",
        "| Criterion | Pass |",
        "|---|---|",
        *[f"| {key} | {value} |" for key, value in result["admission"]["criteria"].items()],
        "",
        "## Frozen focal and predeclared neighbors",
        "",
        "| Role | Variant | n | Net P&L | Exp/R | PF | Hit | Max DD/R | 1.5x-cost P&L |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in result["variants"].items():
        row = item["fresh_2024_metrics"]
        stressed = item["stressed_1_5x_costs"]
        lines.append(
            f"| {item['role']} | `{name}` | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} | {Decimal(str(row['hit_rate'])):.1%} | {_fmt(row['max_drawdown_r'])} | ${stressed['net_pnl']} |"
        )
    lines.extend([
        "",
        "## Focal execution stress",
        "",
        "| Scenario | n | Net P&L | Exp/R | PF | Max DD/R |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for label, key in (
        ("1.5x modeled costs", "stressed_1_5x_costs"),
        ("+2 bp slippage per side", "plus_two_bps_slippage_each_side"),
        ("one extra 15-minute entry bar", "one_extra_15_minute_entry_bar"),
    ):
        row = result["focal"][key]
        lines.append(f"| {label} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} | {_fmt(row['max_drawdown_r'])} |")
    lines.extend(["", "## Month stability", "", "| Month | n | Net P&L | Exp/R | PF |", "|---|---:|---:|---:|---:|"])
    for key, row in result["focal"]["month_metrics"].items():
        lines.append(f"| {key} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend(["", "## Regime stability", "", "| Regime | n | Net P&L | Exp/R | PF |", "|---|---:|---:|---:|---:|"])
    for key, row in result["focal"]["regime_metrics"].items():
        lines.append(f"| {key} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend(["", "## Limitations", "", *[f"- {item}" for item in result["limitations"]], ""])
    return "\n".join(lines)


def _update_ledger(result: Mapping[str, Any], artifact: Mapping[str, Any]) -> None:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    ledger.pop("ledger_hash", None)
    attempts = [item for item in ledger["attempts"] if item.get("attempt_id") != result["attempt_id"]]
    attempts.append({
        "attempt_id": result["attempt_id"],
        "status": "evaluated",
        "spec": "ATTEMPT_006_SPEC.md",
        "instrument": "QQQ shares only",
        "family_hash": result["family_hash"],
        "focal_variant": result["focal_variant"],
        "predeclared_family": artifact["rules"]["variants"],
        "fresh_outcome_validation": result["provenance"],
        "focal_metrics": result["focal"]["metrics"],
        "admission": result["admission"],
        "recommendation": result["decision"],
        "result_hash": result["result_hash"],
    })
    ledger["attempts"] = attempts
    ledger["ledger_hash"] = canonical_hash(ledger)
    _write_json(ATTEMPT_LEDGER, ledger)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--cli", type=Path, default=CLI)
    args = parser.parse_args()
    artifact = json.loads(FROZEN_FAMILY.read_text(encoding="utf-8"))
    validate_family(artifact)
    cache = acquire(executable=args.cli, profile=args.profile, output=CACHE) if args.fetch else json.loads(CACHE.read_text(encoding="utf-8"))
    result = evaluate(cache, artifact)
    _write_json(OUTPUT, result)
    REPORT.write_text(report(result), encoding="utf-8")
    _update_ledger(result, artifact)
    print(json.dumps({"decision": result["decision"], "family_hash": result["family_hash"], "focal": result["focal"]["metrics"], "admission": result["admission"]["criteria"]}, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
