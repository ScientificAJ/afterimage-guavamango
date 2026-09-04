#!/usr/bin/env python3
"""Develop the fixed attempt-008 family on already-revealed 2023-2025 bars."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import ET, ScoredTrade, StockBar, enforce_non_overlapping, select_on_training, summarize
    from .multiday_rotation_candidate import DailyBar, MultiDayCosts, MultiDayTrade, RotationSignal, VARIANTS, rotation_signal, simulate_multiday_trade
    from .run_gap_research import _max_drawdown_r, _profit_concentration
    from .run_research import _stock_objects, _write_json, canonical_hash
except ImportError:
    from candidate import ET, ScoredTrade, StockBar, enforce_non_overlapping, select_on_training, summarize  # type: ignore[no-redef]
    from multiday_rotation_candidate import DailyBar, MultiDayCosts, MultiDayTrade, RotationSignal, VARIANTS, rotation_signal, simulate_multiday_trade  # type: ignore[no-redef]
    from run_gap_research import _max_drawdown_r, _profit_concentration  # type: ignore[no-redef]
    from run_research import _stock_objects, _write_json, canonical_hash  # type: ignore[no-redef]


HERE = Path(__file__).resolve().parent
CACHES = (
    HERE / "data" / "attempt007_market_cache.json",
    HERE / "data" / "attempt006_market_cache.json",
    HERE / "data" / "frozen_extension_2025.json",
)
OUTPUT = HERE / "results" / "attempt008_development.json"
REPORT = HERE / "ATTEMPT_008_DEVELOPMENT.md"
START = date(2023, 1, 3)
END = date(2025, 12, 31)
BASE_COSTS = MultiDayCosts(Decimal("0.0001"), Decimal("0.005"))
STRESSED_COSTS = MultiDayCosts(Decimal("0.00015"), Decimal("0.0075"))


def load_stock() -> tuple[StockBar, ...]:
    raw: dict[tuple[str, str], Mapping[str, Any]] = {}
    for path in CACHES:
        cache = json.loads(path.read_text(encoding="utf-8"))
        body = {key: value for key, value in cache.items() if key != "content_hash"}
        if canonical_hash(body) != str(cache.get("content_hash", "")):
            raise ValueError(f"CACHE_HASH_MISMATCH:{path.name}")
        for item in cache["bars"]:
            raw[(str(item.get("symbol")), str(item.get("t")))] = item
    return _stock_objects(tuple(raw.values()))


def aggregate_daily(stock: Sequence[StockBar]) -> tuple[DailyBar, ...]:
    grouped: dict[tuple[str, date], list[StockBar]] = defaultdict(list)
    for bar in stock:
        grouped[(bar.symbol, bar.timestamp.astimezone(ET).date())].append(bar)
    result = []
    for (symbol, session), rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda item: item.timestamp)
        result.append(DailyBar(
            symbol=symbol,
            session=session,
            timestamp=datetime.combine(session, time(16), ET),
            open=ordered[0].open,
            high=max(item.high for item in ordered),
            low=min(item.low for item in ordered),
            close=ordered[-1].close,
            volume=sum(item.volume for item in ordered),
        ))
    return tuple(result)


def _signals(daily: Sequence[DailyBar]) -> dict[str, tuple[RotationSignal, ...]]:
    sessions = sorted({bar.session for bar in daily if START <= bar.session <= END})
    result: dict[str, list[RotationSignal]] = {variant.name: [] for variant in VARIANTS}
    for session in sessions:
        for variant in VARIANTS:
            try:
                signal = rotation_signal(variant, daily, session)
            except ValueError:
                continue
            if signal is not None:
                result[variant.name].append(signal)
    return {name: tuple(rows) for name, rows in result.items()}


def _evaluate(
    signals: Mapping[str, Sequence[RotationSignal]],
    daily: Sequence[DailyBar],
    costs: MultiDayCosts,
) -> dict[str, tuple[MultiDayTrade, ...]]:
    lookup = {variant.name: variant for variant in VARIANTS}
    result = {}
    for name, rows in signals.items():
        trades = []
        for signal in rows:
            try:
                trades.append(simulate_multiday_trade(signal, daily, lookup[name], costs))
            except ValueError:
                continue
        result[name] = enforce_non_overlapping(trades)  # type: ignore[arg-type,assignment]
    return result


def _metrics(rows: Sequence[MultiDayTrade]) -> dict[str, Any]:
    return {
        **asdict(summarize(rows)),
        "max_drawdown_r": _max_drawdown_r(rows),  # type: ignore[arg-type]
        "largest_win_fraction_of_gross_profit": _profit_concentration(rows),  # type: ignore[arg-type]
        "minimum_after_cost_target_to_stop": min((row.target_to_stop for row in rows), default=Decimal(0)),
    }


def evaluate() -> dict[str, Any]:
    daily = aggregate_daily(load_stock())
    signals = _signals(daily)
    base = _evaluate(signals, daily, BASE_COSTS)
    stressed = _evaluate(signals, daily, STRESSED_COSTS)
    scored = {
        name: tuple(ScoredTrade(row.session, row.return_r, row.net_pnl) for row in rows)
        for name, rows in base.items()
    }
    folds = []
    for validation_year, minimum in ((2024, 20), (2025, 40)):
        training_dates = tuple(sorted({row.session for rows in scored.values() for row in rows if row.session.year < validation_year}))
        selected = select_on_training(scored, training_dates, minimum_samples=minimum)
        validation = tuple(row for row in base.get(selected or "", ()) if row.session.year == validation_year)
        folds.append({
            "validation_year": validation_year,
            "selected_variant": selected,
            "training_end": date(validation_year - 1, 12, 31),
            "validation_metrics": _metrics(validation),
        })
    all_dates = tuple(sorted({row.session for rows in scored.values() for row in rows}))
    selected = select_on_training(scored, all_dates, minimum_samples=60)
    variants = {}
    for variant in VARIANTS:
        rows = base[variant.name]
        variants[variant.name] = {
            "parameters": asdict(variant),
            "development_metrics": _metrics(rows),
            "year_metrics": {str(year): _metrics(tuple(row for row in rows if row.session.year == year)) for year in (2023, 2024, 2025)},
            "stressed_1_5x_costs": _metrics(stressed[variant.name]),
        }
    rolling = []
    for fold in folds:
        rolling.extend(row for row in base.get(fold["selected_variant"] or "", ()) if row.session.year == fold["validation_year"])
    result = {
        "schema_version": "afterimage-attempt008-development-v1",
        "attempt_id": "multiday_cross_sectional_rotation_v8",
        "scope": "development only on already-revealed 2023-2025; no 2022 outcome evaluated",
        "family_spec": "ATTEMPT_008_SPEC.md",
        "family_variants": [asdict(variant) for variant in VARIANTS],
        "folds": folds,
        "rolling_development_validation": _metrics(tuple(sorted(rolling, key=lambda row: row.session))),
        "final_selected_variant": selected,
        "final_selection_rule": "minimum 60 trades; expectancy/R, net P&L, lexical name",
        "variants": variants,
    }
    result["result_hash"] = canonical_hash(result)
    return result


def report(result: Mapping[str, Any]) -> str:
    lines = [
        "# Attempt 008 development — multi-day cross-sectional ETF momentum",
        "",
        f"Development-only selection: `{result['final_selected_variant']}`. No 2022 outcome was evaluated.",
        "",
        "## Expanding development folds",
        "",
        "| Validation year | Selected | n | Net P&L | Exp/R | PF | Max DD/R |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for fold in result["folds"]:
        row = fold["validation_metrics"]
        lines.append(f"| {fold['validation_year']} | `{fold['selected_variant']}` | {row['sample_count']} | ${row['net_pnl']} | {Decimal(str(row['expectancy_r'])):.3f} | {Decimal(str(row['profit_factor'])):.2f} | {Decimal(str(row['max_drawdown_r'])):.2f} |")
    lines.extend(["", "## Fixed family", "", "| Variant | n | Net P&L | Exp/R | PF | DD/R | 1.5x-cost P&L |", "|---|---:|---:|---:|---:|---:|---:|"])
    for name, item in result["variants"].items():
        row = item["development_metrics"]
        stressed = item["stressed_1_5x_costs"]
        lines.append(f"| `{name}` | {row['sample_count']} | ${row['net_pnl']} | {Decimal(str(row['expectancy_r'])):.3f} | {Decimal(str(row['profit_factor'])):.2f} | {Decimal(str(row['max_drawdown_r'])):.2f} | ${stressed['net_pnl']} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    result = evaluate()
    _write_json(OUTPUT, result)
    REPORT.write_text(report(result), encoding="utf-8")
    print(json.dumps({"selected": result["final_selected_variant"], "rolling": result["rolling_development_validation"], "variants": {name: item["development_metrics"] for name, item in result["variants"].items()}}, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
