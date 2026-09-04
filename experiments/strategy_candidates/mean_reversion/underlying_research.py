from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any, Mapping, Sequence

from experiments.strategy_candidates.mean_reversion.run_gap_expansion import _metrics, _selected_oos
from experiments.strategy_candidates.mean_reversion.trend_confirmation import make_rolling_folds


def build_underlying_results(
    *,
    attempt: str,
    strategy: str,
    classification: str,
    stock: Mapping[str, Sequence[Any]],
    symbols: Sequence[str],
    signals: Mapping[str, Sequence[Any]],
    base: Mapping[str, Sequence[Any]],
    stressed: Mapping[str, Sequence[Any]],
    missing: Mapping[str, int],
    variants: Sequence[Any],
    data: Mapping[str, Any],
    method: Mapping[str, Any],
    train_size: int = 25,
) -> dict[str, Any]:
    sessions = tuple(
        sorted(
            set.intersection(
                *(set(row.timestamp.date() for row in stock[symbol]) for symbol in symbols)
            )
        )
    )
    folds = make_rolling_folds(sessions, train_size, 2, 10, 10)
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
        for symbol in symbols
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
        "positive_in_60pct_folds": bool(fold_results) and Decimal(positive_folds) / len(fold_results) >= Decimal("0.60"),
        "positive_in_60pct_months": bool(months) and Decimal(positive_months) / len(months) >= Decimal("0.60"),
        "profitable_at_1_5x_costs": Decimal(stress_stats["net_pnl"]) > 0,
        "at_least_60pct_neighbors_positive": Decimal(positive_neighbors) / len(neighbors) >= Decimal("0.60"),
        "no_single_trade_gt_25pct_gross_profit": gross_profit > 0 and max_win <= gross_profit * Decimal("0.25"),
    }
    return {
        "schema_version": 1,
        "attempt": attempt,
        "strategy": strategy,
        "classification": classification,
        "data": {**dict(data), "shared_sessions": len(sessions)},
        "method": dict(method),
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
            for variant in variants
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


def render_underlying_report(result: Mapping[str, Any], contract: Sequence[str]) -> str:
    stats = result["oos"]["statistics"]
    lines = [
        f"# {result['strategy']}",
        "",
        result["classification"],
        "",
        "## Rolling-OOS decision",
        "",
        f"**{stats['sample_size']} trades**, **${stats['net_pnl']} net**, **{Decimal(str(stats['expectancy_r'])):.4f}R expectancy**, **PF {stats['profit_factor']}**, **{stats['max_drawdown_r']}R / ${stats['max_drawdown']} max drawdown**.",
        "",
        f"Admitted: **{result['admission']['admitted']}**.",
        "",
        "## Admission matrix",
        "",
        "| Criterion | Pass |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {value} |" for name, value in result["admission"]["criteria"].items())
    lines.extend(["", "## Implementation contract", ""])
    lines.extend(f"- {item}" for item in contract)
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "IEX is not SIP. Five-minute OHLC requires the conservative stop-first rule when both stop and target touch within one bar. ETF short borrow is not reconstructed.",
            "",
        ]
    )
    return "\n".join(lines)
