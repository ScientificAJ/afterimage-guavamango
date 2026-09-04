#!/usr/bin/env python3
"""Evaluate the frozen attempt-017 rule once on fresh 2021-2022 outcomes."""
from __future__ import annotations
import argparse,hashlib,json
from collections import defaultdict
from dataclasses import asdict,replace
from datetime import UTC,date,datetime,time
from decimal import Decimal
from pathlib import Path
from typing import Any,Mapping,Sequence
try:
    from .candidate import ET,enforce_non_overlapping,summarize
    from .lowvol_rotation_candidate import LowVolVariant,lowvol_signal
    from .multiday_rotation_candidate import DailyBar,MultiDayCosts,MultiDayTrade,RotationSignal,simulate_multiday_trade
    from .run_gap_research import _max_drawdown_r,_profit_concentration,admission_criteria
    from .run_research import ATTEMPT_LEDGER,PROFILE,REPO,_paged_rows,_parse_timestamp,_write_json,canonical_hash
except ImportError:
    from candidate import ET,enforce_non_overlapping,summarize  # type: ignore[no-redef]
    from lowvol_rotation_candidate import LowVolVariant,lowvol_signal  # type: ignore[no-redef]
    from multiday_rotation_candidate import DailyBar,MultiDayCosts,MultiDayTrade,RotationSignal,simulate_multiday_trade  # type: ignore[no-redef]
    from run_gap_research import _max_drawdown_r,_profit_concentration,admission_criteria  # type: ignore[no-redef]
    from run_research import ATTEMPT_LEDGER,PROFILE,REPO,_paged_rows,_parse_timestamp,_write_json,canonical_hash  # type: ignore[no-redef]
HERE=Path(__file__).resolve().parent;FROZEN=HERE/'results'/'attempt017_frozen_rule.json';CACHE=HERE/'data'/'attempt017_market_cache.json';OUTPUT=HERE/'results'/'attempt017_backtest.json';REPORT=HERE/'ATTEMPT_017_REPORT.md';CONTINUATION=HERE/'CONTINUATION_REPORT.md';CLI=REPO/'.tools'/'bin'/'alpaca'
START=datetime(2020,11,1,tzinfo=UTC);END=datetime(2023,1,1,tzinfo=UTC);VALID_START=date(2021,1,4);VALID_END=date(2022,12,30);SYMBOLS=('SPY','QQQ','IWM','XLK','XLF','XLE','XLV','XLY');BASE=MultiDayCosts(Decimal('.0001'),Decimal('.005'));STRESS=MultiDayCosts(Decimal('.00015'),Decimal('.0075'));PLUS2=MultiDayCosts(Decimal('.0003'),Decimal('.005'))
DEVELOPMENT_ATTEMPTS=(8,9,10,11,12,13,14,15,16)
def _body(a):return {k:v for k,v in a.items() if k not in {'rule_hash','rule_hash_scope','source_hashes'}}
def validate_rule(a:Mapping[str,Any],*,verify_sources:bool=True)->None:
    if canonical_hash(_body(a))!=str(a.get('rule_hash','')):raise ValueError('FROZEN_RULE_HASH_MISMATCH')
    if verify_sources:
        for n,h in a.get('source_hashes',{}).items():
            if hashlib.sha256((HERE/str(n)).read_bytes()).hexdigest()!=h:raise ValueError('FROZEN_SOURCE_HASH_MISMATCH')
def acquire(executable:Path,profile:str)->dict[str,Any]:
    bars=[];commands=[]
    for symbol in SYMBOLS:
        rows,used=_paged_rows(executable,profile,('data','bars','--symbol',symbol,'--start',START.isoformat(),'--end',END.isoformat(),'--timeframe','1Day','--feed','iex','--adjustment','raw','--sort','asc','--limit','10000'),result_key='bars');bars.extend(rows);commands.extend(used)
    body={'schema_version':'afterimage-attempt017-market-cache-v1','retrieved_at':datetime.now().astimezone().isoformat(),'source':'official Alpaca CLI 0.0.14 authenticated read-only data/bars endpoint','window':{'start':START,'end_exclusive':END},'validation_window':{'start':VALID_START,'end':VALID_END},'feed':'iex','timeframe':'1Day','adjustment':'raw','bars':sorted(bars,key=lambda x:(str(x.get('t')),str(x.get('symbol')))),'source_commands':commands};r={**body,'content_hash':canonical_hash(body)};_write_json(CACHE,r);return r
