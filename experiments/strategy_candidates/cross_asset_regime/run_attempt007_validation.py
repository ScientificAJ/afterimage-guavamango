#!/usr/bin/env python3
"""Evaluate the exact frozen attempt-007 QQQ rule once on 2023 outcomes."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import DataExclusion, StockBar, UNIVERSE, enforce_non_overlapping, summarize
    from .equity_candidate import EquityCosts, EquityTrade, simulate_equity_trade
    from .qqq_regime_candidate import QQQRegimeSignal, QQQRegimeVariant, qqq_regime_signal
    from .run_gap_research import _max_drawdown_r, _profit_concentration, admission_criteria
    from .run_research import ATTEMPT_LEDGER, ET, PROFILE, REPO, _paged_rows, _stock_objects, _write_json, canonical_hash
    from .validate_frozen_extension import _rehydrate_trade
except ImportError:
    from candidate import DataExclusion, StockBar, UNIVERSE, enforce_non_overlapping, summarize  # type: ignore[no-redef]
    from equity_candidate import EquityCosts, EquityTrade, simulate_equity_trade  # type: ignore[no-redef]
    from qqq_regime_candidate import QQQRegimeSignal, QQQRegimeVariant, qqq_regime_signal  # type: ignore[no-redef]
    from run_gap_research import _max_drawdown_r, _profit_concentration, admission_criteria  # type: ignore[no-redef]
    from run_research import ATTEMPT_LEDGER, ET, PROFILE, REPO, _paged_rows, _stock_objects, _write_json, canonical_hash  # type: ignore[no-redef]
    from validate_frozen_extension import _rehydrate_trade  # type: ignore[no-redef]


HERE = Path(__file__).resolve().parent
FROZEN_RULE = HERE / "results" / "attempt007_frozen_rule.json"
CACHE = HERE / "data" / "attempt007_market_cache.json"
OUTPUT = HERE / "results" / "attempt007_backtest.json"
REPORT = HERE / "ATTEMPT_007_REPORT.md"
ATTEMPT006_RESULT = HERE / "results" / "attempt006_backtest.json"
CLI = REPO / ".tools" / "bin" / "alpaca"
ACQUISITION_START = datetime(2022, 11, 15, tzinfo=UTC)
ACQUISITION_END = datetime(2024, 1, 1, tzinfo=UTC)
VALIDATION_START = date(2023, 1, 3)
VALIDATION_END = date(2023, 12, 29)
STOCK_SYMBOLS = ("SPY", *UNIVERSE)
BASE_COSTS = EquityCosts(Decimal("0.0001"), Decimal("0.005"))
STRESSED_COSTS = EquityCosts(Decimal("0.00015"), Decimal("0.0075"))
PLUS_TWO_BPS_COSTS = EquityCosts(Decimal("0.0003"), Decimal("0.005"))


def _rule_body(artifact: Mapping[str, Any]) -> dict[str, Any]:
    ignored = {"rule_hash", "rule_hash_scope", "source_hashes"}
    return {key: value for key, value in artifact.items() if key not in ignored}


def validate_rule(artifact: Mapping[str, Any], *, verify_sources: bool = True) -> None:
    if canonical_hash(_rule_body(artifact)) != str(artifact.get("rule_hash", "")):
        raise ValueError("FROZEN_RULE_HASH_MISMATCH")
    if verify_sources:
        for name, expected in artifact.get("source_hashes", {}).items():
            observed = hashlib.sha256((HERE / str(name)).read_bytes()).hexdigest()
            if observed != str(expected):
                raise ValueError("FROZEN_SOURCE_HASH_MISMATCH")


def _validate_cache(cache: Mapping[str, Any]) -> None:
    body = {key: value for key, value in cache.items() if key != "content_hash"}
    if canonical_hash(body) != str(cache.get("content_hash", "")):
        raise ValueError("MARKET_CACHE_HASH_MISMATCH")


def acquire(*, executable: Path, profile: str, output: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    commands: list[list[str]] = []
    for symbol in STOCK_SYMBOLS:
        received, used = _paged_rows(
            executable,
            profile,
            (
                "data", "bars", "--symbol", symbol,
                "--start", ACQUISITION_START.isoformat(), "--end", ACQUISITION_END.isoformat(),
                "--timeframe", "15Min", "--feed", "iex", "--adjustment", "raw",
                "--sort", "asc", "--limit", "10000",
            ),
            result_key="bars",
        )
        rows.extend(received)
        commands.extend(used)
    body = {
        "schema_version": "afterimage-attempt007-market-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only data/bars endpoint",
        "feed": "iex",
        "timeframe": "15Min",
        "adjustment": "raw",
        "acquisition_window": {"start": ACQUISITION_START, "end_exclusive": ACQUISITION_END},
        "validation_window": {"start": VALIDATION_START, "end": VALIDATION_END},
        "bars": sorted(rows, key=lambda item: (str(item.get("t")), str(item.get("symbol")))),
        "source_commands": commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    _write_json(output, result)
    return result


def _variant(artifact: Mapping[str, Any]) -> QQQRegimeVariant:
    rule = artifact["rule"]
    return QQQRegimeVariant(
        name=str(artifact["selected_variant"]),
        breadth_required=int(rule["breadth_required"]),
        minimum_mean_gap=Decimal(str(rule["minimum_mean_gap"])),
        sector_confirmations=int(rule["sector_confirmations"]),
        stop_fraction=Decimal(str(rule["stop_fraction"])),
        hold_bars=int(rule["hold_bars"]),
    )


def _spy_closes(stock: Sequence[StockBar]) -> tuple[tuple[date, Decimal], ...]:
    grouped: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        if bar.symbol == "SPY":
            grouped[bar.timestamp.astimezone(ET).date()].append(bar)
    return tuple(
        (session, max(rows, key=lambda item: item.timestamp).close)
        for session, rows in sorted(grouped.items())
    )


def _signals(stock: Sequence[StockBar], variant: QQQRegimeVariant) -> tuple[QQQRegimeSignal, ...]:
    by_date: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        if bar.symbol in UNIVERSE:
            by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    daily = _spy_closes(stock)
    dates = sorted(by_date)
    result: list[QQQRegimeSignal] = []
    for index, session in enumerate(dates):
        if index == 0 or not VALIDATION_START <= session <= VALIDATION_END:
            continue
        try:
            signal = qqq_regime_signal(variant, (*by_date[dates[index - 1]], *by_date[session]), daily, session)
        except DataExclusion:
            continue
        if signal is not None:
            result.append(signal)
    return tuple(result)


def _evaluate(
    signals: Sequence[QQQRegimeSignal],
    stock: Sequence[StockBar],
    variant: QQQRegimeVariant,
    costs: EquityCosts,
    *,
    delay_bars: int = 0,
) -> tuple[EquityTrade, ...]:
    by_date: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    result: list[EquityTrade] = []
    for signal in signals:
        delayed = replace(signal, completed_at=signal.completed_at + timedelta(minutes=15 * delay_bars))
        try:
            result.append(simulate_equity_trade(delayed, by_date[signal.session], variant, costs))  # type: ignore[arg-type]
        except DataExclusion:
            continue
    return enforce_non_overlapping(result)  # type: ignore[arg-type,return-value]


def _metrics(rows: Sequence[EquityTrade]) -> dict[str, Any]:
    return {
        **asdict(summarize(rows)),
        "max_drawdown_r": _max_drawdown_r(rows),  # type: ignore[arg-type]
        "largest_win_fraction_of_gross_profit": _profit_concentration(rows),  # type: ignore[arg-type]
        "minimum_after_cost_target_to_stop": min((row.target_to_stop for row in rows), default=Decimal(0)),
    }


def _group_metrics(rows: Sequence[EquityTrade], labels: Mapping[date, str] | None = None) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[EquityTrade]] = defaultdict(list)
    for row in rows:
        key = labels[row.session] if labels is not None else row.session.strftime("%Y-%m")
        grouped[key].append(row)
    return {key: _metrics(values) for key, values in sorted(grouped.items())}


def evaluate(cache: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    validate_rule(artifact)
    _validate_cache(cache)
    variant = _variant(artifact)
    stock = _stock_objects(cache["bars"])
    signals = _signals(stock, variant)
    base = _evaluate(signals, stock, variant, BASE_COSTS)
    stressed = _evaluate(signals, stock, variant, STRESSED_COSTS)
    plus_two_bps = _evaluate(signals, stock, variant, PLUS_TWO_BPS_COSTS)
    delayed = _evaluate(signals, stock, variant, BASE_COSTS, delay_bars=1)
    fresh_metrics = _metrics(base)
    stress_metrics = _metrics(stressed)
    months = _group_metrics(base)
    regimes = _group_metrics(base, {signal.session: signal.regime for signal in signals})
    positive_month_fraction = Decimal(sum(row["net_pnl"] > 0 for row in months.values())) / Decimal(len(months) or 1)
    positive_regimes = sum(row["net_pnl"] > 0 for row in regimes.values())

    prior = json.loads(ATTEMPT006_RESULT.read_text(encoding="utf-8"))
    prior_body = {key: value for key, value in prior.items() if key != "result_hash"}
    if canonical_hash(prior_body) != str(prior.get("result_hash", "")):
        raise ValueError("ATTEMPT006_RESULT_HASH_MISMATCH")
    prior_variant = prior["variants"][variant.name]
    prior_trades = tuple(_rehydrate_trade(row) for row in prior_variant["fresh_2024_trades"])
    prior_metrics = _metrics(prior_trades)
    combined = tuple(sorted((*base, *prior_trades), key=lambda row: (row.session, row.entry_at)))

    # No new neighbors are evaluated on 2023. This is the predeclared attempt-006 family result.
    neighbor_fraction = Decimal(str(prior["neighbor_positive_fraction"]))
    admission = admission_criteria(
        target_stop_ratio=Decimal(str(fresh_metrics["minimum_after_cost_target_to_stop"])),
        profit_factor=Decimal(str(fresh_metrics["profit_factor"])),
        expectancy_r=Decimal(str(fresh_metrics["expectancy_r"])),
        sample_count=int(fresh_metrics["sample_count"]),
        max_drawdown_r=Decimal(str(fresh_metrics["max_drawdown_r"])),
        positive_underlyings=1 if fresh_metrics["net_pnl"] > 0 else 0,
        positive_regimes=positive_regimes,
        positive_month_fraction=positive_month_fraction,
        stressed_net_pnl=Decimal(str(stress_metrics["net_pnl"])),
        positive_neighbor_fraction=neighbor_fraction,
        largest_win_fraction=Decimal(str(fresh_metrics["largest_win_fraction_of_gross_profit"])),
    )
    temporal = {
        "base_net_positive_in_both_2023_and_2024": fresh_metrics["net_pnl"] > 0 and prior_metrics["net_pnl"] > 0,
        "one_and_half_cost_net_positive_in_both_2023_and_2024": stress_metrics["net_pnl"] > 0 and Decimal(str(prior_variant["stressed_1_5x_costs"]["net_pnl"])) > 0,
    }
    admission["criteria"].update(temporal)
    admission["admitted"] = admission["admitted"] and all(temporal.values())
    result = {
        "schema_version": "afterimage-attempt007-fresh-outcome-validation-v1",
        "attempt_id": "qqq_regime_active_rule_v7",
        "family": "exact frozen QQQ regime-conditioned sector-confirmed overnight-gap continuation",
        "rule_hash": artifact["rule_hash"],
        "selected_variant": variant.name,
        "provenance": {
            "label": "fresh 2023 outcome validation; no 2023 trade outcome or metric used in design; not untouched-data validation",
            "caveat": artifact["fresh_outcome_validation"]["provenance_caveat"],
            "window": {"start": VALIDATION_START, "end": VALIDATION_END},
            "evaluations": 1,
            "source": cache["source"],
            "cache_hash": cache["content_hash"],
            "feed": cache["feed"],
            "timeframe": cache["timeframe"],
            "selection_on_2023": False,
        },
        "fresh_2023": {
            "metrics": fresh_metrics,
            "trades": [asdict(row) for row in base],
            "month_metrics": months,
            "positive_month_fraction": positive_month_fraction,
            "regime_metrics": regimes,
            "positive_regime_count": positive_regimes,
            "stressed_1_5x_costs": stress_metrics,
            "plus_two_bps_slippage_each_side": _metrics(plus_two_bps),
            "one_extra_15_minute_entry_bar": _metrics(delayed),
        },
        "prior_2024_hypothesis_evidence": {
            "label": "predeclared attempt-006 neighbor sensitivity; revealed before attempt-007 freeze",
            "metrics": prior_metrics,
            "stressed_1_5x_costs": prior_variant["stressed_1_5x_costs"],
            "attempt006_result_hash": prior["result_hash"],
        },
        "combined_diagnostic": {
            "metrics": _metrics(combined),
            "components": [
                {"label": "fresh 2023 outcome validation", "sample_count": len(base)},
                {"label": "revealed 2024 neighbor sensitivity", "sample_count": len(prior_trades)},
            ],
            "warning": "Diagnostic only; combines hypothesis-generating 2024 evidence with the fresh 2023 outcome validation.",
        },
        "neighbor_positive_fraction": neighbor_fraction,
        "neighbor_provenance": "Inherited from the predeclared attempt-006 2024 family; no neighbors evaluated on 2023.",
        "admission": admission,
        "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "limitations": [
            "Late-2023 bars existed previously as warm-up inputs, though no 2023 trade outcome or metric was evaluated before the rule freeze.",
            "This is backward outcome validation, not chronological forward OOS.",
            "IEX 15-minute OHLC is not SIP and lacks intrabar ordering; stop-first is conservative.",
            "Historical QQQ short availability, borrow fees, market impact, and queue position are not modeled.",
        ],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _fmt(value: Any, digits: int = 2) -> str:
    return f"{Decimal(str(value)):.{digits}f}"


def report(result: Mapping[str, Any]) -> str:
    fresh = result["fresh_2023"]["metrics"]
    prior = result["prior_2024_hypothesis_evidence"]["metrics"]
    combined = result["combined_diagnostic"]["metrics"]
    lines = [
        "# Attempt 007 — exact active QQQ regime rule",
        "",
        f"**{result['decision']}**. Frozen `{result['selected_variant']}` on the once-evaluated 2023 outcomes: n={fresh['sample_count']}, net=${fresh['net_pnl']}, expectancy={_fmt(fresh['expectancy_r'], 3)}R, PF={_fmt(fresh['profit_factor'])}, hit={Decimal(str(fresh['hit_rate'])):.1%}, max DD={_fmt(fresh['max_drawdown_r'])}R.",
        "",
        f"Rule hash: `{result['rule_hash']}`. {result['provenance']['label']}.",
        "",
        "## Evidence kept separate",
        "",
        "| Evidence | n | Net P&L | Exp/R | PF | Max DD/R |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Fresh 2023 outcome validation | {fresh['sample_count']} | ${fresh['net_pnl']} | {_fmt(fresh['expectancy_r'], 3)} | {_fmt(fresh['profit_factor'])} | {_fmt(fresh['max_drawdown_r'])} |",
        f"| Revealed 2024 neighbor sensitivity | {prior['sample_count']} | ${prior['net_pnl']} | {_fmt(prior['expectancy_r'], 3)} | {_fmt(prior['profit_factor'])} | {_fmt(prior['max_drawdown_r'])} |",
        f"| 2023+2024 diagnostic pool | {combined['sample_count']} | ${combined['net_pnl']} | {_fmt(combined['expectancy_r'], 3)} | {_fmt(combined['profit_factor'])} | {_fmt(combined['max_drawdown_r'])} |",
        "",
        "The pool is diagnostic only and is not relabeled as untouched or rolling OOS.",
        "",
        "## Admission audit on fresh 2023",
        "",
        "| Criterion | Pass |",
        "|---|---|",
        *[f"| {key} | {value} |" for key, value in result["admission"]["criteria"].items()],
        "",
        "## Execution stress",
        "",
        "| Scenario | n | Net P&L | Exp/R | PF | Max DD/R |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("1.5x modeled costs", "stressed_1_5x_costs"),
        ("+2 bp slippage per side", "plus_two_bps_slippage_each_side"),
        ("one extra 15-minute entry bar", "one_extra_15_minute_entry_bar"),
    ):
        row = result["fresh_2023"][key]
        lines.append(f"| {label} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} | {_fmt(row['max_drawdown_r'])} |")
    lines.extend(["", "## Month stability", "", "| Month | n | Net P&L | Exp/R | PF |", "|---|---:|---:|---:|---:|"])
    for key, row in result["fresh_2023"]["month_metrics"].items():
        lines.append(f"| {key} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend(["", "## Regime stability", "", "| Regime | n | Net P&L | Exp/R | PF |", "|---|---:|---:|---:|---:|"])
    for key, row in result["fresh_2023"]["regime_metrics"].items():
        lines.append(f"| {key} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend(["", "## Limitations", "", *[f"- {item}" for item in result["limitations"]], ""])
    return "\n".join(lines)


def _update_ledger(result: Mapping[str, Any]) -> None:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    ledger.pop("ledger_hash", None)
    attempts = [item for item in ledger["attempts"] if item.get("attempt_id") != result["attempt_id"]]
    attempts.append({
        "attempt_id": result["attempt_id"],
        "status": "evaluated",
        "spec": "ATTEMPT_007_SPEC.md",
        "instrument": "QQQ shares only",
        "rule_hash": result["rule_hash"],
        "selected_variant": result["selected_variant"],
        "fresh_outcome_validation": result["provenance"],
        "fresh_2023_metrics": result["fresh_2023"]["metrics"],
        "prior_2024_hypothesis_metrics": result["prior_2024_hypothesis_evidence"]["metrics"],
        "combined_diagnostic_metrics": result["combined_diagnostic"]["metrics"],
        "admission": result["admission"],
        "recommendation": result["decision"],
        "result_hash": result["result_hash"],
    })
    ledger["attempts"] = attempts
    ledger["ledger_hash"] = canonical_hash(ledger)
    _write_json(ATTEMPT_LEDGER, ledger)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--cli", type=Path, default=CLI)
    args = parser.parse_args()
    artifact = json.loads(FROZEN_RULE.read_text(encoding="utf-8"))
    validate_rule(artifact)
    cache = acquire(executable=args.cli, profile=args.profile, output=CACHE) if args.fetch else json.loads(CACHE.read_text(encoding="utf-8"))
    result = evaluate(cache, artifact)
    _write_json(OUTPUT, result)
    REPORT.write_text(report(result), encoding="utf-8")
    _update_ledger(result)
    print(json.dumps({"decision": result["decision"], "rule_hash": result["rule_hash"], "fresh_2023": result["fresh_2023"]["metrics"], "combined_diagnostic": result["combined_diagnostic"]["metrics"], "admission": result["admission"]["criteria"]}, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
