#!/usr/bin/env python3
"""Screen the fixed attempt-009 breakout family on revealed 2023-2025."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .breakout_candidate import VARIANTS, breakout_signal
    from .candidate import ScoredTrade, enforce_non_overlapping, select_on_training, summarize
    from .multiday_rotation_candidate import MultiDayCosts, MultiDayTrade, RotationSignal, simulate_multiday_trade
    from .run_attempt008_development import aggregate_daily, load_stock
    from .run_gap_research import _max_drawdown_r, _profit_concentration
    from .run_research import _write_json, canonical_hash
except ImportError:
    from breakout_candidate import VARIANTS, breakout_signal  # type: ignore[no-redef]
    from candidate import ScoredTrade, enforce_non_overlapping, select_on_training, summarize  # type: ignore[no-redef]
    from multiday_rotation_candidate import MultiDayCosts, MultiDayTrade, RotationSignal, simulate_multiday_trade  # type: ignore[no-redef]
    from run_attempt008_development import aggregate_daily, load_stock  # type: ignore[no-redef]
    from run_gap_research import _max_drawdown_r, _profit_concentration  # type: ignore[no-redef]
    from run_research import _write_json, canonical_hash  # type: ignore[no-redef]


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "results" / "attempt009_development.json"
REPORT = HERE / "ATTEMPT_009_DEVELOPMENT.md"
START = date(2023, 1, 3)
END = date(2025, 12, 31)
BASE = MultiDayCosts(Decimal("0.0001"), Decimal("0.005"))
STRESS = MultiDayCosts(Decimal("0.00015"), Decimal("0.0075"))


def _metrics(rows: Sequence[MultiDayTrade]) -> dict[str, Any]:
    return {**asdict(summarize(rows)), "max_drawdown_r": _max_drawdown_r(rows), "largest_win_fraction_of_gross_profit": _profit_concentration(rows), "minimum_after_cost_target_to_stop": min((row.target_to_stop for row in rows), default=Decimal(0))}  # type: ignore[arg-type]


def evaluate() -> dict[str, Any]:
    daily = aggregate_daily(load_stock())
    sessions = sorted({bar.session for bar in daily if START <= bar.session <= END})
    signals: dict[str, list[RotationSignal]] = {variant.name: [] for variant in VARIANTS}
    for session in sessions:
        for variant in VARIANTS:
            try: signal = breakout_signal(variant, daily, session)
            except ValueError: continue
            if signal is not None: signals[variant.name].append(signal)
    def simulate(costs: MultiDayCosts) -> dict[str, tuple[MultiDayTrade, ...]]:
        rows = {}
        for variant in VARIANTS:
            candidates = []
            for signal in signals[variant.name]:
                try: candidates.append(simulate_multiday_trade(signal, daily, variant, costs))  # type: ignore[arg-type]
                except ValueError: continue
            rows[variant.name] = enforce_non_overlapping(candidates)  # type: ignore[arg-type,assignment]
        return rows
    base, stress = simulate(BASE), simulate(STRESS)
    scored = {name: tuple(ScoredTrade(row.session,row.return_r,row.net_pnl) for row in rows) for name,rows in base.items()}
    folds=[]
    for year,minimum in ((2024,20),(2025,40)):
        dates=tuple(sorted({row.session for rows in scored.values() for row in rows if row.session.year<year}))
        chosen=select_on_training(scored,dates,minimum_samples=minimum)
        validation=tuple(row for row in base.get(chosen or "",()) if row.session.year==year)
        folds.append({"validation_year":year,"selected_variant":chosen,"validation_metrics":_metrics(validation)})
    all_dates=tuple(sorted({row.session for rows in scored.values() for row in rows}))
    selected=select_on_training(scored,all_dates,minimum_samples=60)
    variants={}
    for variant in VARIANTS:
        rows=base[variant.name]
        variants[variant.name]={"parameters":asdict(variant),"development_metrics":_metrics(rows),"year_metrics":{str(y):_metrics(tuple(row for row in rows if row.session.year==y)) for y in (2023,2024,2025)},"stressed_1_5x_costs":_metrics(stress[variant.name])}
    rolling=tuple(row for fold in folds for row in base.get(fold["selected_variant"] or "",()) if row.session.year==fold["validation_year"])
    result={"schema_version":"afterimage-attempt009-development-v1","attempt_id":"multiday_channel_breakout_v9","scope":"development only on revealed 2023-2025; no 2022 outcome evaluated","family_spec":"ATTEMPT_009_SPEC.md","folds":folds,"rolling_development_validation":_metrics(rolling),"final_selected_variant":selected,"variants":variants}
    result["development_gate"]={"adequate":selected is not None and all(variants[selected]["year_metrics"][str(y)]["net_pnl"]>0 for y in (2024,2025)) and variants[selected]["development_metrics"]["profit_factor"]>=2 and variants[selected]["development_metrics"]["expectancy_r"]>=Decimal("0.25") and variants[selected]["development_metrics"]["max_drawdown_r"]<=6}
    result["result_hash"]=canonical_hash(result);return result


def report(r:Mapping[str,Any])->str:
    lines=["# Attempt 009 development — ETF channel breakout","",f"Development gate: **{'PASS' if r['development_gate']['adequate'] else 'REJECT'}**. Selected `{r['final_selected_variant']}`. No fresh year consumed.","","| Variant | n | Net P&L | Exp/R | PF | DD/R | 1.5x P&L |","|---|---:|---:|---:|---:|---:|---:|"]
    for n,x in r['variants'].items():
        m=x['development_metrics'];s=x['stressed_1_5x_costs'];lines.append(f"| `{n}` | {m['sample_count']} | ${m['net_pnl']} | {Decimal(str(m['expectancy_r'])):.3f} | {Decimal(str(m['profit_factor'])):.2f} | {Decimal(str(m['max_drawdown_r'])):.2f} | ${s['net_pnl']} |")
    lines.extend(["","## Expanding folds","","| Year | Selected | n | P&L | Exp/R | PF |","|---:|---|---:|---:|---:|---:|"])
    for f in r['folds']:
        m=f['validation_metrics'];lines.append(f"| {f['validation_year']} | `{f['selected_variant']}` | {m['sample_count']} | ${m['net_pnl']} | {Decimal(str(m['expectancy_r'])):.3f} | {Decimal(str(m['profit_factor'])):.2f} |")
    return '\n'.join(lines)+"\n"


def main()->None:
    r=evaluate();_write_json(OUTPUT,r);REPORT.write_text(report(r),encoding='utf-8');print(json.dumps({"selected":r['final_selected_variant'],"gate":r['development_gate'],"rolling":r['rolling_development_validation'],"variants":{n:x['development_metrics'] for n,x in r['variants'].items()}},default=str,sort_keys=True))


if __name__=='__main__':main()