def _daily(cache:Mapping[str,Any])->tuple[DailyBar,...]:
    body={k:v for k,v in cache.items() if k!='content_hash'}
    if canonical_hash(body)!=cache.get('content_hash'):raise ValueError('CACHE_HASH_MISMATCH')
    rows=[]
    for x in cache['bars']:
        ts=_parse_timestamp(str(x['t']));session=ts.date();rows.append(DailyBar(str(x['symbol']),session,datetime.combine(session,time(16),ET),Decimal(str(x['o'])),Decimal(str(x['h'])),Decimal(str(x['l'])),Decimal(str(x['c'])),int(x['v'])))
    return tuple(sorted(rows,key=lambda b:(b.session,b.symbol)))
def _variant(a):
    r=a['rule'];return LowVolVariant(str(a['selected_variant']),Decimal(str(r['maximum_mean_abs_spy_return'])),Decimal(str(r['stop_atr_multiplier'])),int(r['hold_sessions']))
def _signals(daily:Sequence[DailyBar],v:LowVolVariant)->tuple[RotationSignal,...]:
    out=[]
    for s in sorted({b.session for b in daily if b.symbol=='SPY' and VALID_START<=b.session<=VALID_END}):
        try:x=lowvol_signal(v,daily,s)
        except ValueError:continue
        if x is not None:out.append(x)
    return tuple(out)
def _evaluate(signals:Sequence[RotationSignal],daily:Sequence[DailyBar],v:LowVolVariant,costs:MultiDayCosts,*,delay:int=0)->tuple[MultiDayTrade,...]:
    sessions=sorted({b.session for b in daily if b.symbol=='SPY'});next_session={s:sessions[i+1] for i,s in enumerate(sessions[:-1])};rows=[]
    for x in signals:
        shifted=x
        if delay:
            if x.session not in next_session:continue
            shifted=replace(x,session=next_session[x.session])
        try:rows.append(simulate_multiday_trade(shifted,daily,v,costs))
        except ValueError:continue
    return enforce_non_overlapping(rows)  # type: ignore[arg-type,return-value]
def _metrics(rows:Sequence[MultiDayTrade])->dict[str,Any]:return {**asdict(summarize(rows)),'max_drawdown_r':_max_drawdown_r(rows),'largest_win_fraction_of_gross_profit':_profit_concentration(rows),'minimum_after_cost_target_to_stop':min((x.target_to_stop for x in rows),default=Decimal(0))}  # type: ignore[arg-type]
def _groups(rows:Sequence[MultiDayTrade],field:str)->dict[str,dict[str,Any]]:
    g=defaultdict(list)
    for x in rows:g[x.session.strftime('%Y-%m') if field=='month' else str(getattr(x,field))].append(x)
    return {k:_metrics(v) for k,v in sorted(g.items())}
