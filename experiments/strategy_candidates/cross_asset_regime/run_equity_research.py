#!/usr/bin/env python3
"""Run attempt 004: cross-asset lead-lag with liquid ETF share execution."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import ScoredTrade, enforce_non_overlapping, select_on_training, summarize
    from .equity_candidate import EQUITY_VARIANTS, EquityCosts, EquitySignal, EquityTrade, simulate_equity_trade
    from .leadlag_candidate import LeadLagVariant, leadlag_signal_at
    from .run_gap_research import PSEUDO_OOS_END, PSEUDO_OOS_START, TRAINING_END, _group_profit_count, _max_drawdown_r, _profit_concentration, admission_criteria
    from .run_leadlag_research import CHECKPOINTS
    from .run_research import ATTEMPT_LEDGER, DATA_CACHE, ET, START, _stock_objects, _write_json, canonical_hash
except ImportError:
    from candidate import ScoredTrade, enforce_non_overlapping, select_on_training, summarize  # type: ignore[no-redef]
    from equity_candidate import EQUITY_VARIANTS, EquityCosts, EquitySignal, EquityTrade, simulate_equity_trade  # type: ignore[no-redef]
    from leadlag_candidate import LeadLagVariant, leadlag_signal_at  # type: ignore[no-redef]
    from run_gap_research import PSEUDO_OOS_END, PSEUDO_OOS_START, TRAINING_END, _group_profit_count, _max_drawdown_r, _profit_concentration, admission_criteria  # type: ignore[no-redef]
    from run_leadlag_research import CHECKPOINTS  # type: ignore[no-redef]
    from run_research import ATTEMPT_LEDGER, DATA_CACHE, ET, START, _stock_objects, _write_json, canonical_hash  # type: ignore[no-redef]


HERE = Path(__file__).resolve().parent
EQUITY_BACKTEST = HERE / "results" / "equity_backtest.json"
EQUITY_REPORT = HERE / "ATTEMPT_004_REPORT.md"
BASE_COSTS = EquityCosts(Decimal("0.0001"), Decimal("0.005"))
STRESSED_COSTS = EquityCosts(Decimal("0.00015"), Decimal("0.0075"))


def _signals(stock: Sequence[Any]) -> dict[str, tuple[EquitySignal, ...]]:
    by_date: dict[date, list[Any]] = defaultdict(list)
    for bar in stock:
        by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    rows: dict[str, list[EquitySignal]] = {variant.name: [] for variant in EQUITY_VARIANTS}
    for session, bars in sorted(by_date.items()):
        if not START.date() <= session <= PSEUDO_OOS_END:
            continue
        for variant in EQUITY_VARIANTS:
            signal_variant = LeadLagVariant(
                variant.name,
                variant.sector_breadth_required,
                variant.minimum_lag,
                variant.stop_fraction,
                hold_bars=variant.hold_bars,
            )
            for checkpoint in CHECKPOINTS:
                try:
                    signal = leadlag_signal_at(
                        signal_variant,
                        bars,
                        session,
                        datetime.combine(session, checkpoint, ET),
                    )
                except ValueError:
                    continue
                if signal is None:
                    continue
                rows[variant.name].append(
                    EquitySignal(
                        session=signal.session,
                        completed_at=signal.completed_at,
                        direction=signal.direction,
                        underlying=signal.underlying,
                        reference_price=signal.reference_price,
                        variant=variant.name,
                    )
                )
    return {name: tuple(values) for name, values in rows.items()}


def _evaluate(
    signals: Mapping[str, Sequence[EquitySignal]],
    stock: Sequence[Any],
    *,
    start: date,
    end: date,
    costs: EquityCosts,
) -> dict[str, tuple[EquityTrade, ...]]:
    variant_lookup = {variant.name: variant for variant in EQUITY_VARIANTS}
    by_session: dict[date, list[Any]] = defaultdict(list)
    for bar in stock:
        by_session[bar.timestamp.astimezone(ET).date()].append(bar)
    result: dict[str, tuple[EquityTrade, ...]] = {}
    for name, variant_signals in signals.items():
        trades = []
        for signal in variant_signals:
            if not start <= signal.session <= end:
                continue
            try:
                trade = simulate_equity_trade(
                    signal, by_session[signal.session], variant_lookup[name], costs
                )
            except ValueError:
                continue
            trades.append(trade)
        result[name] = enforce_non_overlapping(trades)  # type: ignore[arg-type]
    return result


def _scored(rows: Mapping[str, Sequence[EquityTrade]]) -> dict[str, tuple[ScoredTrade, ...]]:
    return {
        name: tuple(ScoredTrade(item.session, item.return_r, item.net_pnl) for item in values)
        for name, values in rows.items()
    }


def evaluate() -> dict[str, Any]:
    cache = json.loads(DATA_CACHE.read_text(encoding="utf-8"))
    stock = _stock_objects(cache["stock"]["bars"])
    signals = _signals(stock)
    development = _evaluate(signals, stock, start=START.date(), end=TRAINING_END, costs=BASE_COSTS)
    scored = _scored(development)
    training_dates = tuple(sorted({item.session for values in scored.values() for item in values}))
    selected = select_on_training(scored, training_dates, minimum_samples=20)
    folds = []
    for month in (3, 4):
        train_dates = tuple(day for day in training_dates if day < date(2026, month, 1))
        chosen = select_on_training(scored, train_dates, minimum_samples=10)
        validation = tuple(item for item in development.get(chosen or "", ()) if item.session.month == month)
        folds.append({"validation_month": month, "selected_variant": chosen, "metrics": asdict(summarize(validation))})

    pseudo = _evaluate(signals, stock, start=PSEUDO_OOS_START, end=PSEUDO_OOS_END, costs=BASE_COSTS)
    stressed = _evaluate(signals, stock, start=PSEUDO_OOS_START, end=PSEUDO_OOS_END, costs=STRESSED_COSTS)
    selected_rows = pseudo.get(selected or "", ())
    selected_stressed = stressed.get(selected or "", ())
    stats = summarize(selected_rows); stressed_stats = summarize(selected_stressed)
    positive_underlyings, underlying_pnl = _group_profit_count(selected_rows, "underlying")
    month_pnl: dict[str, Decimal] = defaultdict(Decimal)
    for trade in selected_rows:
        month_pnl[f"{trade.session:%Y-%m}"] += trade.net_pnl
    positive_month_fraction = Decimal(sum(value > 0 for value in month_pnl.values())) / Decimal(5)
    neighbor_stats = {name: summarize(values) for name, values in pseudo.items()}
    positive_neighbor_fraction = Decimal(sum(value.net_pnl > 0 for value in neighbor_stats.values())) / Decimal(len(EQUITY_VARIANTS))
    target_stop_ratio = min((item.target_to_stop for item in selected_rows), default=Decimal(3))
    admission = admission_criteria(
        target_stop_ratio=target_stop_ratio,
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
    variants = {}
    for variant in EQUITY_VARIANTS:
        variants[variant.name] = {
            "parameters": asdict(variant),
            "development": asdict(summarize(development[variant.name])),
            "pseudo_oos": asdict(neighbor_stats[variant.name]),
            "pseudo_oos_trades": [asdict(item) for item in pseudo[variant.name]],
            "stressed_1_5x_costs": asdict(summarize(stressed[variant.name])),
        }
    result = {
        "schema_version": "afterimage-equity-leadlag-backtest-v1",
        "attempt_id": "equity_sector_index_leadlag_v4",
        "family": "sector basket lead predicts lagging QQQ/IWM catch-up, executed in shares",
        "data": {"source": cache["source"], "stock_cache_hash": cache["content_hash"], "feed": cache["stock"]["feed"], "timeframe": "15Min"},
        "selection": {"window": {"start": START.date(), "end": TRAINING_END}, "selected_variant": selected,
                      "development_metrics": asdict(summarize(development.get(selected or "", ()))), "folds": folds},
        "pseudo_oos": {"window": {"start": PSEUDO_OOS_START, "end": PSEUDO_OOS_END},
                       "label": "rolling/pseudo-OOS; never untouched", "evaluations": 1,
                       "selected_metrics": asdict(stats), "selected_trades": [asdict(item) for item in selected_rows],
                       "max_drawdown_r": _max_drawdown_r(selected_rows), "underlying_pnl": underlying_pnl,
                       "month_pnl": dict(month_pnl), "stressed_1_5x_costs": asdict(stressed_stats),
                       "positive_neighbor_fraction": positive_neighbor_fraction,
                       "largest_win_fraction_of_gross_profit": _profit_concentration(selected_rows)},
        "variants": variants,
        "admission": admission,
        "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "production_contract": {
            "signal_time": "11:45, 13:15, or 14:15 America/New_York after named stock bar completes",
            "execution": "next 15-minute QQQ/IWM bar open; $10,000 max notional; long/short shares",
            "bracket": "one-cent prices with after-cost target:stop >=3; stop-first same-bar convention; six-bar timeout",
            "risk": "global maximum one open strategy position; reject unavailable shorts and stale bars",
            "routing": "existing AFTERIMAGE warrant, governor, serialized Alpaca executor, lifecycle reconciler, and evidence vault",
        },
        "limitations": ["May-Sep is rolling/pseudo-OOS because prior attempts revealed part of the period.", "15-minute OHLC cannot establish intrabar ordering, so same-bar stop is assumed first.", "IEX is not the full SIP.", "Short-sale borrow availability and live spread can differ from historical assumptions."],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _update_ledger(status: str, result: Mapping[str, Any] | None = None) -> None:
    ledger=json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8")); ledger.pop("ledger_hash",None)
    attempts=[x for x in ledger["attempts"] if x.get("attempt_id")!="equity_sector_index_leadlag_v4"]
    entry:dict[str,Any]={"attempt_id":"equity_sector_index_leadlag_v4","status":status,"spec":"ATTEMPT_004_SPEC.md","instrument":"QQQ/IWM shares","predeclared_family":[asdict(x) for x in EQUITY_VARIANTS],"selection_window":{"start":START.date(),"end":TRAINING_END},"pseudo_oos_window":{"start":PSEUDO_OOS_START,"end":PSEUDO_OOS_END,"may_be_reused_as_untouched":False}}
    if result is not None: entry.update({"selected_variant":result["selection"]["selected_variant"],"pseudo_oos_metrics":result["pseudo_oos"]["selected_metrics"],"admission":result["admission"],"recommendation":result["decision"],"result_hash":result["result_hash"]})
    attempts.append(entry);ledger["attempts"]=attempts;ledger["ledger_hash"]=canonical_hash({k:v for k,v in ledger.items() if k!="ledger_hash"});_write_json(ATTEMPT_LEDGER,ledger)


def render_report(result: Mapping[str, Any]) -> str:
    stats=result["pseudo_oos"]["selected_metrics"]
    lines=["# Attempt 004 — liquid ETF lead–lag execution","",f"**{result['decision']}**. `{result['selection']['selected_variant']}`: n={stats['sample_count']}, net=${stats['net_pnl']}, expectancy={Decimal(str(stats['expectancy_r'])):.3f}R, PF={Decimal(str(stats['profit_factor'])):.2f}, hit={Decimal(str(stats['hit_rate'])):.1%}, max DD={Decimal(str(result['pseudo_oos']['max_drawdown_r'])):.2f}R.","","## Admission audit","","| Criterion | Pass |","|---|---|",*[f"| {k} | {v} |" for k,v in result["admission"]["criteria"].items()],"","## Full neighborhood","","| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name,row in result["variants"].items():
        d=row["development"];p=row["pseudo_oos"];s=row["stressed_1_5x_costs"]
        lines.append(f"| `{name}` | {d['sample_count']} | ${d['net_pnl']} | {p['sample_count']} | ${p['net_pnl']} | {Decimal(str(p['expectancy_r'])):.3f} | {Decimal(str(p['profit_factor'])):.2f} | ${s['net_pnl']} |")
    lines.extend(["","## Production contract","",*[f"- {k}: {v}" for k,v in result["production_contract"].items()],"","## Limitations","",*[f"- {x}" for x in result["limitations"]],""]);return "\n".join(lines)


def main() -> None:
    _update_ledger("planned");result=evaluate();_write_json(EQUITY_BACKTEST,result);EQUITY_REPORT.write_text(render_report(result),encoding="utf-8");_update_ledger("evaluated",result);print(json.dumps({"decision":result["decision"],"selected":result["selection"]["selected_variant"],"pseudo_oos":result["pseudo_oos"]["selected_metrics"],"admission":result["admission"]["criteria"]},default=str,sort_keys=True))


if __name__=="__main__":main()
