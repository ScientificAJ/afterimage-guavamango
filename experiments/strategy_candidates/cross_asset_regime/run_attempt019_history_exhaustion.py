#!/usr/bin/env python3
"""Consume all remaining pre-2021 Alpaca history with the unchanged attempt-017 rule."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import ET, enforce_non_overlapping
    from .lowvol_rotation_candidate import LowVolVariant, lowvol_signal
    from .multiday_rotation_candidate import (
        DailyBar,
        MultiDayCosts,
        MultiDayTrade,
        RotationSignal,
        simulate_multiday_trade,
    )
    from .run_attempt017_validation import (
        _daily,
        _metrics,
        _variant,
        validate_rule,
    )
    from .run_gap_research import admission_criteria
    from .run_research import (
        ATTEMPT_LEDGER,
        PROFILE,
        REPO,
        _paged_rows,
        _write_json,
        canonical_hash,
    )
except ImportError:
    from candidate import ET, enforce_non_overlapping  # type: ignore[no-redef]
    from lowvol_rotation_candidate import LowVolVariant, lowvol_signal  # type: ignore[no-redef]
    from multiday_rotation_candidate import (  # type: ignore[no-redef]
        DailyBar,
        MultiDayCosts,
        MultiDayTrade,
        RotationSignal,
        simulate_multiday_trade,
    )
    from run_attempt017_validation import (  # type: ignore[no-redef]
        _daily,
        _metrics,
        _variant,
        validate_rule,
    )
    from run_gap_research import admission_criteria  # type: ignore[no-redef]
    from run_research import (  # type: ignore[no-redef]
        ATTEMPT_LEDGER,
        PROFILE,
        REPO,
        _paged_rows,
        _write_json,
        canonical_hash,
    )


HERE = Path(__file__).resolve().parent
AUDIT = HERE / "results" / "attempt019_frozen_audit.json"
FROZEN_RULE = HERE / "results" / "attempt017_frozen_rule.json"
CACHE = HERE / "data" / "attempt019_market_cache.json"
OUTPUT = HERE / "results" / "attempt019_history_exhaustion.json"
REPORT = HERE / "ATTEMPT_019_REPORT.md"
FINAL_REPORT = HERE / "FINAL_DISCOVERY_REPORT.md"
PRIOR_RESULT = HERE / "results" / "attempt017_backtest.json"
CLI = REPO / ".tools" / "bin" / "alpaca"
SYMBOLS = ("SPY", "QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY")
BASE = MultiDayCosts(Decimal(".0001"), Decimal(".005"))
STRESS = MultiDayCosts(Decimal(".00015"), Decimal(".0075"))
PLUS_TWO_BPS = MultiDayCosts(Decimal(".0003"), Decimal(".005"))


def _audit_body(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in audit.items()
        if key not in {"audit_hash", "audit_hash_scope", "source_hashes"}
    }


def validate_audit(audit: Mapping[str, Any], *, verify_sources: bool = True) -> None:
    if canonical_hash(_audit_body(audit)) != str(audit.get("audit_hash", "")):
        raise ValueError("AUDIT_HASH_MISMATCH")
    if verify_sources:
        for name, expected in audit.get("source_hashes", {}).items():
            actual = hashlib.sha256((HERE / str(name)).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"AUDIT_SOURCE_HASH_MISMATCH:{name}")
        rule = json.loads(FROZEN_RULE.read_text(encoding="utf-8"))
        validate_rule(rule)
        if rule["rule_hash"] != audit["source_rule"]["rule_hash"]:
            raise ValueError("AUDIT_RULE_HASH_MISMATCH")


def acquire(executable: Path, profile: str, audit: Mapping[str, Any]) -> dict[str, Any]:
    requested = audit["requested_history"]
    start = datetime.fromisoformat(f"{requested['start']}T00:00:00+00:00")
    end = datetime.fromisoformat(f"{requested['end_exclusive']}T00:00:00+00:00")
    bars: list[dict[str, Any]] = []
    commands: list[list[str]] = []
    availability: dict[str, dict[str, Any]] = {}
    for symbol in SYMBOLS:
        rows, used = _paged_rows(
            executable,
            profile,
            (
                "data",
                "bars",
                "--symbol",
                symbol,
                "--start",
                start.isoformat(),
                "--end",
                end.isoformat(),
                "--timeframe",
                "1Day",
                "--feed",
                "iex",
                "--adjustment",
                "raw",
                "--sort",
                "asc",
                "--limit",
                "10000",
            ),
            result_key="bars",
        )
        bars.extend(rows)
        commands.extend(used)
        timestamps = sorted(str(row["t"]) for row in rows)
        availability[symbol] = {
            "bar_count": len(rows),
            "earliest_timestamp": timestamps[0] if timestamps else None,
            "latest_timestamp": timestamps[-1] if timestamps else None,
        }
    body = {
        "schema_version": "afterimage-attempt019-market-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only data/bars endpoint",
        "request": requested,
        "feed": "iex",
        "timeframe": "1Day",
        "adjustment": "raw",
        "availability": availability,
        "bars": sorted(bars, key=lambda row: (str(row.get("t")), str(row.get("symbol")))),
        "source_commands": commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    _write_json(CACHE, result)
    return result


def _common_sessions(daily: Sequence[DailyBar]) -> tuple[date, ...]:
    by_symbol = {symbol: {bar.session for bar in daily if bar.symbol == symbol} for symbol in SYMBOLS}
    if any(not sessions for sessions in by_symbol.values()):
        return ()
    return tuple(sorted(set.intersection(*(sessions for sessions in by_symbol.values()))))


def _signals(
    daily: Sequence[DailyBar], variant: LowVolVariant, eligible_sessions: Sequence[date]
) -> tuple[RotationSignal, ...]:
    signals: list[RotationSignal] = []
    for session in eligible_sessions:
        try:
            signal = lowvol_signal(variant, daily, session)
        except ValueError:
            continue
        if signal is not None:
            signals.append(signal)
    return tuple(signals)


def _evaluate(
    signals: Sequence[RotationSignal],
    daily: Sequence[DailyBar],
    variant: LowVolVariant,
    costs: MultiDayCosts,
    *,
    outcome_end: date,
    delay: int = 0,
) -> tuple[MultiDayTrade, ...]:
    sessions = sorted({bar.session for bar in daily if bar.symbol == "SPY"})
    next_session = {session: sessions[index + 1] for index, session in enumerate(sessions[:-1])}
    rows: list[MultiDayTrade] = []
    for signal in signals:
        shifted = signal
        if delay:
            if signal.session not in next_session:
                continue
            shifted = replace(signal, session=next_session[signal.session])
        try:
            trade = simulate_multiday_trade(shifted, daily, variant, costs)
        except ValueError:
            continue
        if trade.exit_at.astimezone(ET).date() <= outcome_end:
            rows.append(trade)
    return enforce_non_overlapping(rows)  # type: ignore[arg-type,return-value]


def _group_metrics(rows: Sequence[MultiDayTrade], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[MultiDayTrade]] = defaultdict(list)
    for trade in rows:
        if field == "month":
            key = trade.session.strftime("%Y-%m")
        elif field == "year":
            key = str(trade.session.year)
        else:
            key = str(getattr(trade, field))
        grouped[key].append(trade)
    return {key: _metrics(values) for key, values in sorted(grouped.items())}


def _trade_from_json(value: Mapping[str, Any]) -> MultiDayTrade:
    return MultiDayTrade(
        session=date.fromisoformat(str(value["session"])),
        variant=str(value["variant"]),
        direction=str(value["direction"]),  # type: ignore[arg-type]
        underlying=str(value["underlying"]),
        regime=str(value["regime"]),
        entry_at=datetime.fromisoformat(str(value["entry_at"])),
        exit_at=datetime.fromisoformat(str(value["exit_at"])),
        shares=int(value["shares"]),
        raw_entry=Decimal(str(value["raw_entry"])),
        entry_fill=Decimal(str(value["entry_fill"])),
        stop_price=Decimal(str(value["stop_price"])),
        target_price=Decimal(str(value["target_price"])),
        exit_fill=Decimal(str(value["exit_fill"])),
        net_pnl=Decimal(str(value["net_pnl"])),
        return_r=Decimal(str(value["return_r"])),
        outcome=str(value["outcome"]),  # type: ignore[arg-type]
        modeled_fees=Decimal(str(value["modeled_fees"])),
        modeled_slippage=Decimal(str(value["modeled_slippage"])),
        target_to_stop=Decimal(str(value["target_to_stop"])),
    )


def _verified_prior() -> dict[str, Any]:
    prior = json.loads(PRIOR_RESULT.read_text(encoding="utf-8"))
    body = {key: value for key, value in prior.items() if key != "result_hash"}
    if canonical_hash(body) != prior["result_hash"]:
        raise ValueError("PRIOR_RESULT_HASH_MISMATCH")
    return prior


def evaluate(
    cache: Mapping[str, Any], audit: Mapping[str, Any], frozen_rule: Mapping[str, Any]
) -> dict[str, Any]:
    validate_audit(audit)
    validate_rule(frozen_rule)
    daily = _daily(cache)
    variant = _variant(frozen_rule)
    common = _common_sessions(daily)
    warmup = int(audit["requested_history"]["warmup_sessions"])
    if len(common) <= warmup:
        raise ValueError("INSUFFICIENT_COMMON_HISTORY_FOR_AUDIT")
    outcome_end = date.fromisoformat(audit["requested_history"]["outcome_end"])
    eligible = tuple(session for session in common[warmup - 1 :] if session <= outcome_end)
    signals = _signals(daily, variant, eligible)
    base = _evaluate(signals, daily, variant, BASE, outcome_end=outcome_end)
    stress = _evaluate(signals, daily, variant, STRESS, outcome_end=outcome_end)
    plus_two = _evaluate(signals, daily, variant, PLUS_TWO_BPS, outcome_end=outcome_end)
    delay = _evaluate(signals, daily, variant, BASE, outcome_end=outcome_end, delay=1)
    metrics = _metrics(base)
    stress_metrics = _metrics(stress)
    months = _group_metrics(base, "month")
    years = _group_metrics(base, "year")
    symbols = _group_metrics(base, "underlying")
    positive_month_fraction = Decimal(sum(row["net_pnl"] > 0 for row in months.values())) / Decimal(
        len(months) or 1
    )
    positive_year_fraction = Decimal(sum(row["net_pnl"] > 0 for row in years.values())) / Decimal(
        len(years) or 1
    )
    positive_symbols = sum(row["net_pnl"] > 0 for row in symbols.values())
    prior = _verified_prior()
    neighbor_fraction = Decimal(str(prior["development_reference"]["positive_neighbor_fraction"]))
    admission = admission_criteria(
        target_stop_ratio=Decimal(str(metrics["minimum_after_cost_target_to_stop"])),
        profit_factor=Decimal(str(metrics["profit_factor"])),
        expectancy_r=Decimal(str(metrics["expectancy_r"])),
        sample_count=int(metrics["sample_count"]),
        max_drawdown_r=Decimal(str(metrics["max_drawdown_r"])),
        positive_underlyings=positive_symbols,
        positive_regimes=1 if metrics["net_pnl"] > 0 else 0,
        positive_month_fraction=positive_month_fraction,
        stressed_net_pnl=Decimal(str(stress_metrics["net_pnl"])),
        positive_neighbor_fraction=neighbor_fraction,
        largest_win_fraction=Decimal(str(metrics["largest_win_fraction_of_gross_profit"])),
    )
    prior_admitted = bool(prior["admission"]["admitted"])
    temporal = {
        "pre_2021_positive_year_fraction_at_least_60pct": positive_year_fraction >= Decimal(".60"),
        "prior_fresh_2021_2022_admission_passed": prior_admitted,
        "all_fresh_blocks_profitable": metrics["net_pnl"] > 0
        and Decimal(str(prior["fresh_2021_2022"]["metrics"]["net_pnl"])) > 0,
    }
    admission["criteria"].update(temporal)
    admission["admitted"] = admission["admitted"] and all(temporal.values())
    prior_trades = tuple(_trade_from_json(row) for row in prior["fresh_2021_2022"]["trades"])
    combined = tuple(sorted((*base, *prior_trades), key=lambda trade: trade.entry_at))
    combined_metrics = _metrics(combined)
    combined_years = _group_metrics(combined, "year")
    by_symbol_dates = {
        symbol: sorted(bar.session for bar in daily if bar.symbol == symbol) for symbol in SYMBOLS
    }
    availability = {
        symbol: {
            "bar_count": len(sessions),
            "earliest_session": sessions[0] if sessions else None,
            "latest_session": sessions[-1] if sessions else None,
        }
        for symbol, sessions in by_symbol_dates.items()
    }
    result = {
        "schema_version": "afterimage-attempt019-history-exhaustion-v1",
        "attempt_id": "remaining_history_exhaustion_v19",
        "audit_hash": audit["audit_hash"],
        "rule_hash": frozen_rule["rule_hash"],
        "selected_variant": frozen_rule["selected_variant"],
        "provenance": {
            "label": "fresh pre-2021 backward validation; no outcome in this block used in design",
            "evaluations": 1,
            "requested_start": audit["requested_history"]["start"],
            "requested_end_exclusive": audit["requested_history"]["end_exclusive"],
            "cache_hash": cache["content_hash"],
            "source": cache["source"],
            "feed": cache["feed"],
            "timeframe": cache["timeframe"],
        },
        "availability": {
            "by_symbol": availability,
            "earliest_common_session": common[0],
            "latest_common_session": common[-1],
            "first_eligible_evaluation_session": eligible[0],
            "last_eligible_evaluation_session": eligible[-1],
            "common_session_count": len(common),
        },
        "fresh_pre_2021": {
            "metrics": metrics,
            "trades": [asdict(trade) for trade in base],
            "signal_count_before_position_constraint": len(signals),
            "year_metrics": years,
            "positive_year_fraction": positive_year_fraction,
            "month_metrics": months,
            "positive_month_fraction": positive_month_fraction,
            "symbol_metrics": symbols,
            "positive_symbol_count": positive_symbols,
            "stressed_1_5x_costs": stress_metrics,
            "plus_two_bps_slippage_each_side": _metrics(plus_two),
            "one_session_entry_delay": _metrics(delay),
        },
        "prior_fresh_2021_2022_reference": {
            "metrics": prior["fresh_2021_2022"]["metrics"],
            "year_metrics": prior["fresh_2021_2022"]["year_metrics"],
            "admission": prior["admission"],
            "result_hash": prior["result_hash"],
        },
        "diagnostic_aggregate_pre_2021_plus_2021_2022": {
            "label": "two separately frozen fresh backward-validation blocks; diagnostic aggregate only",
            "metrics": combined_metrics,
            "year_metrics": combined_years,
        },
        "admission": admission,
        "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "fresh_data_exhaustion": {
            "all_returned_pre_2021_history_for_fixed_universe_consumed": True,
            "usable_unrevealed_chronological_partition_remaining": False,
            "basis": [
                "The request began 2000-01-01, before the fixed universe was complete, and used every common returned session through 2020 as warm-up or eligible outcome data.",
                "2021-2022 was revealed exactly once by Attempt 017; 2023, 2024, 2025, and 2026 were already revealed by Attempts 007, 006, 005/017 development, and 001-005 respectively.",
                "No unused chronological Alpaca IEX daily outcome block remains for this research universe through the latest cached 2026 outcomes.",
            ],
        },
        "production_integration_contract": {
            "status": "NONE_NOT_ADMITTED",
            "signal_module": None,
            "scheduler": None,
            "risk_allocation": None,
            "order_route": None,
            "reason": "No candidate passed every admission and temporal-stability criterion.",
            "dry_run_artifact_only": "results/alpaca_mleg_dry_run.json",
            "orders_submitted": False,
        },
        "limitations": [
            "This is backward validation, not a live forward test.",
            "Alpaca IEX daily OHLC is not SIP and does not reveal intraday path; same-bar stop-first handling is conservative.",
            "Raw adjustment was frozen in the rule; corporate-action discontinuities can affect very long histories.",
            "The absence of an unrevealed chronological partition prevents further honest candidate iteration on this data set.",
        ],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def report(result: Mapping[str, Any]) -> str:
    fresh = result["fresh_pre_2021"]
    metrics = fresh["metrics"]
    aggregate = result["diagnostic_aggregate_pre_2021_plus_2021_2022"]["metrics"]
    lines = [
        "# Attempt 019 — remaining-history exhaustion audit",
        "",
        f"**{result['decision']}**. Fresh pre-2021: n={metrics['sample_count']}, net=${metrics['net_pnl']}, "
        f"expectancy={Decimal(str(metrics['expectancy_r'])):.3f}R, PF={Decimal(str(metrics['profit_factor'])):.2f}, "
        f"max DD={Decimal(str(metrics['max_drawdown_r'])):.2f}R.",
        "",
        f"Audit hash: `{result['audit_hash']}`. Rule hash: `{result['rule_hash']}`. "
        "The rule and audit were frozen before the pre-2021 data request.",
        "",
        "## Alpaca availability boundary",
        "",
        f"Requested from 2000-01-01. Earliest common returned session: "
        f"**{result['availability']['earliest_common_session']}**; first eligible evaluation session after warm-up: "
        f"**{result['availability']['first_eligible_evaluation_session']}**.",
        "",
        "| Symbol | Bars | Earliest | Latest |",
        "|---|---:|---|---|",
    ]
    for symbol, row in result["availability"]["by_symbol"].items():
        lines.append(
            f"| {symbol} | {row['bar_count']} | {row['earliest_session']} | {row['latest_session']} |"
        )
    lines.extend(
        [
            "",
            "## Fresh year stability",
            "",
            "| Year | n | P&L | Exp/R | PF | DD/R |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for year, row in fresh["year_metrics"].items():
        lines.append(
            f"| {year} | {row['sample_count']} | ${row['net_pnl']} | "
            f"{Decimal(str(row['expectancy_r'])):.3f} | {Decimal(str(row['profit_factor'])):.2f} | "
            f"{Decimal(str(row['max_drawdown_r'])):.2f} |"
        )
    lines.extend(
        [
            "",
            "## Execution stress",
            "",
            "| Scenario | n | P&L | Exp/R | PF | DD/R |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for label, key in (
        ("base", "metrics"),
        ("1.5x costs", "stressed_1_5x_costs"),
        ("+2 bp/side", "plus_two_bps_slippage_each_side"),
        ("one-session delay", "one_session_entry_delay"),
    ):
        row = fresh[key]
        lines.append(
            f"| {label} | {row['sample_count']} | ${row['net_pnl']} | "
            f"{Decimal(str(row['expectancy_r'])):.3f} | {Decimal(str(row['profit_factor'])):.2f} | "
            f"{Decimal(str(row['max_drawdown_r'])):.2f} |"
        )
    lines.extend(
        [
            "",
            "## Admission audit",
            "",
            "| Criterion | Pass |",
            "|---|---|",
            *[f"| {name} | {passed} |" for name, passed in result["admission"]["criteria"].items()],
            "",
            "## Diagnostic aggregate",
            "",
            "Pre-2021 and the separately frozen 2021–2022 block together: "
            f"n={aggregate['sample_count']}, net=${aggregate['net_pnl']}, "
            f"expectancy={Decimal(str(aggregate['expectancy_r'])):.3f}R, "
            f"PF={Decimal(str(aggregate['profit_factor'])):.2f}, "
            f"max DD={Decimal(str(aggregate['max_drawdown_r'])):.2f}R. This pooling is diagnostic only.",
            "",
            "## Stopping condition",
            "",
            "No usable unrevealed chronological Alpaca IEX daily partition remains for this fixed research universe. "
            "Further iteration would tune against revealed outcomes, so discovery stops without a promoted candidate.",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in result["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def _update_ledger(result: Mapping[str, Any]) -> None:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    ledger.pop("ledger_hash", None)
    attempts = list(ledger["attempts"])
    attempt018 = json.loads((HERE / "results" / "attempt018_development.json").read_text(encoding="utf-8"))
    attempt018_body = {key: value for key, value in attempt018.items() if key != "result_hash"}
    if canonical_hash(attempt018_body) != attempt018["result_hash"]:
        raise ValueError("ATTEMPT018_RESULT_HASH_MISMATCH")
    attempts = [
        row
        for row in attempts
        if row.get("attempt_id") not in {attempt018["attempt_id"], result["attempt_id"]}
    ]
    selected = attempt018["final_selected_variant"]
    attempts.append(
        {
            "attempt_id": attempt018["attempt_id"],
            "status": "rejected_in_development",
            "spec": attempt018["family_spec"],
            "selected_variant": selected,
            "development_metrics": attempt018["variants"][selected]["development_metrics"],
            "rolling_development_validation": attempt018["rolling_development_validation"],
            "recommendation": "REJECT_DEVELOPMENT",
            "result_hash": attempt018["result_hash"],
        }
    )
    attempts.append(
        {
            "attempt_id": result["attempt_id"],
            "status": "evaluated_history_exhaustion",
            "spec": "ATTEMPT_019_SPEC.md",
            "audit_hash": result["audit_hash"],
            "rule_hash": result["rule_hash"],
            "selected_variant": result["selected_variant"],
            "fresh_metrics": result["fresh_pre_2021"]["metrics"],
            "admission": result["admission"],
            "fresh_data_exhaustion": result["fresh_data_exhaustion"],
            "recommendation": result["decision"],
            "result_hash": result["result_hash"],
        }
    )
    ledger["attempts"] = attempts
    ledger["ledger_hash"] = canonical_hash(ledger)
    _write_json(ATTEMPT_LEDGER, ledger)


def final_report(result: Mapping[str, Any]) -> str:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    lines = [
        "# AFTERIMAGE strategy discovery — final evidence report",
        "",
        "**NO CANDIDATE PROMOTED.** Nineteen recorded attempts were preserved. The last exact frozen rule "
        "failed fresh validation, and the full remaining Alpaca history was then consumed in one sealed audit.",
        "",
        "Attempts 001–007 remain sealed by snapshot hash "
        "`d9aa8d0820fe58c9cacf814da1c64cde5333cb3248f69c46778c5aad02218bb7`.",
        "",
        "| Attempt ID | Status | Selected | n | Net P&L | Exp/R | PF | DD/R |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in ledger["attempts"]:
        metrics = row.get("fresh_metrics") or row.get("development_metrics") or row.get("pseudo_oos_metrics") or {}
        lines.append(
            f"| {row.get('attempt_id')} | {row.get('status')} | `{row.get('selected_variant', '')}` | "
            f"{metrics.get('sample_count', '')} | {metrics.get('net_pnl', '')} | "
            f"{metrics.get('expectancy_r', '')} | {metrics.get('profit_factor', '')} | "
            f"{metrics.get('max_drawdown_r', '')} |"
        )
    lines.extend(
        [
            "",
            "## Final validation verdict",
            "",
            report(result),
            "",
            "## Production integration contract",
            "",
            "There is none: admission failed, so no signal module, scheduler, risk allocation, or order route is "
            "authorized for production. The existing exact MLEG dry-run artifact remains a non-submitted audit "
            "artifact only (`submitted: false`); no order was placed during this research.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--cli", type=Path, default=CLI)
    args = parser.parse_args()
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    frozen_rule = json.loads(FROZEN_RULE.read_text(encoding="utf-8"))
    validate_audit(audit)
    cache = acquire(args.cli, args.profile, audit) if args.fetch else json.loads(CACHE.read_text(encoding="utf-8"))
    result = evaluate(cache, audit, frozen_rule)
    _write_json(OUTPUT, result)
    REPORT.write_text(report(result), encoding="utf-8")
    _update_ledger(result)
    FINAL_REPORT.write_text(final_report(result), encoding="utf-8")
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "availability": result["availability"],
                "fresh": result["fresh_pre_2021"]["metrics"],
                "aggregate": result["diagnostic_aggregate_pre_2021_plus_2021_2022"]["metrics"],
                "admission": result["admission"]["criteria"],
                "exhaustion": result["fresh_data_exhaustion"],
            },
            default=str,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
