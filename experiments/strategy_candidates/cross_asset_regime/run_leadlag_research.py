#!/usr/bin/env python3
"""Run attempt 003: sector-to-index lead-lag catch-up."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import Costs, DataExclusion, ScoredTrade, Trade, enforce_non_overlapping, select_on_training, select_vertical, summarize
    from .gap_candidate import gap_target_stop_levels, simulate_gap_trade
    from .leadlag_candidate import LEADLAG_VARIANTS, LeadLagSignal, leadlag_signal_at
    from .run_gap_research import (
        GAP_CACHE, PSEUDO_OOS_END, PSEUDO_OOS_START, TRAINING_END,
        _group_profit_count, _max_drawdown_r, _profit_concentration,
        admission_criteria,
    )
    from .run_research import (
        ATTEMPT_LEDGER, DATA_CACHE, END, ET, PROFILE, REPO, START,
        _chunks, _contract_object, _option_frames, _paged_rows, _stock_objects,
        _write_json, canonical_hash,
    )
except ImportError:
    from candidate import Costs, DataExclusion, ScoredTrade, Trade, enforce_non_overlapping, select_on_training, select_vertical, summarize  # type: ignore[no-redef]
    from gap_candidate import gap_target_stop_levels, simulate_gap_trade  # type: ignore[no-redef]
    from leadlag_candidate import LEADLAG_VARIANTS, LeadLagSignal, leadlag_signal_at  # type: ignore[no-redef]
    from run_gap_research import GAP_CACHE, PSEUDO_OOS_END, PSEUDO_OOS_START, TRAINING_END, _group_profit_count, _max_drawdown_r, _profit_concentration, admission_criteria  # type: ignore[no-redef]
    from run_research import ATTEMPT_LEDGER, DATA_CACHE, END, ET, PROFILE, REPO, START, _chunks, _contract_object, _option_frames, _paged_rows, _stock_objects, _write_json, canonical_hash  # type: ignore[no-redef]


HERE = Path(__file__).resolve().parent
LEADLAG_CACHE = HERE / "data" / "leadlag_market_cache.json"
LEADLAG_BACKTEST = HERE / "results" / "leadlag_backtest.json"
LEADLAG_REPORT = HERE / "ATTEMPT_003_REPORT.md"
BASE_COSTS = Costs(Decimal("0.03"), Decimal("0.65"))
STRESSED_COSTS = Costs(Decimal("0.045"), Decimal("0.975"))
CHECKPOINTS = (time(11, 30), time(13, 0), time(14, 0))


def _signals(stock: Sequence[Any]) -> tuple[dict[str, tuple[LeadLagSignal, ...]], list[dict[str, str]]]:
    by_date: dict[date, list[Any]] = defaultdict(list)
    for bar in stock:
        by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    rows: dict[str, list[LeadLagSignal]] = {variant.name: [] for variant in LEADLAG_VARIANTS}
    exclusions: list[dict[str, str]] = []
    for session, session_bars in sorted(by_date.items()):
        if not START.date() <= session <= PSEUDO_OOS_END:
            continue
        for variant in LEADLAG_VARIANTS:
            for checkpoint in CHECKPOINTS:
                signal_start = datetime.combine(session, checkpoint, ET)
                try:
                    signal = leadlag_signal_at(variant, session_bars, session, signal_start)
                except DataExclusion as exc:
                    exclusions.append({"stage": "signal", "session": session.isoformat(), "variant": variant.name, "reason": str(exc)})
                    continue
                if signal is not None:
                    rows[variant.name].append(signal)
    return {name: tuple(values) for name, values in rows.items()}, exclusions


def acquire_leadlag(*, executable: Path, profile: str, output: Path) -> dict[str, Any]:
    base = json.loads(DATA_CACHE.read_text(encoding="utf-8"))
    gap_cache = json.loads(GAP_CACHE.read_text(encoding="utf-8"))
    stock = _stock_objects(base["stock"]["bars"])
    signals, exclusions = _signals(stock)
    contract_rows: dict[str, dict[str, str]] = {}
    for source in (base["contracts"], gap_cache["contracts"]):
        for item in source:
            contract_rows[str(item["symbol"])] = dict(item)
    contracts = tuple(_contract_object(item) for item in contract_rows.values())
    selections: list[dict[str, Any]] = []
    for variant in LEADLAG_VARIANTS:
        for signal in signals[variant.name]:
            try:
                vertical = select_vertical(signal, contracts)
            except DataExclusion as exc:
                exclusions.append({"stage": "contract", "session": signal.session.isoformat(), "variant": variant.name, "reason": str(exc)})
                continue
            selections.append({
                "session": signal.session.isoformat(), "variant": variant.name,
                "completed_at": signal.completed_at.isoformat(), "direction": signal.direction,
                "underlying": signal.underlying, "reference_price": str(signal.reference_price),
                "sector_breadth": signal.sector_breadth, "sector_mean_return": str(signal.sector_mean_return),
                "lag": str(signal.lag), "long_symbol": vertical.long.symbol,
                "short_symbol": vertical.short.symbol, "expiration": vertical.long.expiration.isoformat(),
            })
    symbols = sorted({str(item[key]) for item in selections for key in ("long_symbol", "short_symbol")})
    option_rows: list[dict[str, Any]] = []
    source_commands: list[list[str]] = []
    for batch in _chunks(symbols, 80):
        rows, commands = _paged_rows(
            executable, profile,
            ("data", "option", "bars", "--symbols", ",".join(batch), "--start", START.isoformat(),
             "--end", END.isoformat(), "--timeframe", "15Min", "--sort", "asc", "--limit", "10000"),
            result_key="bars",
        )
        option_rows.extend(rows); source_commands.extend(commands)
    body = {
        "schema_version": "afterimage-leadlag-market-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only endpoints",
        "base_stock_cache_hash": base["content_hash"], "contract_cache_hash": gap_cache["content_hash"],
        "contracts": sorted(contract_rows.values(), key=lambda item: item["symbol"]),
        "selections": sorted(selections, key=lambda item: (item["session"], item["completed_at"], item["variant"])),
        "option_bars": sorted(option_rows, key=lambda item: (str(item.get("symbol")), str(item.get("t")))),
        "exclusions": exclusions, "source_commands": source_commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    _write_json(output, result)
    return result


def _rehydrate(item: Mapping[str, Any]) -> LeadLagSignal:
    return LeadLagSignal(
        session=date.fromisoformat(str(item["session"])), completed_at=datetime.fromisoformat(str(item["completed_at"])),
        direction=str(item["direction"]), underlying=str(item["underlying"]), reference_price=Decimal(str(item["reference_price"])),
        sector_breadth=int(item["sector_breadth"]), sector_mean_return=Decimal(str(item["sector_mean_return"])),
        lag=Decimal(str(item["lag"])), variant=str(item["variant"]),
    )


def _evaluate(cache: Mapping[str, Any], *, start: date, end: date, costs: Costs) -> tuple[dict[str, tuple[Trade, ...]], list[dict[str, str]]]:
    variants = {item.name: item for item in LEADLAG_VARIANTS}
    rows: dict[str, list[Trade]] = {item.name: [] for item in LEADLAG_VARIANTS}
    exclusions: list[dict[str, str]] = []
    for item in cache["selections"]:
        session = date.fromisoformat(str(item["session"])); name = str(item["variant"])
        if not start <= session <= end:
            continue
        signal = _rehydrate(item)
        try:
            frames = _option_frames(cache["option_bars"], str(item["long_symbol"]), str(item["short_symbol"]), session)
            trade = simulate_gap_trade(signal, frames, variants[name], costs)  # type: ignore[arg-type]
        except (DataExclusion, KeyError, ValueError) as exc:
            exclusions.append({"stage": "execution", "session": session.isoformat(), "variant": name, "reason": str(exc)})
            continue
        rows[name].append(trade)
    return {name: enforce_non_overlapping(values) for name, values in rows.items()}, exclusions


def _scored(rows: Mapping[str, Sequence[Trade]]) -> dict[str, tuple[ScoredTrade, ...]]:
    return {name: tuple(ScoredTrade(item.session, item.return_r, item.net_pnl) for item in values) for name, values in rows.items()}


def evaluate(cache: Mapping[str, Any]) -> dict[str, Any]:
    development, dev_exclusions = _evaluate(cache, start=START.date(), end=TRAINING_END, costs=BASE_COSTS)
    scored = _scored(development)
    training_dates = tuple(sorted({item.session for values in scored.values() for item in values}))
    selected = select_on_training(scored, training_dates, minimum_samples=12)
    folds = []
    for month in (3, 4):
        train = tuple(day for day in training_dates if day < date(2026, month, 1))
        chosen = select_on_training(scored, train, minimum_samples=6)
        validation = tuple(item for item in development.get(chosen or "", ()) if item.session.month == month)
        folds.append({"validation_month": month, "selected_variant": chosen, "metrics": asdict(summarize(validation))})
    pseudo, pseudo_exclusions = _evaluate(cache, start=PSEUDO_OOS_START, end=PSEUDO_OOS_END, costs=BASE_COSTS)
    stressed, stress_exclusions = _evaluate(cache, start=PSEUDO_OOS_START, end=PSEUDO_OOS_END, costs=STRESSED_COSTS)
    selected_rows = pseudo.get(selected or "", ()); stressed_rows = stressed.get(selected or "", ())
    stats = summarize(selected_rows); stress_stats = summarize(stressed_rows)
    positive_underlyings, underlying_pnl = _group_profit_count(selected_rows, "underlying")
    month_pnl: dict[str, Decimal] = defaultdict(Decimal)
    for trade in selected_rows: month_pnl[f"{trade.session:%Y-%m}"] += trade.net_pnl
    positive_month_fraction = Decimal(sum(value > 0 for value in month_pnl.values())) / Decimal(5)
    neighbor_stats = {name: summarize(values) for name, values in pseudo.items()}
    positive_neighbor_fraction = Decimal(sum(item.net_pnl > 0 for item in neighbor_stats.values())) / Decimal(len(LEADLAG_VARIANTS))
    variant_lookup = {item.name: item for item in LEADLAG_VARIANTS}
    nominal_ratio = Decimal(3)
    if selected_rows and selected:
        ratios = []
        for trade in selected_rows:
            _, target, risk = gap_target_stop_levels(trade.entry_debit, variant_lookup[selected].stop_fraction, BASE_COSTS)
            ratios.append(((target - trade.entry_debit) * Decimal(100) - Decimal("2.60")) / risk)
        nominal_ratio = min(ratios)
    admission = admission_criteria(
        target_stop_ratio=nominal_ratio, profit_factor=stats.profit_factor, expectancy_r=stats.expectancy_r,
        sample_count=stats.sample_count, max_drawdown_r=_max_drawdown_r(selected_rows), positive_underlyings=positive_underlyings,
        positive_regimes=sum(value > 0 for value in month_pnl.values()), positive_month_fraction=positive_month_fraction,
        stressed_net_pnl=stress_stats.net_pnl, positive_neighbor_fraction=positive_neighbor_fraction,
        largest_win_fraction=_profit_concentration(selected_rows),
    )
    exclusion_counts = Counter((x.get("variant", "unknown"), x.get("reason", "unknown")) for x in (*dev_exclusions, *pseudo_exclusions, *stress_exclusions))
    variants = {}
    for variant in LEADLAG_VARIANTS:
        variants[variant.name] = {
            "parameters": asdict(variant), "development": asdict(summarize(development[variant.name])),
            "pseudo_oos": asdict(neighbor_stats[variant.name]), "pseudo_oos_trades": [asdict(x) for x in pseudo[variant.name]],
            "stressed_1_5x_costs": asdict(summarize(stressed[variant.name])),
            "exclusions": {reason: count for (name, reason), count in exclusion_counts.items() if name == variant.name},
        }
    result = {
        "schema_version": "afterimage-leadlag-backtest-v1", "attempt_id": "sector_index_leadlag_v3",
        "family": "sector basket lead predicts lagging QQQ/IWM catch-up",
        "selection": {"window": {"start": START.date(), "end": TRAINING_END}, "selected_variant": selected,
                      "development_metrics": asdict(summarize(development.get(selected or "", ()))), "folds": folds},
        "pseudo_oos": {"window": {"start": PSEUDO_OOS_START, "end": PSEUDO_OOS_END},
                       "label": "rolling/pseudo-OOS; never untouched", "evaluations": 1,
                       "selected_metrics": asdict(stats), "selected_trades": [asdict(x) for x in selected_rows],
                       "max_drawdown_r": _max_drawdown_r(selected_rows), "underlying_pnl": underlying_pnl,
                       "month_pnl": dict(month_pnl), "stressed_1_5x_costs": asdict(stress_stats),
                       "positive_neighbor_fraction": positive_neighbor_fraction,
                       "largest_win_fraction_of_gross_profit": _profit_concentration(selected_rows)},
        "variants": variants, "admission": admission, "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "limitations": ["All May-Sep evidence is rolling/pseudo-OOS, not untouched.", "Trade-bar opens plus fixed slippage are not NBBO quote replay.", "Sparse synchronized option bars reduce the checkpoint sample.", "IEX is not the full SIP."],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _update_ledger(status: str, result: Mapping[str, Any] | None = None) -> None:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8")); ledger.pop("ledger_hash", None)
    attempts = [item for item in ledger["attempts"] if item.get("attempt_id") != "sector_index_leadlag_v3"]
    entry: dict[str, Any] = {"attempt_id": "sector_index_leadlag_v3", "status": status, "spec": "ATTEMPT_003_SPEC.md",
                             "predeclared_family": [asdict(item) for item in LEADLAG_VARIANTS],
                             "selection_window": {"start": START.date(), "end": TRAINING_END},
                             "pseudo_oos_window": {"start": PSEUDO_OOS_START, "end": PSEUDO_OOS_END, "may_be_reused_as_untouched": False}}
    if result is not None: entry.update({"selected_variant": result["selection"]["selected_variant"], "pseudo_oos_metrics": result["pseudo_oos"]["selected_metrics"], "admission": result["admission"], "recommendation": result["decision"], "result_hash": result["result_hash"]})
    attempts.append(entry); ledger["attempts"] = attempts
    ledger["ledger_hash"] = canonical_hash({k: v for k, v in ledger.items() if k != "ledger_hash"}); _write_json(ATTEMPT_LEDGER, ledger)


def render_report(result: Mapping[str, Any]) -> str:
    stats = result["pseudo_oos"]["selected_metrics"]
    lines = ["# Attempt 003 — sector-to-index lead–lag catch-up", "",
             f"**{result['decision']}**. `{result['selection']['selected_variant']}`: n={stats['sample_count']}, net=${stats['net_pnl']}, expectancy={Decimal(str(stats['expectancy_r'])):.3f}R, PF={Decimal(str(stats['profit_factor'])):.2f}, max DD={Decimal(str(result['pseudo_oos']['max_drawdown_r'])):.2f}R.", "",
             "## Admission audit", "", "| Criterion | Pass |", "|---|---|",
             *[f"| {k} | {v} |" for k, v in result["admission"]["criteria"].items()], "",
             "## Neighborhood", "", "| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, row in result["variants"].items():
        d=row["development"]; p=row["pseudo_oos"]; s=row["stressed_1_5x_costs"]
        lines.append(f"| `{name}` | {d['sample_count']} | ${d['net_pnl']} | {p['sample_count']} | ${p['net_pnl']} | {Decimal(str(p['expectancy_r'])):.3f} | {Decimal(str(p['profit_factor'])):.2f} | ${s['net_pnl']} |")
    lines.extend(["", "## Limitations", "", *[f"- {x}" for x in result["limitations"]], ""]); return "\n".join(lines)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--fetch", action="store_true"); parser.add_argument("--alpaca-cli", type=Path, default=REPO/".tools"/"bin"/"alpaca"); parser.add_argument("--profile", default=PROFILE); args=parser.parse_args()
    _update_ledger("planned")
    cache=acquire_leadlag(executable=args.alpaca_cli, profile=args.profile, output=LEADLAG_CACHE) if args.fetch or not LEADLAG_CACHE.exists() else json.loads(LEADLAG_CACHE.read_text(encoding="utf-8"))
    result=evaluate(cache); _write_json(LEADLAG_BACKTEST,result); LEADLAG_REPORT.write_text(render_report(result),encoding="utf-8"); _update_ledger("evaluated",result)
    print(json.dumps({"decision":result["decision"],"selected":result["selection"]["selected_variant"],"pseudo_oos":result["pseudo_oos"]["selected_metrics"],"admission":result["admission"]["criteria"]},default=str,sort_keys=True))


if __name__ == "__main__": main()