def evaluate(cache:Mapping[str,Any],a:Mapping[str,Any])->dict[str,Any]:
    validate_rule(a);daily=_daily(cache);v=_variant(a);signals=_signals(daily,v);base=_evaluate(signals,daily,v,BASE);stress=_evaluate(signals,daily,v,STRESS);plus2=_evaluate(signals,daily,v,PLUS2);delay=_evaluate(signals,daily,v,BASE,delay=1);m=_metrics(base);sm=_metrics(stress);months=_groups(base,'month');symbols=_groups(base,'underlying');years=_groups(base,'session') if False else {str(y):_metrics(tuple(x for x in base if x.session.year==y)) for y in (2021,2022)};month_fraction=Decimal(sum(x['net_pnl']>0 for x in months.values()))/Decimal(len(months) or 1);positive_symbols=sum(x['net_pnl']>0 for x in symbols.values())
    dev=json.loads((HERE/'results'/'attempt014_development.json').read_text());db={k:v for k,v in dev.items() if k!='result_hash'}
    if canonical_hash(db)!=dev['result_hash']:raise ValueError('DEVELOPMENT_HASH_MISMATCH')
    neighbor=Decimal(str(dev['positive_neighbor_fraction']));admission=admission_criteria(target_stop_ratio=Decimal(str(m['minimum_after_cost_target_to_stop'])),profit_factor=Decimal(str(m['profit_factor'])),expectancy_r=Decimal(str(m['expectancy_r'])),sample_count=int(m['sample_count']),max_drawdown_r=Decimal(str(m['max_drawdown_r'])),positive_underlyings=positive_symbols,positive_regimes=1 if m['net_pnl']>0 else 0,positive_month_fraction=month_fraction,stressed_net_pnl=Decimal(str(sm['net_pnl'])),positive_neighbor_fraction=neighbor,largest_win_fraction=Decimal(str(m['largest_win_fraction_of_gross_profit'])))
    temporal={'fresh_2021_and_2022_both_profitable':all(x['net_pnl']>0 for x in years.values()),'development_2023_2024_2025_all_profitable':all(Decimal(str(dev['variants'][a['selected_variant']]['year_metrics'][str(y)]['net_pnl']))>0 for y in (2023,2024,2025))};admission['criteria'].update(temporal);admission['admitted']=admission['admitted'] and all(temporal.values())
    r={'schema_version':'afterimage-attempt017-fresh-validation-v1','attempt_id':'frozen_lowvol_consensus_v17','rule_hash':a['rule_hash'],'selected_variant':a['selected_variant'],'provenance':{'label':'fresh 2021-2022 outcome validation; no outcome in this block used in design','caveat':a['fresh_outcome_validation']['provenance_caveat'],'evaluations':1,'cache_hash':cache['content_hash'],'source':cache['source'],'feed':cache['feed'],'timeframe':cache['timeframe']},'fresh_2021_2022':{'metrics':m,'trades':[asdict(x) for x in base],'year_metrics':years,'month_metrics':months,'positive_month_fraction':month_fraction,'symbol_metrics':symbols,'positive_symbol_count':positive_symbols,'stressed_1_5x_costs':sm,'plus_two_bps_slippage_each_side':_metrics(plus2),'one_session_entry_delay':_metrics(delay)},'development_reference':{'metrics':dev['variants'][a['selected_variant']]['development_metrics'],'year_metrics':dev['variants'][a['selected_variant']]['year_metrics'],'stressed_1_5x_costs':dev['variants'][a['selected_variant']]['stressed_1_5x_costs'],'positive_neighbor_fraction':neighbor,'result_hash':dev['result_hash']},'admission':admission,'decision':'ADMIT' if admission['admitted'] else 'REJECT','limitations':['Fresh block is backward validation, not chronological forward OOS.','Alpaca IEX daily OHLC is not SIP and has no intraday path; stop-first is conservative.','Historical liquidity, market impact, and queue position are not modeled.']};r['result_hash']=canonical_hash(r);return r
def report(r):
    m=r['fresh_2021_2022']['metrics'];lines=['# Attempt 017 — frozen low-noise consensus validation','',f"**{r['decision']}**. Fresh 2021–2022: n={m['sample_count']}, net=${m['net_pnl']}, expectancy={Decimal(str(m['expectancy_r'])):.3f}R, PF={Decimal(str(m['profit_factor'])):.2f}, max DD={Decimal(str(m['max_drawdown_r'])):.2f}R.",'',f"Rule hash: `{r['rule_hash']}`. No 2021–2022 outcome was used in design.",'','## Admission audit','','| Criterion | Pass |','|---|---|',*[f"| {k} | {v} |" for k,v in r['admission']['criteria'].items()],'','## Year stability','','| Year | n | P&L | Exp/R | PF | DD/R |','|---:|---:|---:|---:|---:|---:|']
    for y,x in r['fresh_2021_2022']['year_metrics'].items():lines.append(f"| {y} | {x['sample_count']} | ${x['net_pnl']} | {Decimal(str(x['expectancy_r'])):.3f} | {Decimal(str(x['profit_factor'])):.2f} | {Decimal(str(x['max_drawdown_r'])):.2f} |")
    lines.extend(['','## Cost and delay stress','','| Scenario | n | P&L | Exp/R | PF | DD/R |','|---|---:|---:|---:|---:|---:|'])
    for label,key in [('1.5x costs','stressed_1_5x_costs'),('+2 bp/side','plus_two_bps_slippage_each_side'),('one-session delay','one_session_entry_delay')]:
        x=r['fresh_2021_2022'][key];lines.append(f"| {label} | {x['sample_count']} | ${x['net_pnl']} | {Decimal(str(x['expectancy_r'])):.3f} | {Decimal(str(x['profit_factor'])):.2f} | {Decimal(str(x['max_drawdown_r'])):.2f} |")
    lines.extend(['','## Symbol stability','','| Symbol | n | P&L | Exp/R | PF |','|---|---:|---:|---:|---:|'])
    for k,x in r['fresh_2021_2022']['symbol_metrics'].items():lines.append(f"| {k} | {x['sample_count']} | ${x['net_pnl']} | {Decimal(str(x['expectancy_r'])):.3f} | {Decimal(str(x['profit_factor'])):.2f} |")
    lines.extend(['','## Month stability','','| Month | n | P&L | Exp/R | PF |','|---|---:|---:|---:|---:|'])
    for k,x in r['fresh_2021_2022']['month_metrics'].items():lines.append(f"| {k} | {x['sample_count']} | ${x['net_pnl']} | {Decimal(str(x['expectancy_r'])):.3f} | {Decimal(str(x['profit_factor'])):.2f} |")
    lines.extend(['','## Limitations','',*[f"- {x}" for x in r['limitations']],'']);return '\n'.join(lines)
