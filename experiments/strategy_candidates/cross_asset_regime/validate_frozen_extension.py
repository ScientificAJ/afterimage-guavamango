#!/usr/bin/env python3
"""Validate the frozen attempt-005 rule on previously unused 2025 Alpaca bars."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from .candidate import DataExclusion, StockBar, UNIVERSE, enforce_non_overlapping, summarize
    from .equity_candidate import EquityCosts, EquitySignal, EquityTrade, simulate_equity_trade
    from .gap_candidate import GapVariant, gap_signal
    from .run_gap_research import _max_drawdown_r, _profit_concentration, admission_criteria
    from .run_research import (
        ATTEMPT_LEDGER,
        ET,
        PROFILE,
        REPO,
        _paged_rows,
        _stock_objects,
        _write_json,
        canonical_hash,
    )
except ImportError:
    from candidate import DataExclusion, StockBar, UNIVERSE, enforce_non_overlapping, summarize  # type: ignore[no-redef]
    from equity_candidate import EquityCosts, EquitySignal, EquityTrade, simulate_equity_trade  # type: ignore[no-redef]
    from gap_candidate import GapVariant, gap_signal  # type: ignore[no-redef]
    from run_gap_research import _max_drawdown_r, _profit_concentration, admission_criteria  # type: ignore[no-redef]
    from run_research import (  # type: ignore[no-redef]
        ATTEMPT_LEDGER, ET, PROFILE, REPO, _paged_rows, _stock_objects, _write_json,
        canonical_hash,
    )


HERE = Path(__file__).resolve().parent
FROZEN_RULE = HERE / "results" / "equity_gap_frozen_rule.json"
CACHE = HERE / "data" / "frozen_extension_2025.json"
OUTPUT = HERE / "results" / "frozen_extension_2025.json"
REPORT = HERE / "FRESH_EXTENSION_REPORT.md"
CURRENT_RESULT = HERE / "results" / "equity_gap_backtest.json"
CLI = REPO / ".tools" / "bin" / "alpaca"

# The extra history is signal/regime warm-up only. Reported trades remain inside 2025.
ACQUISITION_START = datetime(2024, 11, 15, tzinfo=UTC)
ACQUISITION_END = datetime(2026, 1, 1, tzinfo=UTC)
EXTENSION_START = date(2025, 1, 2)
EXTENSION_END = date(2025, 12, 31)
STOCK_SYMBOLS = ("SPY", *UNIVERSE)
BASE_COSTS = EquityCosts(Decimal("0.0001"), Decimal("0.005"))
STRESSED_COSTS = EquityCosts(Decimal("0.00015"), Decimal("0.0075"))
# Separate diagnostic requested after the freeze: add two bps per side to base slippage.
DELAY_PROXY_COSTS = EquityCosts(Decimal("0.0003"), Decimal("0.005"))


@dataclass(frozen=True)
class FrozenVariant:
    name: str
    breadth_required: int
    minimum_mean_gap: Decimal
    stop_fraction: Decimal
    hold_bars: int


def _frozen_hash_body(artifact: Mapping[str, Any]) -> dict[str, Any]:
    ignored = {"rule_hash", "rule_hash_scope", "source_hashes"}
    return {key: value for key, value in artifact.items() if key not in ignored}


def validate_frozen_rule(artifact: Mapping[str, Any]) -> None:
    expected = str(artifact.get("rule_hash", ""))
    observed = canonical_hash(_frozen_hash_body(artifact))
    if not expected or observed != expected:
        raise ValueError("FROZEN_RULE_HASH_MISMATCH")


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
                "--start", ACQUISITION_START.isoformat(),
                "--end", ACQUISITION_END.isoformat(),
                "--timeframe", "15Min", "--feed", "iex", "--adjustment", "raw",
                "--sort", "asc", "--limit", "10000",
            ),
            result_key="bars",
        )
        rows.extend(received)
        commands.extend(used)
    body = {
        "schema_version": "afterimage-frozen-extension-market-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only data/bars endpoint",
        "feed": "iex",
        "timeframe": "15Min",
        "adjustment": "raw",
        "acquisition_window": {
            "start": ACQUISITION_START,
            "end_exclusive": ACQUISITION_END,
            "warmup_only_before": EXTENSION_START,
        },
        "reported_trade_window": {"start": EXTENSION_START, "end": EXTENSION_END},
        "bars": sorted(rows, key=lambda item: (str(item.get("t")), str(item.get("symbol")))),
        "source_commands": commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    _write_json(output, result)
    return result


def _variant(artifact: Mapping[str, Any]) -> FrozenVariant:
    rule = artifact["rule"]
    return FrozenVariant(
        name=str(artifact["selected_variant"]),
        breadth_required=int(rule["breadth_required"]),
        minimum_mean_gap=Decimal(str(rule["minimum_mean_gap"])),
        stop_fraction=Decimal(str(rule["stop_fraction"])),
        hold_bars=int(rule["hold_bars"]),
    )


def _signals(stock: Sequence[StockBar], variant: FrozenVariant) -> tuple[EquitySignal, ...]:
    by_date: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        if bar.symbol in UNIVERSE:
            by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    dates = sorted(by_date)
    rows: list[EquitySignal] = []
    signal_variant = GapVariant(
        variant.name,
        variant.breadth_required,
        variant.minimum_mean_gap,
        Decimal("0.20"),
        variant.hold_bars,
    )
    for index, session in enumerate(dates):
        if index == 0 or not EXTENSION_START <= session <= EXTENSION_END:
            continue
        try:
            signal = gap_signal(signal_variant, (*by_date[dates[index - 1]], *by_date[session]), session)
        except DataExclusion:
            continue
        if signal is not None:
            rows.append(
                EquitySignal(
                    signal.session,
                    signal.completed_at,
                    signal.direction,
                    signal.underlying,
                    signal.reference_price,
                    variant.name,
                )
            )
    return tuple(rows)


def _evaluate(
    signals: Sequence[EquitySignal],
    stock: Sequence[StockBar],
    variant: FrozenVariant,
    costs: EquityCosts,
    *,
    delay_bars: int = 0,
) -> tuple[EquityTrade, ...]:
    by_date: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        by_date[bar.timestamp.astimezone(ET).date()].append(bar)
    trades: list[EquityTrade] = []
    for signal in signals:
        delayed = replace(signal, completed_at=signal.completed_at + timedelta(minutes=15 * delay_bars))
        try:
            trades.append(simulate_equity_trade(delayed, by_date[signal.session], variant, costs))  # type: ignore[arg-type]
        except DataExclusion:
            continue
    return enforce_non_overlapping(trades)  # type: ignore[arg-type,return-value]


def _rehydrate_trade(item: Mapping[str, Any]) -> EquityTrade:
    return EquityTrade(
        session=date.fromisoformat(str(item["session"])),
        variant=str(item["variant"]),
        direction=str(item["direction"]),
        underlying=str(item["underlying"]),
        entry_at=datetime.fromisoformat(str(item["entry_at"])),
        exit_at=datetime.fromisoformat(str(item["exit_at"])),
        shares=int(item["shares"]),
        raw_entry=Decimal(str(item["raw_entry"])),
        entry_fill=Decimal(str(item["entry_fill"])),
        stop_price=Decimal(str(item["stop_price"])),
        target_price=Decimal(str(item["target_price"])),
        exit_fill=Decimal(str(item["exit_fill"])),
        net_pnl=Decimal(str(item["net_pnl"])),
        return_r=Decimal(str(item["return_r"])),
        outcome=str(item["outcome"]),  # type: ignore[arg-type]
        modeled_fees=Decimal(str(item["modeled_fees"])),
        modeled_slippage=Decimal(str(item["modeled_slippage"])),
        target_to_stop=Decimal(str(item["target_to_stop"])),
    )


def _metrics(rows: Sequence[EquityTrade]) -> dict[str, Any]:
    return {
        **asdict(summarize(rows)),
        "max_drawdown_r": _max_drawdown_r(rows),  # type: ignore[arg-type]
        "largest_win_fraction_of_gross_profit": _profit_concentration(rows),  # type: ignore[arg-type]
        "minimum_after_cost_target_to_stop": min((row.target_to_stop for row in rows), default=Decimal(0)),
    }


def _group_metrics(rows: Sequence[EquityTrade], field: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[EquityTrade]] = defaultdict(list)
    for row in rows:
        key = row.session.strftime("%Y-%m") if field == "month" else str(getattr(row, field))
        grouped[key].append(row)
    return {key: _metrics(values) for key, values in sorted(grouped.items())}


def _spy_closes(stock: Sequence[StockBar]) -> tuple[tuple[date, Decimal], ...]:
    grouped: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        if bar.symbol == "SPY":
            grouped[bar.timestamp.astimezone(ET).date()].append(bar)
    return tuple(
        (session, max(items, key=lambda item: item.timestamp).close)
        for session, items in sorted(grouped.items())
    )


def _regime_for(row: EquityTrade, spy: Sequence[tuple[date, Decimal]]) -> str:
    eligible = [value for session, value in spy if session < row.session]
    if len(eligible) < 20:
        return "insufficient_warmup"
    average = sum(eligible[-20:], Decimal(0)) / Decimal(20)
    market = "risk_on" if eligible[-1] >= average else "risk_off"
    alignment = "bullish" if row.direction == "bullish" else "bearish"
    return f"{market}_{alignment}"


def _regime_metrics(rows: Sequence[EquityTrade], stock: Sequence[StockBar]) -> dict[str, dict[str, Any]]:
    spy = _spy_closes(stock)
    grouped: dict[str, list[EquityTrade]] = defaultdict(list)
    for row in rows:
        grouped[_regime_for(row, spy)].append(row)
    return {key: _metrics(values) for key, values in sorted(grouped.items())}


def evaluate(cache: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    validate_frozen_rule(artifact)
    _validate_cache(cache)
    variant = _variant(artifact)
    stock = _stock_objects(cache["bars"])
    signals = _signals(stock, variant)
    base = _evaluate(signals, stock, variant, BASE_COSTS)
    cost_stress = _evaluate(signals, stock, variant, STRESSED_COSTS)
    delay_proxy = _evaluate(signals, stock, variant, DELAY_PROXY_COSTS)
    one_bar_delay = _evaluate(signals, stock, variant, BASE_COSTS, delay_bars=1)

    current = json.loads(CURRENT_RESULT.read_text(encoding="utf-8"))
    current_body = {key: value for key, value in current.items() if key != "result_hash"}
    if canonical_hash(current_body) != str(current.get("result_hash", "")):
        raise ValueError("CURRENT_RESULT_HASH_MISMATCH")
    rolling = tuple(_rehydrate_trade(item) for item in current["rolling_oos"]["trades"])
    pooled = tuple(sorted((*base, *rolling), key=lambda row: (row.session, row.entry_at)))

    months = _group_metrics(base, "month")
    symbols = _group_metrics(base, "underlying")
    regimes = _regime_metrics(base, stock)
    base_metrics = _metrics(base)
    cost_stress_metrics = _metrics(cost_stress)
    positive_month_fraction = Decimal(sum(value["net_pnl"] > 0 for value in months.values())) / Decimal(len(months) or 1)
    positive_symbol_count = sum(value["net_pnl"] > 0 for value in symbols.values())
    positive_regime_count = sum(value["net_pnl"] > 0 for value in regimes.values())
    prior_neighbor_fraction = Decimal(str(current["rolling_oos"]["positive_neighbor_fraction"]))
    admission = admission_criteria(
        target_stop_ratio=Decimal(str(base_metrics["minimum_after_cost_target_to_stop"])),
        profit_factor=Decimal(str(base_metrics["profit_factor"])),
        expectancy_r=Decimal(str(base_metrics["expectancy_r"])),
        sample_count=int(base_metrics["sample_count"]),
        max_drawdown_r=Decimal(str(base_metrics["max_drawdown_r"])),
        positive_underlyings=positive_symbol_count,
        positive_regimes=positive_regime_count,
        positive_month_fraction=positive_month_fraction,
        stressed_net_pnl=Decimal(str(cost_stress_metrics["net_pnl"])),
        positive_neighbor_fraction=prior_neighbor_fraction,
        largest_win_fraction=Decimal(str(base_metrics["largest_win_fraction_of_gross_profit"])),
    )
    result = {
        "schema_version": "afterimage-frozen-backward-validation-v1",
        "attempt_id": "equity_overnight_gap_v5",
        "frozen_rule_hash": artifact["rule_hash"],
        "selected_variant": artifact["selected_variant"],
        "provenance": {
            "label": "fresh backward validation; previously unused during design; not chronological forward OOS",
            "rule_frozen_at": artifact["frozen_at"],
            "rule_evidence_seen_through": artifact["evidence_seen_through"],
            "trade_window": {"start": EXTENSION_START, "end": EXTENSION_END},
            "cache_hash": cache["content_hash"],
            "source": cache["source"],
            "feed": cache["feed"],
            "timeframe": cache["timeframe"],
            "evaluations": 1,
        },
        "fresh_extension": {
            "metrics": base_metrics,
            "trades": [asdict(row) for row in base],
            "symbol_metrics": symbols,
            "month_metrics": months,
            "regime_definition": "Prior completed SPY close versus prior 20-session SMA, crossed with trade direction; reporting only.",
            "regime_metrics": regimes,
            "positive_month_fraction": positive_month_fraction,
            "positive_symbol_count": positive_symbol_count,
            "positive_regime_count": positive_regime_count,
        },
        "stress": {
            "one_and_half_times_modeled_costs": cost_stress_metrics,
            "plus_two_bps_slippage_each_side": _metrics(delay_proxy),
            "one_extra_15_minute_entry_bar": _metrics(one_bar_delay),
            "note": "Diagnostics were declared after freezing and cannot alter the frozen rule.",
        },
        "prior_2026_rolling_evidence": {
            "scope": current["rolling_oos"]["scope"],
            "metrics": current["rolling_oos"]["metrics"],
            "max_drawdown_r": current["rolling_oos"]["max_drawdown_r"],
            "result_hash": current["result_hash"],
        },
        "pooled_with_clear_provenance": {
            "metrics": _metrics(pooled),
            "components": [
                {"label": "2025 fresh backward validation", "sample_count": len(base)},
                {"label": "2026 rolling/pseudo-OOS evidence", "sample_count": len(rolling)},
            ],
            "warning": "Pooled metrics combine a backward validation with rolling/pseudo-OOS evidence and are not an untouched holdout estimate.",
        },
        "fresh_extension_admission": {
            **admission,
            "neighbor_provenance": "Neighbor-positive fraction is inherited from the pre-freeze 2026 rolling diagnostic; no 2025 neighbor was evaluated after freeze.",
        },
        "decision": "ADMIT" if admission["admitted"] else "REJECT_AFTER_FRESH_EXTENSION",
        "limitations": [
            "Backward validation is fresh to strategy design but is not chronological forward OOS.",
            "IEX 15-minute OHLC is not SIP and does not reveal intrabar path; stop-first ordering is conservative.",
            "Short availability, borrow fees, market impact, and queue position are not modeled.",
            "The plus-two-bps and one-bar-delay diagnostics were not used to select or alter the rule.",
        ],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _fmt(value: Any, digits: int = 2) -> str:
    return f"{Decimal(str(value)):.{digits}f}"


def report(result: Mapping[str, Any]) -> str:
    fresh = result["fresh_extension"]["metrics"]
    pooled = result["pooled_with_clear_provenance"]["metrics"]
    prior = result["prior_2026_rolling_evidence"]["metrics"]
    stress = result["stress"]
    lines = [
        "# Frozen attempt-005 backward validation",
        "",
        f"Rule hash: `{result['frozen_rule_hash']}`. This exact rule was frozen before the 2025 cache was acquired or evaluated.",
        "",
        "## Evidence kept separate",
        "",
        "| Evidence | n | Net P&L | Expectancy/R | PF | Max DD/R |",
        "|---|---:|---:|---:|---:|---:|",
        f"| 2025 fresh backward validation | {fresh['sample_count']} | ${fresh['net_pnl']} | {_fmt(fresh['expectancy_r'], 3)} | {_fmt(fresh['profit_factor'])} | {_fmt(fresh['max_drawdown_r'])} |",
        f"| 2026 rolling evidence | {prior['sample_count']} | ${prior['net_pnl']} | {_fmt(prior['expectancy_r'], 3)} | {_fmt(prior['profit_factor'])} | {_fmt(result['prior_2026_rolling_evidence']['max_drawdown_r'])} |",
        f"| Provenance-labeled pool | {pooled['sample_count']} | ${pooled['net_pnl']} | {_fmt(pooled['expectancy_r'], 3)} | {_fmt(pooled['profit_factor'])} | {_fmt(pooled['max_drawdown_r'])} |",
        "",
        "The 2025 slice is genuinely unseen during design, but because it precedes the design period it is a fresh backward validation—not forward OOS. The pooled row is diagnostic only.",
        "",
        "## Frozen-rule stress",
        "",
        "| Scenario | n | Net P&L | Expectancy/R | PF |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, key in (
        ("1.5x modeled costs", "one_and_half_times_modeled_costs"),
        ("+2 bp slippage per side", "plus_two_bps_slippage_each_side"),
        ("one extra 15-minute entry bar", "one_extra_15_minute_entry_bar"),
    ):
        row = stress[key]
        lines.append(f"| {label} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend([
        "",
        f"## Decision: {result['decision']}",
        "",
        "The frozen rule fails the fresh-extension PF, expectancy, drawdown, and positive-month admission floors. The prior 2026 result is therefore not promoted as a robust production candidate.",
        "",
        "| Admission criterion | Pass |",
        "|---|---|",
        *[f"| {key} | {value} |" for key, value in result["fresh_extension_admission"]["criteria"].items()],
        "",
        "## 2025 stability",
        "",
        "| Symbol | n | Net P&L | Expectancy/R | PF |",
        "|---|---:|---:|---:|---:|",
    ])
    for key, row in result["fresh_extension"]["symbol_metrics"].items():
        lines.append(f"| {key} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend(["", "| Month | n | Net P&L | Expectancy/R | PF |", "|---|---:|---:|---:|---:|"])
    for key, row in result["fresh_extension"]["month_metrics"].items():
        lines.append(f"| {key} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend(["", "| Lagged SPY regime × direction | n | Net P&L | Expectancy/R | PF |", "|---|---:|---:|---:|---:|"])
    for key, row in result["fresh_extension"]["regime_metrics"].items():
        lines.append(f"| {key} | {row['sample_count']} | ${row['net_pnl']} | {_fmt(row['expectancy_r'], 3)} | {_fmt(row['profit_factor'])} |")
    lines.extend(["", "## Limitations", "", *[f"- {item}" for item in result["limitations"]], ""])
    return "\n".join(lines)


def _update_ledger(result: Mapping[str, Any]) -> None:
    ledger = json.loads(ATTEMPT_LEDGER.read_text(encoding="utf-8"))
    ledger.pop("ledger_hash", None)
    for attempt in ledger["attempts"]:
        if attempt.get("attempt_id") == "equity_overnight_gap_v5":
            attempt["frozen_rule_hash"] = result["frozen_rule_hash"]
            attempt["rolling_oos_metrics"] = result["prior_2026_rolling_evidence"]["metrics"]
            attempt["fresh_backward_validation_2025"] = {
                "provenance": result["provenance"],
                "metrics": result["fresh_extension"]["metrics"],
                "stress": result["stress"],
            }
            attempt["pooled_diagnostic_metrics"] = result["pooled_with_clear_provenance"]["metrics"]
            attempt["fresh_extension_admission"] = result["fresh_extension_admission"]
            attempt["recommendation"] = result["decision"]
            break
    else:
        raise ValueError("ATTEMPT_005_LEDGER_ENTRY_MISSING")
    ledger["ledger_hash"] = canonical_hash(ledger)
    _write_json(ATTEMPT_LEDGER, ledger)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="Fetch real read-only 2025 Alpaca bars before evaluation")
    parser.add_argument("--profile", default=PROFILE)
    parser.add_argument("--cli", type=Path, default=CLI)
    args = parser.parse_args()
    artifact = json.loads(FROZEN_RULE.read_text(encoding="utf-8"))
    validate_frozen_rule(artifact)
    cache = acquire(executable=args.cli, profile=args.profile, output=CACHE) if args.fetch else json.loads(CACHE.read_text(encoding="utf-8"))
    result = evaluate(cache, artifact)
    _write_json(OUTPUT, result)
    REPORT.write_text(report(result), encoding="utf-8")
    _update_ledger(result)
    summary = {
        "frozen_rule_hash": result["frozen_rule_hash"],
        "fresh_extension": result["fresh_extension"]["metrics"],
        "pooled": result["pooled_with_clear_provenance"]["metrics"],
    }
    print(json.dumps(summary, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
