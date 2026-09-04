#!/usr/bin/env python3
"""Acquire development HYG/TLT bars and screen attempt 011 on 2023-2025."""

from __future__ import annotations

import argparse,json
from dataclasses import asdict
from datetime import UTC,date,datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    from .candidate import ScoredTrade,enforce_non_overlapping,select_on_training
    from .credit_impulse_candidate import VARIANTS,credit_impulse_signal
    from .multiday_rotation_candidate import DailyBar,MultiDayCosts,simulate_multiday_trade
    from .run_attempt008_development import aggregate_daily,load_stock
    from .run_attempt009_development import _metrics
    from .run_research import PROFILE,REPO,_paged_rows,_parse_timestamp,_write_json,canonical_hash
except ImportError:
    from candidate import ScoredTrade,enforce_non_overlapping,select_on_training  # type: ignore[no-redef]
    from credit_impulse_candidate import VARIANTS,credit_impulse_signal  # type: ignore[no-redef]
    from multiday_rotation_candidate import DailyBar,MultiDayCosts,simulate_multiday_trade  # type: ignore[no-redef]
    from run_attempt008_development import aggregate_daily,load_stock  # type: ignore[no-redef]
    from run_attempt009_development import _metrics  # type: ignore[no-redef]
    from run_research import PROFILE,REPO,_paged_rows,_parse_timestamp,_write_json,canonical_hash  # type: ignore[no-redef]

HERE=Path(__file__).resolve().parent;CACHE=HERE/'data'/'attempt011_credit_development_cache.json';OUTPUT=HERE/'results'/'attempt011_development.json';REPORT=HERE/'ATTEMPT_011_DEVELOPMENT.md';CLI=REPO/'.tools'/'bin'/'alpaca'
START=datetime(2023,1,1,tzinfo=UTC);END=datetime(2026,1,1,tzinfo=UTC);BASE=MultiDayCosts(Decimal('.0001'),Decimal('.005'));STRESS=MultiDayCosts(Decimal('.00015'),Decimal('.0075'))


def acquire(executable:Path,profile:str)->dict[str,Any]:
    bars=[];commands=[]
    for symbol in ('HYG','TLT'):
        rows,used=_paged_rows(executable,profile,('data','bars','--symbol',symbol,'--start',START.isoformat(),'--end',END.isoformat(),'--timeframe','1Day','--feed','iex','--adjustment','raw','--sort','asc','--limit','10000'),result_key='bars');bars.extend(rows);commands.extend(used)
    body={'schema_version':'afterimage-attempt011-credit-development-cache-v1','retrieved_at':datetime.now().astimezone().isoformat(),'source':'official Alpaca CLI 0.0.14 authenticated read-only data/bars endpoint','window':{'start':START,'end_exclusive':END},'feed':'iex','timeframe':'1Day','bars':sorted(bars,key=lambda x:(str(x.get('t')),str(x.get('symbol')))),'source_commands':commands};result={**body,'content_hash':canonical_hash(body)};_write_json(CACHE,result);return result


def _credit_daily(cache:dict[str,Any])->tuple[DailyBar,...]:
    body={k:v for k,v in cache.items() if k!='content_hash'}
    if canonical_hash(body)!=cache.get('content_hash'):raise ValueError('CREDIT_CACHE_HASH_MISMATCH')
    rows=[]
    for x in cache['bars']:
        ts=_parse_timestamp(str(x['t']));rows.append(DailyBar(str(x['symbol']),ts.date(),ts,Decimal(str(x['o'])),Decimal(str(x['h'])),Decimal(str(x['l'])),Decimal(str(x['c'])),int(x['v'])))
    return tuple(rows)


