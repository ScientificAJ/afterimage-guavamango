#!/usr/bin/env python3
"""Direct-ETF execution comparison for the fixed multi-day trend family."""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.gap_expansion import UnderlyingSignal
from experiments.strategy_candidates.mean_reversion.multi_day_trend import detect_multi_day_trend
from experiments.strategy_candidates.mean_reversion.run_gap_expansion import _metrics, _selected_oos
from experiments.strategy_candidates.mean_reversion.run_multi_day_trend import (
    STOCK_CACHE,
    SYMBOLS,
    VARIANTS as OPTION_VARIANTS,
    _parse_stock,
)
from experiments.strategy_candidates.mean_reversion.run_research import _json_default, _sha256, _write_json
from experiments.strategy_candidates.mean_reversion.run_underlying_comparison import (
    EvaluatedUnderlyingTrade,
    UnderlyingVariant,
    evaluate_underlying,
)
from experiments.strategy_candidates.mean_reversion.trend_confirmation import make_rolling_folds
from experiments.strategy_candidates.mean_reversion.underlying_execution import (
    EquityCosts,
    build_equity_dry_run_order,
)


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "multi_day_underlying"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
BASE_COSTS = EquityCosts(Decimal("1.0"), Decimal("0.005"))
STRESS_COSTS = EquityCosts(Decimal("1.5"), Decimal("0.0075"))
VARIANTS = tuple(
    UnderlyingVariant(
        "d_" + variant.name,
        # CarryParameters and TrendParameters have different fields, but the evaluator
        # only consumes the variant name plus ATR/execution attributes.
        variant.signal,  # type: ignore[arg-type]
        atr_lookback=24 if variant.signal.lookback_sessions <= 5 else 48,
        atr_multiple=Decimal("4") if variant.signal.lookback_sessions <= 5 else Decimal("6"),
        max_holding_bars=variant.max_holding_bars * 3,
    )
    for variant in OPTION_VARIANTS
)


def _build_results(
    stock: Mapping[str, Sequence[Bar]],
    signals: Mapping[str, Sequence[UnderlyingSignal]],
    base: Mapping[str, Sequence[EvaluatedUnderlyingTrade]],
    stressed: Mapping[str, Sequence[EvaluatedUnderlyingTrade]],
    missing: Mapping[str, int],
) -> dict[str, Any]:
    sessions = tuple(
        sorted(
            set.intersection(
                *(set(row.timestamp.date() for row in stock[symbol]) for symbol in SYMBOLS)
            )
        )
    )
    folds = make_rolling_folds(sessions, 25, 2, 10, 10)
    oos, fold_results = _selected_oos(base, folds)
    stress_oos = [
        row
        for source, reported in zip(folds, fold_results, strict=True)
        for row in stressed.get(reported["selected_variant"], ())
        if row.session in set(source.test)
    ]
    oos_dates = {day for fold in folds for day in fold.test}
    neighbors = {
        name: _metrics(tuple(row for row in rows if row.session in oos_dates))
        for name, rows in base.items()
    }
    by_underlying = {
        symbol: _metrics(tuple(row for row in oos if row.underlying == symbol))
        for symbol in SYMBOLS
    }
    months = sorted({row.month for row in oos})
    by_month = {
        month: _metrics(tuple(row for row in oos if row.month == month)) for month in months
    }
    stats = _metrics(oos)
    stress_stats = _metrics(stress_oos)
    positive_folds = sum(Decimal(row["oos"]["net_pnl"]) > 0 for row in fold_results)
    positive_months = sum(Decimal(row["net_pnl"]) > 0 for row in by_month.values())
    positive_neighbors = sum(Decimal(row["net_pnl"]) > 0 for row in neighbors.values())
    gross_profit = Decimal(stats["gross_profit"])
    max_win = max((row.net_pnl for row in oos if row.net_pnl > 0), default=Decimal(0))
    criteria = {
        "target_stop_gte_3": bool(oos) and all(row.operational_target_stop >= 3 for row in oos),
        "profit_factor_gte_2": stats["profit_factor"] is not None and Decimal(stats["profit_factor"]) >= 2,
        "expectancy_gte_quarter_r": Decimal(stats["expectancy_r"]) >= Decimal("0.25"),
        "closed_oos_trades_gte_30": len(oos) >= 30,
        "max_drawdown_lte_6r": Decimal(stats["max_drawdown_r"]) <= 6,
        "positive_on_two_underlyings": sum(Decimal(row["net_pnl"]) > 0 for row in by_underlying.values()) >= 2,
        "positive_in_60pct_folds": Decimal(positive_folds) / len(fold_results) >= Decimal("0.60"),
        "positive_in_60pct_months": bool(months) and Decimal(positive_months) / len(months) >= Decimal("0.60"),
        "profitable_at_1_5x_costs": Decimal(stress_stats["net_pnl"]) > 0,
        "at_least_60pct_neighbors_positive": Decimal(positive_neighbors) / len(neighbors) >= Decimal("0.60"),
        "no_single_trade_gt_25pct_gross_profit": gross_profit > 0 and max_win <= gross_profit * Decimal("0.25"),
    }
    return {
        "schema_version": 1,
        "attempt": "006_multi_day_trend_direct_etf",
        "strategy": "multi-day cross-index trend carry executed directly in SPY/QQQ/IWM",
        "classification": "pseudo-OOS execution comparison against fixed attempt 004 signals",
        "data": {
            "source": "Alpaca IEX five-minute bars",
            "start": "2026-01-02",
            "end": "2026-04-30",
            "shared_sessions": len(sessions),
            "stock_cache_sha256": _sha256(STOCK_CACHE),
        },
        "method": {
            "signal": "14:45 completed N-session return confirmed across >=2 ETFs",
            "execution": "trade every confirming ETF after next five-minute bar completes; hold into subsequent sessions",
            "risk": "ATR-scaled stop, about $100 initial risk, after-cost +3R target",
            "costs": asdict(BASE_COSTS),
            "stress_costs_1_5x": asdict(STRESS_COSTS),
            "validation": "25-session rolling train, 2-session embargo, unique 10-session pseudo-OOS plus nested selection",
        },
        "variants": {
            variant.name: {
                "signal": asdict(OPTION_VARIANTS[index].signal),
                "atr_lookback": variant.atr_lookback,
                "atr_multiple": variant.atr_multiple,
                "max_holding_bars": variant.max_holding_bars,
                "signals": len(signals[variant.name]),
                "missing": missing[variant.name],
                "neighbor_oos": neighbors[variant.name],
            }
            for index, variant in enumerate(VARIANTS)
        },
        "folds": fold_results,
        "oos": {
            "statistics": stats,
            "by_underlying": by_underlying,
            "by_month": by_month,
            "trades": [asdict(row) for row in oos],
        },
        "stress_1_5x_cost_oos": {
            "statistics": stress_stats,
            "trades": [asdict(row) for row in stress_oos],
        },
        "admission": {"criteria": criteria, "admitted": all(criteria.values())},
    }


