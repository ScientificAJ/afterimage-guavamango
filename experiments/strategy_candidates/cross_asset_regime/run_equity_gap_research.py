#!/usr/bin/env python3
"""Run attempt 005: confirmed overnight gap continuation in liquid ETF shares."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import ScoredTrade, enforce_non_overlapping, select_on_training, summarize
    from .equity_candidate import EquityCosts, EquitySignal, EquityTrade, simulate_equity_trade
    from .gap_candidate import GapVariant, gap_signal
    from .run_gap_research import PSEUDO_OOS_END, PSEUDO_OOS_START, TRAINING_END, _group_profit_count, _max_drawdown_r, _profit_concentration, admission_criteria
    from .run_research import ATTEMPT_LEDGER, DATA_CACHE, ET, START, _stock_objects, _write_json, canonical_hash
except ImportError:
    from candidate import ScoredTrade, enforce_non_overlapping, select_on_training, summarize  # type: ignore[no-redef]
    from equity_candidate import EquityCosts, EquitySignal, EquityTrade, simulate_equity_trade  # type: ignore[no-redef]
    from gap_candidate import GapVariant, gap_signal  # type: ignore[no-redef]
    from run_gap_research import PSEUDO_OOS_END, PSEUDO_OOS_START, TRAINING_END, _group_profit_count, _max_drawdown_r, _profit_concentration, admission_criteria  # type: ignore[no-redef]
    from run_research import ATTEMPT_LEDGER, DATA_CACHE, ET, START, _stock_objects, _write_json, canonical_hash  # type: ignore[no-redef]


HERE=Path(__file__).resolve().parent
BACKTEST=HERE/"results"/"equity_gap_backtest.json"
REPORT=HERE/"ATTEMPT_005_REPORT.md"
BASE_COSTS=EquityCosts(Decimal("0.0001"),Decimal("0.005"))
STRESSED_COSTS=EquityCosts(Decimal("0.00015"),Decimal("0.0075"))


@dataclass(frozen=True)
class EquityGapVariant:
    name:str
    breadth_required:int
    minimum_mean_gap:Decimal
    stop_fraction:Decimal
    hold_bars:int=6


VARIANTS=tuple(
    EquityGapVariant(f"equity_gap_b{breadth}_m{int(gap*10000):02d}_s{int(stop*10000):02d}",breadth,gap,stop)
    for breadth in (4,5)
    for gap in (Decimal("0.0010"),Decimal("0.0020"))
    for stop in (Decimal("0.0015"),Decimal("0.0025"),Decimal("0.0035"))
)


def _signals(stock:Sequence[Any])->dict[str,tuple[EquitySignal,...]]:
    by_date:dict[date,list[Any]]=defaultdict(list)
    for bar in stock:by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    dates=sorted(by_date);rows:dict[str,list[EquitySignal]]={v.name:[] for v in VARIANTS}
    for index,session in enumerate(dates):
        if index==0 or not START.date()<=session<=PSEUDO_OOS_END:continue
        window=(*by_date[dates[index-1]],*by_date[session])
        for variant in VARIANTS:
            try:signal=gap_signal(GapVariant(variant.name,variant.breadth_required,variant.minimum_mean_gap,Decimal("0.20")),window,session)
            except ValueError:continue
            if signal is not None:rows[variant.name].append(EquitySignal(signal.session,signal.completed_at,signal.direction,signal.underlying,signal.reference_price,variant.name))
    return {name:tuple(values) for name,values in rows.items()}


def _evaluate(signals:Mapping[str,Sequence[EquitySignal]],stock:Sequence[Any],*,start:date,end:date,costs:EquityCosts)->dict[str,tuple[EquityTrade,...]]:
    by_date:dict[date,list[Any]]=defaultdict(list)
    for bar in stock:by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    lookup={v.name:v for v in VARIANTS};result={}
    for name,items in signals.items():
        trades=[]
        for signal in items:
            if not start<=signal.session<=end:continue
            try:trades.append(simulate_equity_trade(signal,by_date[signal.session],lookup[name],costs))  # type: ignore[arg-type]
            except ValueError:continue
        result[name]=enforce_non_overlapping(trades)  # type: ignore[arg-type]
    return result


def _scored(rows:Mapping[str,Sequence[EquityTrade]])->dict[str,tuple[ScoredTrade,...]]:
    return {name:tuple(ScoredTrade(x.session,x.return_r,x.net_pnl) for x in values) for name,values in rows.items()}


def aggregate_rolling_oos(
    development: Mapping[str, Sequence[Any]],
    fold_selections: Sequence[tuple[int, str | None]],
    pseudo: Mapping[str, Sequence[Any]],
    final_selected: str | None,
) -> tuple[Any, ...]:
    rows = []
    for month, selected in fold_selections:
        if selected is not None:
            rows.extend(item for item in development.get(selected, ()) if item.session.month == month)
    if final_selected is not None:
        rows.extend(pseudo.get(final_selected, ()))
    return tuple(sorted(rows, key=lambda item: item.session))


def evaluate()->dict[str,Any]:
    cache=json.loads(DATA_CACHE.read_text(encoding="utf-8"));stock=_stock_objects(cache["stock"]["bars"]);signals=_signals(stock)
    dev=_evaluate(signals,stock,start=START.date(),end=TRAINING_END,costs=BASE_COSTS)
    stressed_dev=_evaluate(signals,stock,start=START.date(),end=TRAINING_END,costs=STRESSED_COSTS)
    scored=_scored(dev);train_dates=tuple(sorted({x.session for values in scored.values() for x in values}));selected=select_on_training(scored,train_dates,minimum_samples=20)
    folds=[];fold_selections=[]
    for month in (3,4):
        tr=tuple(d for d in train_dates if d<date(2026,month,1));chosen=select_on_training(scored,tr,minimum_samples=6);validation=tuple(x for x in dev.get(chosen or "",()) if x.session.month==month);folds.append({"validation_month":month,"selected_variant":chosen,"metrics":asdict(summarize(validation))});fold_selections.append((month,chosen))
    pseudo=_evaluate(signals,stock,start=PSEUDO_OOS_START,end=PSEUDO_OOS_END,costs=BASE_COSTS);stressed=_evaluate(signals,stock,start=PSEUDO_OOS_START,end=PSEUDO_OOS_END,costs=STRESSED_COSTS)
    rows=pseudo.get(selected or "",());stress_rows=stressed.get(selected or "",());pseudo_stats=summarize(rows);pseudo_stress_stats=summarize(stress_rows)
    rolling=aggregate_rolling_oos(dev,fold_selections,pseudo,selected);rolling_stress=aggregate_rolling_oos(stressed_dev,fold_selections,stressed,selected)
    stats=summarize(rolling);stress_stats=summarize(rolling_stress)
    positive_underlyings,underlying_pnl=_group_profit_count(rolling,"underlying");month_pnl:dict[str,Decimal]=defaultdict(Decimal)
    for trade in rolling:month_pnl[f"{trade.session:%Y-%m}"]+=trade.net_pnl
    month_fraction=Decimal(sum(v>0 for v in month_pnl.values()))/Decimal(len(month_pnl) or 1)
    neighbors={};
    for variant in VARIANTS:
        diagnostic=tuple(x for x in dev[variant.name] if x.session.month in {3,4})+tuple(pseudo[variant.name]);neighbors[variant.name]=summarize(diagnostic)
    neighbor_fraction=Decimal(sum(v.net_pnl>0 for v in neighbors.values()))/Decimal(len(VARIANTS));ratio=min((x.target_to_stop for x in rolling),default=Decimal(3))
    admission=admission_criteria(target_stop_ratio=ratio,profit_factor=stats.profit_factor,expectancy_r=stats.expectancy_r,sample_count=stats.sample_count,max_drawdown_r=_max_drawdown_r(rolling),positive_underlyings=positive_underlyings,positive_regimes=sum(v>0 for v in month_pnl.values()),positive_month_fraction=month_fraction,stressed_net_pnl=stress_stats.net_pnl,positive_neighbor_fraction=neighbor_fraction,largest_win_fraction=_profit_concentration(rolling))
    variants={}
    for variant in VARIANTS:variants[variant.name]={"parameters":asdict(variant),"development":asdict(summarize(dev[variant.name])),"pseudo_oos":asdict(summarize(pseudo[variant.name])),"rolling_neighbor_diagnostic":asdict(neighbors[variant.name]),"pseudo_oos_trades":[asdict(x) for x in pseudo[variant.name]],"stressed_1_5x_costs":asdict(summarize(stressed[variant.name]))}
    result={"schema_version":"afterimage-equity-gap-backtest-v1","attempt_id":"equity_overnight_gap_v5","family":"confirmed cross-asset overnight gap continuation in QQQ/IWM shares","data":{"source":cache["source"],"stock_cache_hash":cache["content_hash"],"feed":cache["stock"]["feed"],"timeframe":"15Min"},"selection":{"window":{"start":START.date(),"end":TRAINING_END},"selected_variant":selected,"development_metrics":asdict(summarize(dev.get(selected or "",()))),"folds":folds},"rolling_oos":{"scope":"March/April expanding-fold validation plus frozen May-September pseudo-OOS","metrics":asdict(stats),"trades":[asdict(x) for x in rolling],"max_drawdown_r":_max_drawdown_r(rolling),"underlying_pnl":underlying_pnl,"month_pnl":dict(month_pnl),"stressed_1_5x_costs":asdict(stress_stats),"positive_neighbor_fraction":neighbor_fraction,"largest_win_fraction_of_gross_profit":_profit_concentration(rolling)},"pseudo_oos":{"window":{"start":PSEUDO_OOS_START,"end":PSEUDO_OOS_END},"label":"pseudo-OOS; never untouched","evaluations":1,"selected_metrics":asdict(pseudo_stats),"selected_trades":[asdict(x) for x in rows],"max_drawdown_r":_max_drawdown_r(rows),"stressed_1_5x_costs":asdict(pseudo_stress_stats)},"variants":variants,"admission":admission,"decision":"ADMIT" if admission["admitted"] else "REJECT","production_contract":{"signal":"09:45 ET after overnight breadth and both QQQ/IWM first-bar confirmation","instrument":"up to $10,000 QQQ or IWM shares, long or short","entry":"next 15-minute bar open with one bp adverse slippage","exit":"cent-rounded after-cost >=3R target / 1R stop; stop-first; six-bar timeout","risk":"max one open strategy position through AFTERIMAGE warrant/governor/serialized execution/lifecycle gates"},"limitations":["May-Sep is pseudo-OOS and March-Apr are expanding-fold validation; no later untouched calendar remains.","15-minute OHLC has no intrabar ordering; stop-first is conservative.","IEX is not SIP.","Historical short availability is not modeled."]};result["result_hash"]=canonical_hash(result);return result


def _ledger(status:str,result:Mapping[str,Any]|None=None)->None:
    ledger=json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"));ledger.pop("ledger_hash",None);attempts=[x for x in ledger["attempts"] if x.get("attempt_id")!="equity_overnight_gap_v5"];entry:dict[str,Any]={"attempt_id":"equity_overnight_gap_v5","status":status,"spec":"ATTEMPT_005_SPEC.md","instrument":"QQQ/IWM shares","predeclared_family":[asdict(x) for x in VARIANTS],"selection_window":{"start":START.date(),"end":TRAINING_END},"pseudo_oos_window":{"start":PSEUDO_OOS_START,"end":PSEUDO_OOS_END,"may_be_reused_as_untouched":False}}
    if result is not None:entry.update({"selected_variant":result["selection"]["selected_variant"],"pseudo_oos_metrics":result["pseudo_oos"]["selected_metrics"],"admission":result["admission"],"recommendation":result["decision"],"result_hash":result["result_hash"]})
    attempts.append(entry);ledger["attempts"]=attempts;ledger["ledger_hash"]=canonical_hash({k:v for k,v in ledger.items() if k!="ledger_hash"});_write_json(ATTEMPT_LEDGER,ledger)


def report(result:Mapping[str,Any])->str:
    s=result["rolling_oos"]["metrics"];p=result["pseudo_oos"]["selected_metrics"];lines=["# Attempt 005 — confirmed overnight-gap ETF shares","",f"**{result['decision']} on the 2026 rolling evidence only**. `{result['selection']['selected_variant']}`: n={s['sample_count']}, net=${s['net_pnl']}, expectancy={Decimal(str(s['expectancy_r'])):.3f}R, PF={Decimal(str(s['profit_factor'])):.2f}, hit={Decimal(str(s['hit_rate'])):.1%}, max DD={Decimal(str(result['rolling_oos']['max_drawdown_r'])):.2f}R.","",f"Rolling provenance: {result['rolling_oos']['scope']}. The May–September pseudo-OOS slice alone is n={p['sample_count']}, net=${p['net_pnl']}, expectancy={Decimal(str(p['expectancy_r'])):.3f}R, PF={Decimal(str(p['profit_factor'])):.2f}. See `FRESH_EXTENSION_REPORT.md` for the separately frozen 2025 backward validation and final rejection.","","## Admission audit — 2026 rolling evidence","","| Criterion | Pass |","|---|---|",*[f"| {k} | {v} |" for k,v in result["admission"]["criteria"].items()],"","## Neighborhood","","| Variant | Dev n | Dev P&L | Pseudo n | Pseudo P&L | Exp/R | PF | Stress P&L |","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for n,x in result["variants"].items():d=x["development"];p=x["pseudo_oos"];t=x["stressed_1_5x_costs"];lines.append(f"| `{n}` | {d['sample_count']} | ${d['net_pnl']} | {p['sample_count']} | ${p['net_pnl']} | {Decimal(str(p['expectancy_r'])):.3f} | {Decimal(str(p['profit_factor'])):.2f} | ${t['net_pnl']} |")
    lines.extend(["","## Production contract","",*[f"- {k}: {v}" for k,v in result["production_contract"].items()],"","## Limitations","",*[f"- {x}" for x in result["limitations"]],""]);return "\n".join(lines)


def main()->None:
    _ledger("planned");r=evaluate();_write_json(BACKTEST,r);REPORT.write_text(report(r),encoding="utf-8");_ledger("evaluated",r);print(json.dumps({"decision":r["decision"],"selected":r["selection"]["selected_variant"],"pseudo_oos":r["pseudo_oos"]["selected_metrics"],"admission":r["admission"]["criteria"]},default=str,sort_keys=True))


if __name__=="__main__":main()
