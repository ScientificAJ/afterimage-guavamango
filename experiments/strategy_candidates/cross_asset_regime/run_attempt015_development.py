#!/usr/bin/env python3
"""Screen near-unanimous breadth persistence on revealed 2023-2025."""
from __future__ import annotations
import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
try:
    from .candidate import ScoredTrade,enforce_non_overlapping,select_on_training
    from .multiday_rotation_candidate import MultiDayCosts,simulate_multiday_trade
    from .run_attempt008_development import aggregate_daily,load_stock
    from .run_attempt009_development import _metrics
    from .run_research import _write_json,canonical_hash
    from .unanimous_rotation_candidate import VARIANTS,unanimous_signal
except ImportError:
    from candidate import ScoredTrade,enforce_non_overlapping,select_on_training  # type: ignore[no-redef]
    from multiday_rotation_candidate import MultiDayCosts,simulate_multiday_trade  # type: ignore[no-redef]
    from run_attempt008_development import aggregate_daily,load_stock  # type: ignore[no-redef]
    from run_attempt009_development import _metrics  # type: ignore[no-redef]
    from run_research import _write_json,canonical_hash  # type: ignore[no-redef]
    from unanimous_rotation_candidate import VARIANTS,unanimous_signal  # type: ignore[no-redef]
HERE=Path(__file__).resolve().parent;OUTPUT=HERE/'results'/'attempt015_development.json';REPORT=HERE/'ATTEMPT_015_DEVELOPMENT.md';BASE=MultiDayCosts(Decimal('.0001'),Decimal('.005'));STRESS=MultiDayCosts(Decimal('.00015'),Decimal('.0075'))
def evaluate()->dict[str,Any]:
    daily=aggregate_daily(load_stock());sessions=sorted({b.session for b in daily if date(2023,1,3)<=b.session<=date(2025,12,31)});signals={v.name:[] for v in VARIANTS}
    for s in sessions:
        for v in VARIANTS:
            try:x=unanimous_signal(v,daily,s)
            except ValueError:continue
            if x is not None:signals[v.name].append(x)
    def sim(costs):
        out={}
        for v in VARIANTS:
            rows=[]
            for s in signals[v.name]:
                try:rows.append(simulate_multiday_trade(s,daily,v,costs))  # type: ignore[arg-type]
                except ValueError:continue
            out[v.name]=enforce_non_overlapping(rows)  # type: ignore[arg-type,assignment]
        return out
    base,stress=sim(BASE),sim(STRESS);scored={n:tuple(ScoredTrade(x.session,x.return_r,x.net_pnl) for x in rows) for n,rows in base.items()};folds=[]
    for year,minimum in ((2024,20),(2025,40)):
        dates=tuple(sorted({x.session for rows in scored.values() for x in rows if x.session.year<year}));chosen=select_on_training(scored,dates,minimum_samples=minimum);val=tuple(x for x in base.get(chosen or '',()) if x.session.year==year);folds.append({'validation_year':year,'selected_variant':chosen,'validation_metrics':_metrics(val)})
    dates=tuple(sorted({x.session for rows in scored.values() for x in rows}));selected=select_on_training(scored,dates,minimum_samples=60);variants={}
    for v in VARIANTS:
        rows=base[v.name];variants[v.name]={'parameters':asdict(v),'development_metrics':_metrics(rows),'year_metrics':{str(y):_metrics(tuple(x for x in rows if x.session.year==y)) for y in (2023,2024,2025)},'stressed_1_5x_costs':_metrics(stress[v.name])}
    rolling=tuple(x for f in folds for x in base.get(f['selected_variant'] or '',()) if x.session.year==f['validation_year']);neighbor_fraction=Decimal(sum(v['development_metrics']['net_pnl']>0 for v in variants.values()))/Decimal(len(variants));adequate=selected is not None and variants[selected]['development_metrics']['profit_factor']>=2 and variants[selected]['development_metrics']['expectancy_r']>=Decimal('.25') and variants[selected]['development_metrics']['max_drawdown_r']<=6 and variants[selected]['stressed_1_5x_costs']['net_pnl']>0 and all(variants[selected]['year_metrics'][str(y)]['net_pnl']>0 for y in (2024,2025)) and neighbor_fraction>=Decimal('.60')
    r={'schema_version':'afterimage-attempt015-development-v1','attempt_id':'unanimous_breadth_rotation_v15','scope':'development on revealed 2023-2025; no pre-2023 outcome evaluated','family_spec':'ATTEMPT_015_SPEC.md','folds':folds,'rolling_development_validation':_metrics(rolling),'final_selected_variant':selected,'positive_neighbor_fraction':neighbor_fraction,'variants':variants,'development_gate':{'adequate':adequate}};r['result_hash']=canonical_hash(r);return r
def report(r):
    lines=['# Attempt 015 development — near-unanimous breadth persistence','',f"Development gate: **{'PASS' if r['development_gate']['adequate'] else 'REJECT'}**. Selected `{r['final_selected_variant']}`. No fresh year consumed.",'','| Variant | n | Net P&L | Exp/R | PF | DD/R | 1.5x P&L |','|---|---:|---:|---:|---:|---:|---:|']
    for n,x in r['variants'].items():m=x['development_metrics'];s=x['stressed_1_5x_costs'];lines.append(f"| `{n}` | {m['sample_count']} | ${m['net_pnl']} | {Decimal(str(m['expectancy_r'])):.3f} | {Decimal(str(m['profit_factor'])):.2f} | {Decimal(str(m['max_drawdown_r'])):.2f} | ${s['net_pnl']} |")
    lines.extend(['','## Expanding folds','','| Year | Selected | n | P&L | Exp/R | PF |','|---:|---|---:|---:|---:|---:|'])
    for f in r['folds']:m=f['validation_metrics'];lines.append(f"| {f['validation_year']} | `{f['selected_variant']}` | {m['sample_count']} | ${m['net_pnl']} | {Decimal(str(m['expectancy_r'])):.3f} | {Decimal(str(m['profit_factor'])):.2f} |")
    return '\n'.join(lines)+'\n'
def main():
    r=evaluate();_write_json(OUTPUT,r);REPORT.write_text(report(r),encoding='utf-8');print(json.dumps({'selected':r['final_selected_variant'],'gate':r['development_gate'],'neighbor_fraction':r['positive_neighbor_fraction'],'rolling':r['rolling_development_validation'],'variants':{n:x['development_metrics'] for n,x in r['variants'].items()}},default=str,sort_keys=True))
if __name__=='__main__':main()
