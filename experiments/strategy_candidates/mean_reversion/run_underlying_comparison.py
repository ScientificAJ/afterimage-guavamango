#!/usr/bin/env python3
"""Pseudo-OOS execution-structure comparison using liquid index ETFs directly."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from experiments.strategy_candidates.mean_reversion.candidate import Bar
from experiments.strategy_candidates.mean_reversion.gap_expansion import UnderlyingSignal
from experiments.strategy_candidates.mean_reversion.run_cross_index_trend import (
    STOCK_CACHE,
    SYMBOLS,
    VARIANTS as OPTION_VARIANTS,
    _parse_stock,
)
from experiments.strategy_candidates.mean_reversion.run_gap_expansion import _metrics, _selected_oos
from experiments.strategy_candidates.mean_reversion.run_research import _json_default, _sha256, _write_json
from experiments.strategy_candidates.mean_reversion.trend_confirmation import (
    TrendParameters,
    detect_cross_index_underlying_trend,
    make_rolling_folds,
)
from experiments.strategy_candidates.mean_reversion.underlying_execution import (
    EquityCosts,
    build_equity_dry_run_order,
    underlying_bracket,
)


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "underlying_comparison"
RESULTS = OUTPUT / "results.json"
REPORT = OUTPUT / "report.md"
ORDER_DRY_RUN = OUTPUT / "order_dry_run.json"
BASE_COSTS = EquityCosts(Decimal("1.0"), Decimal("0.005"))
STRESS_COSTS = EquityCosts(Decimal("1.5"), Decimal("0.0075"))


@dataclass(frozen=True)
class UnderlyingVariant:
    name: str
    signal: TrendParameters
    atr_lookback: int
    atr_multiple: Decimal
    max_holding_bars: int


@dataclass(frozen=True)
class EvaluatedUnderlyingTrade:
    session: date
    month: str
    variant: str
    underlying: str
    direction: str
    signal_at: datetime
    completed_at: datetime
    entry_at: datetime
    exit_at: datetime
    entry_price: Decimal
    exit_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    quantity: int
    risk_dollars: Decimal
    net_pnl: Decimal
    return_r: Decimal
    exit_reason: str
    operational_target_stop: Decimal


VARIANTS = tuple(
    UnderlyingVariant(
        variant.name.replace("t", "u", 1),
        variant.parameters,
        atr_lookback=12 if variant.parameters.recent_lookback == 6 else 24,
        atr_multiple=Decimal("2") if variant.parameters.recent_lookback == 6 else Decimal("3"),
        max_holding_bars=variant.parameters.max_holding_bars,
    )
    for variant in OPTION_VARIANTS
)


def _risk_distance(
    bars: Sequence[Bar], signal: UnderlyingSignal, lookback: int, multiple: Decimal
) -> Decimal:
    history = tuple(row for row in bars if row.timestamp <= signal.signal.signal_bar_start)
    window = history[-lookback:]
    if len(window) < lookback:
        raise ValueError("insufficient ATR history")
    average_range = sum((Decimal(str(row.high - row.low)) for row in window), Decimal(0)) / len(window)
    return average_range * multiple


def evaluate_underlying(
    stock: Mapping[str, Sequence[Bar]],
    signals: Mapping[str, Sequence[UnderlyingSignal]],
    costs: EquityCosts,
    variants: Sequence[UnderlyingVariant] = VARIANTS,
) -> tuple[dict[str, tuple[EvaluatedUnderlyingTrade, ...]], dict[str, int]]:
    lookup = {variant.name: variant for variant in variants}
    output = {}
    missing = {}
    for name, signal_rows in signals.items():
        evaluated = []
        missed = 0
        variant = lookup[name]
        for item in signal_rows:
            try:
                risk_distance = _risk_distance(
                    stock[item.underlying], item, variant.atr_lookback, variant.atr_multiple
                )
                quantity = max(1, min(1000, int(Decimal("100") / risk_distance)))
                trade = underlying_bracket(
                    item.signal.completed_at,
                    stock[item.underlying],
                    item.signal.direction,
                    costs,
                    risk_distance,
                    quantity,
                    Decimal("3"),
                    variant.max_holding_bars,
                )
            except ValueError:
                missed += 1
                continue
            evaluated.append(
                EvaluatedUnderlyingTrade(
                    session=item.signal.signal_bar_start.date(),
                    month=item.signal.signal_bar_start.strftime("%Y-%m"),
                    variant=name,
                    underlying=item.underlying,
                    direction=item.signal.direction,
                    signal_at=item.signal.signal_bar_start,
                    completed_at=item.signal.completed_at,
                    entry_at=trade.entry_at,
                    exit_at=trade.exit_at,
                    entry_price=trade.entry_price,
                    exit_price=trade.exit_price,
                    stop_price=trade.stop_price,
                    target_price=trade.target_price,
                    quantity=trade.quantity,
                    risk_dollars=trade.risk_dollars,
                    net_pnl=trade.net_pnl,
                    return_r=trade.return_r,
                    exit_reason=trade.exit_reason,
                    operational_target_stop=trade.operational_target_stop,
                )
            )
        output[name] = tuple(evaluated)
        missing[name] = missed
    return output, missing


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
    folds = make_rolling_folds(sessions, 30, 2, 10, 10)
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
        "attempt": "005_cross_index_underlying_comparison",
        "strategy": "cross-index VWAP trend persistence executed in SPY/QQQ/IWM shares",
        "classification": "pseudo-OOS implementation comparison; same fixed signal dates as attempt 002, first direct-underlying evaluation",
        "data": {
            "source": "Alpaca IEX 5-minute bars",
            "start": "2025-05-01",
            "end": "2025-08-29",
            "shared_sessions": len(sessions),
            "stock_cache_sha256": _sha256(STOCK_CACHE),
        },
        "method": {
            "signal": "completed fixed-time session-return/recent-return/VWAP trend confirmed across SPY/QQQ/IWM",
            "execution": "trade every confirming ETF after the next five-minute bar closes",
            "risk": "$100 approximate initial risk per trade; ATR-scaled stop; +3R target solved after costs",
            "costs": asdict(BASE_COSTS),
            "stress_costs_1_5x": asdict(STRESS_COSTS),
            "validation": "30-session outer rolling train, 2-session embargo, unique 10-session pseudo-OOS with nested selection",
        },
        "variants": {
            variant.name: {
                "signal": asdict(variant.signal),
                "atr_lookback": variant.atr_lookback,
                "atr_multiple": variant.atr_multiple,
                "max_holding_bars": variant.max_holding_bars,
                "signals": len(signals[variant.name]),
                "missing": missing[variant.name],
                "neighbor_oos": neighbors[variant.name],
            }
            for variant in VARIANTS
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
        "# Cross-index trend: options versus direct ETF execution",
        "",
        "This is explicitly a pseudo-OOS execution comparison against attempt 002's fixed signal family, not a newly untouched holdout.",
        "",
        "## Direct-underlying result",
        "",
        f"**{stats['sample_size']} trades**, **${stats['net_pnl']} net**, **{Decimal(str(stats['expectancy_r'])):.4f}R expectancy**, **PF {stats['profit_factor']}**, and **{stats['max_drawdown_r']}R / ${stats['max_drawdown']} max drawdown**.",
        "",
        f"Admitted: **{result['admission']['admitted']}**.",
        "",
        "## Admission matrix",
        "",
        "| Criterion | Pass |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in result["admission"]["criteria"].items())
    lines.extend(
        [
            "",
            "## Implementation contract",
            "",
            "- Use completed, aligned SPY/QQQ/IWM five-minute bars. Require trend direction from session return, recent return, and session VWAP in the configured number of indices; trade every confirming ETF.",
            "- The entry is the close of the first fully post-signal five-minute bar plus adverse slippage. ATR uses bars completed no later than the signal bar. Position size targets about $100 initial risk.",
            "- Stop and target prices are solved so the modeled after-cost loss is 1R and target profit is 3R. If both touch in a bar, record the stop first; stop gaps receive worse open fills; targets receive no improvement.",
            "- Modeled costs are 1 bp per side plus $0.005/share; stress is 1.5x. The exact bracket payload in `order_dry_run.json` is non-submitting and ends with `--dry-run`.",
            "- Outer pseudo-OOS dates are unique, with inner embargoed selection. This compares execution structures honestly; it does not relabel attempt 002's revealed dates as a fresh holdout.",
            "",
            "## Limitations",
            "",
            "IEX is not SIP. Five-minute OHLC cannot order intrabar stop versus target except by the conservative stop-first rule. Borrow availability for short ETF signals is not reconstructed.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    stock = _parse_stock()
    signals = {
        variant.name: detect_cross_index_underlying_trend(stock, variant.signal)
        for variant in VARIANTS
    }
    base, missing = evaluate_underlying(stock, signals, BASE_COSTS)
    stressed, _ = evaluate_underlying(stock, signals, STRESS_COSTS)
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