def evaluate(cache:dict[str,Any])->dict[str,Any]:
    daily=tuple((*aggregate_daily(load_stock()),*_credit_daily(cache)));sessions=sorted({b.session for b in daily if b.symbol=='SPY' and date(2023,1,3)<=b.session<=date(2025,12,31)});week_end={s:(i==len(sessions)-1 or sessions[i+1].isocalendar()[:2]!=s.isocalendar()[:2]) for i,s in enumerate(sessions)};signals={v.name:[] for v in VARIANTS}
    for s in sessions:
        for v in VARIANTS:
            try:x=credit_impulse_signal(v,daily,s,is_week_end=week_end[s])
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
    for year,minimum in ((2024,15),(2025,30)):
        dates=tuple(sorted({x.session for rows in scored.values() for x in rows if x.session.year<year}));chosen=select_on_training(scored,dates,minimum_samples=minimum);val=tuple(x for x in base.get(chosen or '',()) if x.session.year==year);folds.append({'validation_year':year,'selected_variant':chosen,'validation_metrics':_metrics(val)})
    dates=tuple(sorted({x.session for rows in scored.values() for x in rows}));selected=select_on_training(scored,dates,minimum_samples=60);variants={}
    for v in VARIANTS:
        rows=base[v.name];variants[v.name]={'parameters':asdict(v),'development_metrics':_metrics(rows),'year_metrics':{str(y):_metrics(tuple(x for x in rows if x.session.year==y)) for y in (2023,2024,2025)},'stressed_1_5x_costs':_metrics(stress[v.name])}
    rolling=tuple(x for f in folds for x in base.get(f['selected_variant'] or '',()) if x.session.year==f['validation_year']);adequate=selected is not None and variants[selected]['development_metrics']['profit_factor']>=2 and variants[selected]['development_metrics']['expectancy_r']>=Decimal('.25') and variants[selected]['development_metrics']['max_drawdown_r']<=6 and variants[selected]['stressed_1_5x_costs']['net_pnl']>0 and all(variants[selected]['year_metrics'][str(y)]['net_pnl']>0 for y in (2024,2025))
    r={'schema_version':'afterimage-attempt011-development-v1','attempt_id':'credit_duration_impulse_v11','scope':'development on revealed 2023-2025; no pre-2023 outcome evaluated','family_spec':'ATTEMPT_011_SPEC.md','credit_cache_hash':cache['content_hash'],'folds':folds,'rolling_development_validation':_metrics(rolling),'final_selected_variant':selected,'variants':variants,'development_gate':{'adequate':adequate}};r['result_hash']=canonical_hash(r);return r


def report(r):
    lines=['# Attempt 011 development — credit-duration impulse','',f"Development gate: **{'PASS' if r['development_gate']['adequate'] else 'REJECT'}**. Selected `{r['final_selected_variant']}`. No fresh year consumed.",'','| Variant | n | Net P&L | Exp/R | PF | DD/R | 1.5x P&L |','|---|---:|---:|---:|---:|---:|---:|']
    for n,x in r['variants'].items():m=x['development_metrics'];s=x['stressed_1_5x_costs'];lines.append(f"| `{n}` | {m['sample_count']} | ${m['net_pnl']} | {Decimal(str(m['expectancy_r'])):.3f} | {Decimal(str(m['profit_factor'])):.2f} | {Decimal(str(m['max_drawdown_r'])):.2f} | ${s['net_pnl']} |")
    lines.extend(['','## Expanding folds','','| Year | Selected | n | P&L | Exp/R | PF |','|---:|---|---:|---:|---:|---:|'])
    for f in r['folds']:m=f['validation_metrics'];lines.append(f"| {f['validation_year']} | `{f['selected_variant']}` | {m['sample_count']} | ${m['net_pnl']} | {Decimal(str(m['expectancy_r'])):.3f} | {Decimal(str(m['profit_factor'])):.2f} |")
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser();p.add_argument('--fetch',action='store_true');p.add_argument('--profile',default=PROFILE);p.add_argument('--cli',type=Path,default=CLI);a=p.parse_args();cache=acquire(a.cli,a.profile) if a.fetch else json.loads(CACHE.read_text());r=evaluate(cache);_write_json(OUTPUT,r);REPORT.write_text(report(r),encoding='utf-8');print(json.dumps({'selected':r['final_selected_variant'],'gate':r['development_gate'],'rolling':r['rolling_development_validation'],'variants':{n:x['development_metrics'] for n,x in r['variants'].items()}},default=str,sort_keys=True))


if __name__=='__main__':main()