def _report(result: Mapping[str, Any]) -> str:
    stats = result["oos"]["statistics"]
    lines = [
        "# Multi-day trend: options versus direct ETF execution",
        "",
        "This is a pseudo-OOS execution comparison on attempt 004's fixed signal dates, not a fresh holdout.",
        "",
        f"Result: **{stats['sample_size']} trades**, **${stats['net_pnl']} net**, **{Decimal(str(stats['expectancy_r'])):.4f}R**, **PF {stats['profit_factor']}**, **{stats['max_drawdown_r']}R max drawdown**.",
        "",
        f"Admitted: **{result['admission']['admitted']}**.",
        "",
        "## Admission matrix",
        "",
        "| Criterion | Pass |",
        "|---|---:|",
    ]
    lines.extend(f"| {key} | {value} |" for key, value in result["admission"]["criteria"].items())
    lines.extend(
        [
            "",
            "## Implementation contract",
            "",
            "- Use the completed 14:45 New York five-minute bar and only completed prior sessions. Trade each ETF whose N-session direction participates in the required SPY/QQQ/IWM agreement.",
            "- Enter after the next five-minute bar closes with adverse slippage. Set an ATR-scaled after-cost -1R stop and +3R target, conservatively resolving same-bar ambiguity to the stop and retaining gap-through losses.",
            "- Hold across subsequent sessions up to the configured horizon. Base costs are 1 bp/side plus $0.005/share and stress is 1.5x.",
            "- OOS slices do not overlap; nested selection uses only earlier embargoed validation. This is an execution comparison, not a relabeled fresh holdout.",
            "- `order_dry_run.json` contains an exact non-submitting Alpaca bracket command ending in `--dry-run`.",
            "",
            "## Limitations",
            "",
            "IEX is not SIP. Five-minute OHLC requires a stop-first assumption for same-bar stop/target touches. ETF short borrow is not reconstructed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    stock = _parse_stock()
    signals = {
        variant.name: detect_multi_day_trend(stock, OPTION_VARIANTS[index].signal)
        for index, variant in enumerate(VARIANTS)
    }
    base, missing = evaluate_underlying(stock, signals, BASE_COSTS, VARIANTS)
    stressed, _ = evaluate_underlying(stock, signals, STRESS_COSTS, VARIANTS)
    result = _build_results(stock, signals, base, stressed, missing)
    _write_json(RESULTS, result)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(_report(result), encoding="utf-8")
    example = next(iter(result["oos"]["trades"]), None)
    order = (
        build_equity_dry_run_order(
            example["underlying"],
            example["direction"],
            example["quantity"],
            Decimal(example["entry_price"]),
            Decimal(example["target_price"]),
            Decimal(example["stop_price"]),
        )
        if example
        else {"submission_allowed": False, "reason": "no pseudo-OOS trade"}
    )
    _write_json(ORDER_DRY_RUN, order)
    print(json.dumps({"statistics": result["oos"]["statistics"], "admission": result["admission"]}, default=_json_default))


if __name__ == "__main__":
    main()
