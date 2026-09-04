#!/usr/bin/env python3
"""Run attempt 002: overnight breadth plus first-bar confirmation."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import Contract, Costs, DataExclusion, Metrics, ScoredTrade, Trade, UNIVERSE, select_on_training, select_vertical, summarize
    from .gap_candidate import GAP_VARIANTS, GapSignal, GapVariant, gap_signal, gap_target_stop_levels, simulate_gap_trade
    from .run_research import (
        ATTEMPT_LEDGER,
        DATA_CACHE,
        ET,
        PROFILE,
        REPO,
        START,
        END,
        _chunks,
        _contract_object,
        _normalize_contract,
        _option_frames,
        _paged_rows,
        _stock_objects,
        _write_json,
        canonical_hash,
    )
except ImportError:
    from candidate import Contract, Costs, DataExclusion, Metrics, ScoredTrade, Trade, UNIVERSE, select_on_training, select_vertical, summarize  # type: ignore[no-redef]
    from gap_candidate import GAP_VARIANTS, GapSignal, GapVariant, gap_signal, gap_target_stop_levels, simulate_gap_trade  # type: ignore[no-redef]
    from run_research import (  # type: ignore[no-redef]
        ATTEMPT_LEDGER, DATA_CACHE, ET, PROFILE, REPO, START, END, _chunks,
        _contract_object, _normalize_contract, _option_frames, _paged_rows,
        _stock_objects, _write_json, canonical_hash,
    )


HERE = Path(__file__).resolve().parent
GAP_CACHE = HERE / "data" / "gap_market_cache.json"
GAP_BACKTEST = HERE / "results" / "gap_backtest.json"
GAP_REPORT = HERE / "ATTEMPT_002_REPORT.md"
TRAINING_END = date(2026, 4, 30)
PSEUDO_OOS_START = date(2026, 5, 1)
PSEUDO_OOS_END = date(2026, 9, 3)
BASE_COSTS = Costs(Decimal("0.03"), Decimal("0.65"))
STRESSED_COSTS = Costs(Decimal("0.045"), Decimal("0.975"))


def select_gap_variant(
    rows_by_variant: Mapping[str, Sequence[ScoredTrade]], *, minimum_samples: int
) -> str | None:
    training_dates = tuple(
        sorted(
            {
                item.session
                for rows in rows_by_variant.values()
                for item in rows
                if START.date() <= item.session <= TRAINING_END
            }
        )
    )
    return select_on_training(
        rows_by_variant, training_dates, minimum_samples=minimum_samples
    )


def admission_criteria(
    *,
    target_stop_ratio: Decimal,
    profit_factor: Decimal,
    expectancy_r: Decimal,
    sample_count: int,
    max_drawdown_r: Decimal,
    positive_underlyings: int,
    positive_regimes: int,
    positive_month_fraction: Decimal,
    stressed_net_pnl: Decimal,
    positive_neighbor_fraction: Decimal,
    largest_win_fraction: Decimal,
) -> dict[str, Any]:
    exceptional_sample = (
        20 <= sample_count < 30
        and positive_underlyings >= 2
        and positive_month_fraction >= Decimal("0.80")
        and positive_neighbor_fraction >= Decimal("0.75")
    )
    criteria = {
        "after_cost_target_stop_at_least_3": target_stop_ratio >= Decimal(3),
        "profit_factor_at_least_2": profit_factor >= Decimal(2),
        "expectancy_at_least_0_25r": expectancy_r >= Decimal("0.25"),
        "sample_adequate": sample_count >= 30 or exceptional_sample,
        "max_drawdown_at_most_6r": max_drawdown_r <= Decimal(6),
        "cross_symbol_or_three_regime_support": positive_underlyings >= 2 or positive_regimes >= 3,
        "positive_month_fraction_at_least_60pct": positive_month_fraction >= Decimal("0.60"),
        "profitable_at_1_5x_costs": stressed_net_pnl > 0,
        "positive_neighbor_fraction_at_least_60pct": positive_neighbor_fraction >= Decimal("0.60"),
        "largest_win_at_most_25pct_gross_profit": largest_win_fraction <= Decimal("0.25"),
    }
    inputs = {
        "target_stop_ratio": target_stop_ratio,
        "profit_factor": profit_factor,
        "expectancy_r": expectancy_r,
        "sample_count": sample_count,
        "max_drawdown_r": max_drawdown_r,
        "positive_underlyings": positive_underlyings,
        "positive_regimes": positive_regimes,
        "positive_month_fraction": positive_month_fraction,
        "stressed_net_pnl": stressed_net_pnl,
        "positive_neighbor_fraction": positive_neighbor_fraction,
        "largest_win_fraction": largest_win_fraction,
    }
    return {
        "admitted": all(criteria.values()),
        "exceptional_sample_used": exceptional_sample,
        "criteria": criteria,
        "inputs": inputs,
    }


def _gap_signals(stock: Sequence[Any]) -> tuple[dict[str, tuple[GapSignal, ...]], list[dict[str, str]]]:
    by_date: dict[date, list[Any]] = defaultdict(list)
    for bar in stock:
        if bar.symbol in UNIVERSE:
            by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    dates = sorted(day for day in by_date if START.date() <= day <= PSEUDO_OOS_END)
    signals: dict[str, list[GapSignal]] = {variant.name: [] for variant in GAP_VARIANTS}
    exclusions: list[dict[str, str]] = []
    for index, session in enumerate(dates):
        if index == 0:
            continue
        window = (*by_date[dates[index - 1]], *by_date[session])
        for variant in GAP_VARIANTS:
            try:
                signal = gap_signal(variant, window, session)
            except DataExclusion as exc:
                exclusions.append({"stage": "signal", "session": session.isoformat(), "variant": variant.name, "reason": str(exc)})
                continue
            if signal is not None:
                signals[variant.name].append(signal)
    return {name: tuple(rows) for name, rows in signals.items()}, exclusions


def _selection_signal(signal: GapSignal, variant_name: str) -> Any:
    from_types = {variant.name: variant for variant in GAP_VARIANTS}
    if variant_name not in from_types:
        raise KeyError(variant_name)
    # select_vertical depends only on this structural interface.
    return signal


def acquire_gap(*, executable: Path, profile: str, output: Path) -> dict[str, Any]:
    base = json.loads(DATA_CACHE.read_text(encoding="utf-8"))
    stock = _stock_objects(base["stock"]["bars"])
    signals_by_variant, exclusions = _gap_signals(stock)
    unique_signals: dict[tuple[Any, ...], GapSignal] = {}
    for signals in signals_by_variant.values():
        for signal in signals:
            unique_signals[(signal.session, signal.direction, signal.underlying, signal.reference_price)] = signal
    groups: dict[tuple[int, int, str], list[GapSignal]] = defaultdict(list)
    for signal in unique_signals.values():
        groups[(signal.session.year, signal.session.month, signal.underlying)].append(signal)
    source_commands: list[list[str]] = []
    contract_rows: dict[str, dict[str, str]] = {
        str(item["symbol"]): dict(item) for item in base["contracts"]
    }
    for (_, _, underlying), signals in sorted(groups.items()):
        spots = [item.reference_price for item in signals]
        lower = (min(spots) - Decimal(8)).quantize(Decimal(1), rounding=ROUND_FLOOR)
        upper = (max(spots) + Decimal(8)).quantize(Decimal(1), rounding=ROUND_CEILING)
        request = (
            "option", "contracts", "--underlying-symbols", underlying,
            "--expiration-date-gte", (min(item.session for item in signals) + timedelta(days=3)).isoformat(),
            "--expiration-date-lte", (max(item.session for item in signals) + timedelta(days=9)).isoformat(),
            "--strike-price-gte", str(lower), "--strike-price-lte", str(upper), "--limit", "10000",
        )
        for status in ("inactive", "active"):
            rows, commands = _paged_rows(executable, profile, (*request, "--status", status), result_key="option_contracts")
            source_commands.extend(commands)
            for raw in rows:
                normalized = _normalize_contract(raw, underlying)
                if normalized is not None:
                    contract_rows[normalized["symbol"]] = normalized
    contracts = tuple(_contract_object(item) for item in contract_rows.values())
    selections: list[dict[str, Any]] = []
    for variant in GAP_VARIANTS:
        for signal in signals_by_variant[variant.name]:
            try:
                vertical = select_vertical(signal, contracts)
            except DataExclusion as exc:
                exclusions.append({"stage": "contract", "session": signal.session.isoformat(), "variant": variant.name, "reason": str(exc)})
                continue
            selections.append(
                {
                    "session": signal.session.isoformat(), "variant": variant.name,
                    "completed_at": signal.completed_at.isoformat(), "direction": signal.direction,
                    "underlying": signal.underlying, "reference_price": str(signal.reference_price),
                    "breadth_count": signal.breadth_count, "mean_gap": str(signal.mean_gap),
                    "long_symbol": vertical.long.symbol, "short_symbol": vertical.short.symbol,
                    "expiration": vertical.long.expiration.isoformat(),
                    "long_strike": str(vertical.long.strike), "short_strike": str(vertical.short.strike),
                }
            )
    symbols = sorted({str(item[key]) for item in selections for key in ("long_symbol", "short_symbol")})
    option_rows: list[dict[str, Any]] = []
    for batch in _chunks(symbols, 80):
        rows, commands = _paged_rows(
            executable, profile,
            ("data", "option", "bars", "--symbols", ",".join(batch), "--start", START.isoformat(),
             "--end", END.isoformat(), "--timeframe", "15Min", "--sort", "asc", "--limit", "10000"),
            result_key="bars",
        )
        option_rows.extend(rows)
        source_commands.extend(commands)
    body = {
        "schema_version": "afterimage-gap-market-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only endpoints",
        "base_stock_cache_hash": base["content_hash"],
        "contracts": sorted(contract_rows.values(), key=lambda item: item["symbol"]),
        "selections": sorted(selections, key=lambda item: (item["session"], item["variant"])),
        "option_bars": sorted(option_rows, key=lambda item: (str(item.get("symbol")), str(item.get("t")))),
        "exclusions": exclusions,
        "source_commands": source_commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    _write_json(output, result)
    return result


def _rehydrate(item: Mapping[str, Any]) -> GapSignal:
    return GapSignal(
        session=date.fromisoformat(str(item["session"])), completed_at=datetime.fromisoformat(str(item["completed_at"])),
        direction=str(item["direction"]), underlying=str(item["underlying"]),
        reference_price=Decimal(str(item["reference_price"])), breadth_count=int(item["breadth_count"]),
        mean_gap=Decimal(str(item["mean_gap"])), variant=str(item["variant"]),
    )


def _evaluate(
    cache: Mapping[str, Any], *, start: date, end: date, costs: Costs
) -> tuple[dict[str, tuple[Trade, ...]], list[dict[str, str]]]:
    lookup = {variant.name: variant for variant in GAP_VARIANTS}
    rows: dict[str, list[Trade]] = {variant.name: [] for variant in GAP_VARIANTS}
    exclusions: list[dict[str, str]] = []
    for item in cache["selections"]:
        session = date.fromisoformat(str(item["session"]))
        if not start <= session <= end:
            continue
        name = str(item["variant"])
        signal = _rehydrate(item)
        try:
            frames = _option_frames(cache["option_bars"], str(item["long_symbol"]), str(item["short_symbol"]), session)
            trade = simulate_gap_trade(signal, frames, lookup[name], costs)
        except (DataExclusion, KeyError, ValueError) as exc:
            exclusions.append({"stage": "execution", "session": session.isoformat(), "variant": name, "reason": str(exc)})
            continue
        rows[name].append(trade)
    return {name: tuple(sorted(values, key=lambda item: item.entry_at)) for name, values in rows.items()}, exclusions


def _scored(rows: Mapping[str, Sequence[Trade]]) -> dict[str, tuple[ScoredTrade, ...]]:
    return {name: tuple(ScoredTrade(item.session, item.return_r, item.net_pnl) for item in values) for name, values in rows.items()}


def _metrics_dict(metrics: Metrics) -> dict[str, Any]:
    return asdict(metrics)


def _max_drawdown_r(trades: Sequence[Trade]) -> Decimal:
    cumulative = Decimal(0)
    peak = Decimal(0)
    drawdown = Decimal(0)
    for trade in sorted(trades, key=lambda item: item.entry_at):
        cumulative += trade.return_r
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return drawdown


def _profit_concentration(trades: Sequence[Trade]) -> Decimal:
    winners = [item.net_pnl for item in trades if item.net_pnl > 0]
    gross = sum(winners, Decimal(0))
    return max(winners) / gross if gross else Decimal(1)


def _group_profit_count(trades: Sequence[Trade], field: str) -> tuple[int, dict[str, Decimal]]:
    grouped: dict[str, Decimal] = defaultdict(Decimal)
    for trade in trades:
        key = str(getattr(trade, field))
        grouped[key] += trade.net_pnl
    return sum(value > 0 for value in grouped.values()), dict(grouped)


def evaluate_gap(cache: Mapping[str, Any]) -> dict[str, Any]:
    development, dev_exclusions = _evaluate(cache, start=START.date(), end=TRAINING_END, costs=BASE_COSTS)
    scored = _scored(development)
    selected = select_gap_variant(scored, minimum_samples=12)
    dev_folds: list[dict[str, Any]] = []
    for validation_month in (3, 4):
        training_dates = tuple(
            sorted({item.session for rows in scored.values() for item in rows if item.session < date(2026, validation_month, 1)})
        )
        fold_selected = select_on_training(scored, training_dates, minimum_samples=6)
        validation = tuple(item for item in development.get(fold_selected or "", ()) if item.session.month == validation_month)
        dev_folds.append({"validation_month": validation_month, "selected_variant": fold_selected, "metrics": _metrics_dict(summarize(validation))})

    # May-Sep was not used in attempt-002 design or selection; it is revealed once here as pseudo-OOS.
    pseudo_rows, pseudo_exclusions = _evaluate(cache, start=PSEUDO_OOS_START, end=PSEUDO_OOS_END, costs=BASE_COSTS)
    stressed_rows, stressed_exclusions = _evaluate(cache, start=PSEUDO_OOS_START, end=PSEUDO_OOS_END, costs=STRESSED_COSTS)
    selected_rows = pseudo_rows.get(selected or "", ())
    selected_stressed = stressed_rows.get(selected or "", ())
    stats = summarize(selected_rows)
    stressed_stats = summarize(selected_stressed)
    positive_underlyings, underlying_pnl = _group_profit_count(selected_rows, "underlying")
    month_pnl: dict[str, Decimal] = defaultdict(Decimal)
    for trade in selected_rows:
        month_pnl[f"{trade.session:%Y-%m}"] += trade.net_pnl
    total_months = 5
    positive_month_fraction = Decimal(sum(value > 0 for value in month_pnl.values())) / Decimal(total_months)
    neighbor_metrics = {name: summarize(rows) for name, rows in pseudo_rows.items()}
    positive_neighbor_fraction = Decimal(sum(item.net_pnl > 0 for item in neighbor_metrics.values())) / Decimal(len(GAP_VARIANTS))
    variant_lookup = {variant.name: variant for variant in GAP_VARIANTS}
    selected_variant = variant_lookup.get(selected or "")
    nominal_ratio = Decimal(3)
    if selected_rows and selected_variant:
        ratios = []
        for trade in selected_rows:
            stop, target, risk = gap_target_stop_levels(trade.entry_debit, selected_variant.stop_fraction, BASE_COSTS)
            target_net = (target - trade.entry_debit) * Decimal(100) - Decimal("2.60")
            ratios.append(target_net / risk)
        nominal_ratio = min(ratios)
    admission = admission_criteria(
        target_stop_ratio=nominal_ratio,
        profit_factor=stats.profit_factor,
        expectancy_r=stats.expectancy_r,
        sample_count=stats.sample_count,
        max_drawdown_r=_max_drawdown_r(selected_rows),
        positive_underlyings=positive_underlyings,
        positive_regimes=sum(value > 0 for value in month_pnl.values()),
        positive_month_fraction=positive_month_fraction,
        stressed_net_pnl=stressed_stats.net_pnl,
        positive_neighbor_fraction=positive_neighbor_fraction,
        largest_win_fraction=_profit_concentration(selected_rows),
    )
    exclusion_counts = Counter((item.get("variant", "unknown"), item.get("reason", "unknown")) for item in (*dev_exclusions, *pseudo_exclusions))
    variants = {}
    for variant in GAP_VARIANTS:
        variants[variant.name] = {
            "parameters": asdict(variant),
            "development": _metrics_dict(summarize(development[variant.name])),
            "pseudo_oos": _metrics_dict(neighbor_metrics[variant.name]),
            "pseudo_oos_trades": [asdict(item) for item in pseudo_rows[variant.name]],
            "stressed_1_5x_costs": _metrics_dict(summarize(stressed_rows[variant.name])),
            "exclusions": {reason: count for (name, reason), count in exclusion_counts.items() if name == variant.name},
        }
    result = {
        "schema_version": "afterimage-gap-backtest-v1",
        "attempt_id": "overnight_breadth_confirmation_v2",
        "family": "overnight seven-ETF gap breadth confirmed by QQQ and IWM first bars",
        "selection": {
            "development_window": {"start": START.date(), "end": TRAINING_END},
            "selected_variant": selected,
            "minimum_training_samples": 12,
            "development_metrics": _metrics_dict(summarize(development.get(selected or "", ()))),
            "expanding_development_folds": dev_folds,
        },
        "pseudo_oos": {
            "window": {"start": PSEUDO_OOS_START, "end": PSEUDO_OOS_END},
            "label": "rolling/pseudo-OOS; Aug-Sep were revealed by attempt 001 and are not untouched",
            "evaluations": 1,
            "selected_metrics": _metrics_dict(stats),
            "selected_trades": [asdict(item) for item in selected_rows],
            "max_drawdown_r": _max_drawdown_r(selected_rows),
            "underlying_pnl": underlying_pnl,
            "month_pnl": dict(month_pnl),
            "stressed_1_5x_costs": _metrics_dict(stressed_stats),
            "positive_neighbor_fraction": positive_neighbor_fraction,
            "largest_win_fraction_of_gross_profit": _profit_concentration(selected_rows),
        },
        "variants": variants,
        "admission": admission,
        "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "limitations": [
            "May-Sep is pseudo-OOS rather than untouched because attempt 001 already revealed Aug-Sep.",
            "Option trade-bar opens are not NBBO quotes; fixed adverse per-leg slippage and 1.5x stress cannot reproduce queue position.",
            "Signals cluster in large overnight-gap regimes and may be sensitive to macro-event composition.",
            "The IEX feed is not the full SIP.",
        ],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _update_attempt_ledger(status: str, result: Mapping[str, Any] | None = None) -> None:
    if ATTEMPT_LEDGER.exists():
        ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    else:
        ledger = {"schema_version": "afterimage-strategy-attempt-ledger-v1", "rule": "A revealed date range can never be relabeled untouched by a later attempt.", "attempts": []}
    ledger.pop("ledger_hash", None)
    attempts = [item for item in ledger["attempts"] if item.get("attempt_id") != "overnight_breadth_confirmation_v2"]
    entry: dict[str, Any] = {
        "attempt_id": "overnight_breadth_confirmation_v2",
        "status": status,
        "spec": "ATTEMPT_002_SPEC.md",
        "predeclared_family": [asdict(item) for item in GAP_VARIANTS],
        "selection_window": {"start": START.date(), "end": TRAINING_END},
        "pseudo_oos_window": {"start": PSEUDO_OOS_START, "end": PSEUDO_OOS_END, "may_be_reused_as_untouched": False},
    }
    if result is not None:
        entry.update({"selected_variant": result["selection"]["selected_variant"], "pseudo_oos_metrics": result["pseudo_oos"]["selected_metrics"], "admission": result["admission"], "recommendation": result["decision"], "result_hash": result["result_hash"]})
    attempts.append(entry)
    ledger["attempts"] = attempts
    ledger["ledger_hash"] = canonical_hash({key: value for key, value in ledger.items() if key != "ledger_hash"})
    _write_json(ATTEMPT_LEDGER, ledger)


def render_report(result: Mapping[str, Any]) -> str:
    stats = result["pseudo_oos"]["selected_metrics"]
    admission = result["admission"]
    lines = [
        "# Attempt 002 — overnight breadth confirmation",
        "",
        f"**{result['decision']}**. Training selected `{result['selection']['selected_variant']}`. Pseudo-OOS: n={stats['sample_count']}, net=${stats['net_pnl']}, expectancy={Decimal(str(stats['expectancy_r'])):.3f}R, PF={Decimal(str(stats['profit_factor'])):.2f}, hit={Decimal(str(stats['hit_rate'])):.1%}, max DD=${stats['max_drawdown']} / {Decimal(str(result['pseudo_oos']['max_drawdown_r'])):.2f}R.",
        "",
        "## Admission audit",
        "",
        "| Criterion | Pass |",
        "|---|---|",
        *[f"| {name} | {value} |" for name, value in admission["criteria"].items()],
        "",
        "## Full predeclared neighborhood",
        "",
        "| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in result["variants"].items():
        dev = row["development"]; pseudo = row["pseudo_oos"]; stress = row["stressed_1_5x_costs"]
        lines.append(f"| `{name}` | {dev['sample_count']} | ${dev['net_pnl']} | {pseudo['sample_count']} | ${pseudo['net_pnl']} | {Decimal(str(pseudo['expectancy_r'])):.3f} | {Decimal(str(pseudo['profit_factor'])):.2f} | ${stress['net_pnl']} |")
    lines.extend(["", "## Honesty and limitations", "", *[f"- {item}" for item in result["limitations"]], ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--alpaca-cli", type=Path, default=REPO / ".tools" / "bin" / "alpaca")
    parser.add_argument("--profile", default=PROFILE)
    arguments = parser.parse_args()
    _update_attempt_ledger("planned")
    if arguments.fetch or not GAP_CACHE.exists():
        cache = acquire_gap(executable=arguments.alpaca_cli, profile=arguments.profile, output=GAP_CACHE)
    else:
        cache = json.loads(GAP_CACHE.read_text(encoding="utf-8"))
    result = evaluate_gap(cache)
    _write_json(GAP_BACKTEST, result)
    GAP_REPORT.write_text(render_report(result), encoding="utf-8")
    _update_attempt_ledger("evaluated", result)
    print(json.dumps({"decision": result["decision"], "selected": result["selection"]["selected_variant"], "pseudo_oos": result["pseudo_oos"]["selected_metrics"], "admission": result["admission"]["criteria"]}, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