def _update_ledger(r):
    ledger=json.loads(ATTEMPT_LEDGER.read_text());ledger.pop('ledger_hash',None);attempts=list(ledger['attempts']);existing={x['attempt_id'] for x in attempts}
    for n in DEVELOPMENT_ATTEMPTS:
        p=HERE/'results'/f'attempt{n:03d}_development.json';d=json.loads(p.read_text());attempt_id=d['attempt_id']
        if attempt_id in existing:continue
        selected=d.get('final_selected_variant');attempts.append({'attempt_id':attempt_id,'status':'rejected_in_development','spec':d['family_spec'],'selected_variant':selected,'development_metrics':d['variants'].get(selected or '',{}).get('development_metrics',{}),'rolling_development_validation':d['rolling_development_validation'],'recommendation':'REJECT_DEVELOPMENT','result_hash':d['result_hash']});existing.add(attempt_id)
    attempts=[x for x in attempts if x.get('attempt_id')!=r['attempt_id']];attempts.append({'attempt_id':r['attempt_id'],'status':'evaluated','spec':'ATTEMPT_017_SPEC.md','rule_hash':r['rule_hash'],'selected_variant':r['selected_variant'],'fresh_metrics':r['fresh_2021_2022']['metrics'],'admission':r['admission'],'recommendation':r['decision'],'result_hash':r['result_hash']});ledger['attempts']=attempts;ledger['ledger_hash']=canonical_hash(ledger);_write_json(ATTEMPT_LEDGER,ledger)
def continuation_report(r):
    lines=['# Continued discovery after attempts 001–007','',f"Attempts 001–007 are sealed by snapshot hash `d9aa8d0820fe58c9cacf814da1c64cde5333cb3248f69c46778c5aad02218bb7`.",'','| Attempt | Family | Selected | Dev n | Dev Exp/R | Dev PF | Dev DD/R | Disposition |','|---:|---|---|---:|---:|---:|---:|---|']
    for n in DEVELOPMENT_ATTEMPTS:
        d=json.loads((HERE/'results'/f'attempt{n:03d}_development.json').read_text());s=d.get('final_selected_variant');m=d['variants'].get(s or '',{}).get('development_metrics',{});lines.append(f"| {n:03d} | {d['attempt_id']} | `{s}` | {m.get('sample_count',0)} | {Decimal(str(m.get('expectancy_r',0))):.3f} | {Decimal(str(m.get('profit_factor',0))):.2f} | {Decimal(str(m.get('max_drawdown_r',0))):.2f} | REJECT development |")
    m=r['fresh_2021_2022']['metrics'];lines.extend(['',f"Attempt 017 froze `{r['selected_variant']}` under `{r['rule_hash']}` before the fresh block. Fresh result: n={m['sample_count']}, net=${m['net_pnl']}, expectancy={Decimal(str(m['expectancy_r'])):.3f}R, PF={Decimal(str(m['profit_factor'])):.2f}, max DD={Decimal(str(m['max_drawdown_r'])):.2f}R. Final decision: **{r['decision']}**.",'','See `ATTEMPT_017_REPORT.md` and `results/attempt017_backtest.json` for every gate and trade.']);return '\n'.join(lines)+'\n'
def main():
    p=argparse.ArgumentParser();p.add_argument('--fetch',action='store_true');p.add_argument('--profile',default=PROFILE);p.add_argument('--cli',type=Path,default=CLI);x=p.parse_args();a=json.loads(FROZEN.read_text());validate_rule(a);cache=acquire(x.cli,x.profile) if x.fetch else json.loads(CACHE.read_text());r=evaluate(cache,a);_write_json(OUTPUT,r);REPORT.write_text(report(r),encoding='utf-8');CONTINUATION.write_text(continuation_report(r),encoding='utf-8');_update_ledger(r);print(json.dumps({'decision':r['decision'],'fresh':r['fresh_2021_2022']['metrics'],'admission':r['admission']['criteria']},default=str,sort_keys=True))
if __name__=='__main__':main()
