#!/usr/bin/env python3
"""Evaluate and permanently record the approved SPY+QQQ pivot attempts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from acquire import canonical_hash
from candidate import DataExclusion, OptionBar, SpreadFrame
from ledger import append_attempt, verify_ledger
from pivots import (
    CONDOR_FAMILIES,
    MOMENTUM_FAMILIES,
    STRANGLE_FAMILIES,
    CondorFrame,
    PivotMetrics,
    PivotTrade,
    fixed_family_walk_forward,
    promotion_gates,
    rolling_walk_forward,
    simulate_condor,
    simulate_debit_vertical,
    simulate_long_strangle,
    summarize_pivots,
)

ET = ZoneInfo("America/New_York")
EVALUATION_MONTHS = ("2026-05", "2026-06", "2026-07", "2026-08")


def _decimal(value: Decimal) -> str:
    return "Infinity" if value.is_infinite() else str(value)


def _metrics_payload(metrics: PivotMetrics) -> dict[str, Any]:
    return {
        "sample_count": metrics.sample_count,
        "wins": metrics.wins,
        "losses": metrics.losses,
        "flats": metrics.flats,
        "hit_rate": _decimal(metrics.hit_rate),
        "net_pnl": str(metrics.net_pnl),
        "expectancy_r": _decimal(metrics.expectancy_r),
        "max_drawdown": str(metrics.max_drawdown),
        "max_drawdown_r": _decimal(metrics.max_drawdown_r),
        "sample_stddev_r": _decimal(metrics.sample_stddev_r),
        "mean_ci95_lower_r": _decimal(metrics.mean_ci95_lower_r),
        "mean_ci95_upper_r": _decimal(metrics.mean_ci95_upper_r),
        "gross_profit": str(metrics.gross_profit),
        "gross_loss": str(metrics.gross_loss),
        "profit_factor": _decimal(metrics.profit_factor),
    }


def _trade_payload(trade: PivotTrade) -> dict[str, Any]:
    return {
        key: value.isoformat()
        if isinstance(value, datetime)
        else _decimal(value)
        if isinstance(value, Decimal)
        else list(value)
        if isinstance(value, tuple)
        else value
        for key, value in asdict(trade).items()
    }


def _family_names(strategy: str) -> tuple[str, ...]:
    if strategy in {
        "directional_debit_momentum",
        "directional_long_momentum",
        "directional_debit_reversal",
        "directional_long_reversal",
        "causal_vwap_long_reversal",
    }:
        return tuple(item.name for item in MOMENTUM_FAMILIES)
    if strategy in {"compression_iron_condor", "compression_long_strangle"}:
        return tuple(item.name for item in CONDOR_FAMILIES)
    if strategy == "expansion_long_strangle":
        return tuple(item.name for item in STRANGLE_FAMILIES)
    raise ValueError("UNKNOWN_PIVOT_STRATEGY")


def build_attempt_result(
    *,
    strategy: str,
    trades_by_family: Mapping[str, Sequence[PivotTrade]],
    exclusions: Mapping[str, Sequence[dict[str, Any]]],
    source_hash: str,
    fixed_family: str | None = None,
) -> dict[str, Any]:
    family_names = _family_names(strategy)
    if fixed_family is None:
        rolling = rolling_walk_forward(
            trades_by_family,
            family_order=family_names,
            evaluation_months=EVALUATION_MONTHS,
        )
    else:
        if fixed_family not in family_names:
            raise ValueError("FIXED_FAMILY_NOT_DECLARED")
        rolling = fixed_family_walk_forward(
            trades_by_family.get(fixed_family, ()),
            family=fixed_family,
            evaluation_months=EVALUATION_MONTHS,
        )
    neighbor_rows = {
        family: tuple(
            item
            for item in trades_by_family.get(family, ())
            if item.session_date[:7] in EVALUATION_MONTHS
        )
        for family in family_names
    }
    neighbor_metrics = {family: summarize_pivots(rows) for family, rows in neighbor_rows.items()}
    gates = promotion_gates(rolling.trades, neighbor_metrics=neighbor_metrics)
    one_and_half_cost_net = sum(
        (
            item.net_pnl - (item.modeled_fees + item.modeled_slippage) * Decimal("0.50")
            for item in rolling.trades
        ),
        Decimal(0),
    )
    largest_profit = max(
        (item.net_pnl for item in rolling.trades if item.net_pnl > 0),
        default=Decimal(0),
    )
    largest_profit_share = (
        largest_profit / rolling.metrics.gross_profit
        if rolling.metrics.gross_profit > 0
        else Decimal("Infinity")
    )
    by_symbol = {
        symbol: _metrics_payload(
            summarize_pivots([item for item in rolling.trades if item.symbol == symbol])
        )
        for symbol in ("SPY", "QQQ")
    }
    by_month = {
        month: _metrics_payload(
            summarize_pivots(
                [item for item in rolling.trades if item.session_date.startswith(month)]
            )
        )
        for month in EVALUATION_MONTHS
    }
    all_variants = {
        family: {
            "researcher_visible_may_august": _metrics_payload(neighbor_metrics[family]),
            "all_april_august": _metrics_payload(
                summarize_pivots(trades_by_family.get(family, ()))
            ),
            "exclusion_count": len(exclusions.get(family, ())),
            "exclusions": list(exclusions.get(family, ())),
            "trades": [_trade_payload(item) for item in trades_by_family.get(family, ())],
        }
        for family in family_names
    }
    failed = sorted(name for name, passed in gates.items() if name != "promoted" and not passed)
    body = {
        "schema_version": "afterimage-options-pivot-attempt-v1",
        "strategy": strategy,
        "source_cache_hash": source_hash,
        "evaluation_label": "researcher-visible expanding monthly pseudo-OOS; not untouched",
        "evaluation_months": list(EVALUATION_MONTHS),
        "family_selection_rule": (
            f"fixed before scoring: {fixed_family}"
            if fixed_family is not None
            else "highest prior-month pooled SPY+QQQ expectancy/R, then profit factor, drawdown, n, declared order"
        ),
        "rolling": {
            "metrics": _metrics_payload(rolling.metrics),
            "by_symbol": by_symbol,
            "by_month": by_month,
            "operational_target_stop_minimum": _decimal(
                min((item.operational_target_stop for item in rolling.trades), default=Decimal(0))
            ),
            "one_and_half_cost_net_pnl": _decimal(one_and_half_cost_net),
            "largest_trade_profit_share": _decimal(largest_profit_share),
            "trades": [_trade_payload(item) for item in rolling.trades],
            "folds": [
                {
                    "evaluation_month": fold.evaluation_month,
                    "training_start": fold.training_start.isoformat(),
                    "training_end": fold.training_end.isoformat(),
                    "selected_family": fold.selected_family,
                    "selection_metrics": _metrics_payload(fold.selection_metrics),
                    "evaluation_metrics": _metrics_payload(fold.evaluation_metrics),
                    "trade_count": len(fold.trades),
                }
                for fold in rolling.folds
            ],
        },
        "promotion_policy": {
            "operational_target_stop_minimum": "3.0",
            "profit_factor_minimum": "2.0",
            "expectancy_r_minimum": "0.25",
            "pooled_sample_minimum": 30,
            "cross_symbol_positive_or_positive_regimes_minimum": 3,
            "positive_month_fold_fraction_minimum": "0.60",
            "max_drawdown_r_maximum": "6.0",
            "profitable_at_one_and_half_costs": True,
            "largest_trade_profit_share_maximum": "0.25",
            "positive_neighbor_family_fraction_minimum": "0.60",
        },
        "promotion_gates": gates,
        "failed_gates": failed,
        "verdict": "promoted" if gates["promoted"] else "rejected",
        "all_variants": all_variants,
        "pricing_model": {
            "basis": "adverse synchronized 5-minute option trade-bar extremes",
            "quotes_used": False,
            "slippage_per_leg_side": "0.01",
            "fee_per_contract_side": "0.03",
            "warning": "bar-extreme bounds are not historical bid/ask quotes or guaranteed fills",
        },
    }
    return {**body, "result_hash": canonical_hash(body)}


def _parse_option_bar(raw: dict[str, Any]) -> OptionBar:
    return OptionBar(
        symbol=str(raw["symbol"]),
        timestamp=datetime.fromisoformat(str(raw["t"])),
        open=Decimal(str(raw["o"])),
        high=Decimal(str(raw["h"])),
        low=Decimal(str(raw["l"])),
        close=Decimal(str(raw["c"])),
        volume=int(raw.get("v", 0)),
    )


def evaluate_cache(
    cache: dict[str, Any],
) -> tuple[
    dict[str, dict[str, tuple[PivotTrade, ...]]],
    dict[str, dict[str, tuple[dict[str, Any], ...]]],
]:
    bars: dict[str, dict[datetime, OptionBar]] = defaultdict(dict)
    for raw in cache["option_bars"]:
        try:
            parsed = _parse_option_bar(raw)
        except (KeyError, TypeError, ValueError, ArithmeticError, DataExclusion):
            continue
        bars[parsed.symbol][parsed.timestamp] = parsed
    strategies = {
        "directional_debit_momentum": tuple(item.name for item in MOMENTUM_FAMILIES),
        "compression_iron_condor": tuple(item.name for item in CONDOR_FAMILIES),
        "expansion_long_strangle": tuple(item.name for item in STRANGLE_FAMILIES),
    }
    trades: dict[str, dict[str, list[PivotTrade]]] = {
        strategy: {family: [] for family in families} for strategy, families in strategies.items()
    }
    exclusions: dict[str, dict[str, list[dict[str, Any]]]] = {
        strategy: {family: [] for family in families} for strategy, families in strategies.items()
    }
    for item in cache["pre_bar_exclusions"]:
        strategy = str(item["strategy"])
        family = str(item["family"])
        exclusions[strategy][family].append(dict(item))
    momentum_lookup = {item.name: item for item in MOMENTUM_FAMILIES}
    condor_lookup = {item.name: item for item in CONDOR_FAMILIES}
    strangle_lookup = {item.name: item for item in STRANGLE_FAMILIES}
    for selection in cache["selections"]:
        strategy = str(selection["strategy"])
        family_name = str(selection["family"])
        symbol = str(selection["symbol"])
        session_date = date.fromisoformat(str(selection["session_date"]))
        leg_symbols = tuple(str(item) for item in selection["legs"].values())
        synchronized = sorted(set.intersection(*(set(bars[item]) for item in leg_symbols)))
        start = datetime.combine(session_date, time(10), ET)
        end = datetime.combine(session_date, time(15, 40), ET)
        synchronized = [item for item in synchronized if start <= item.astimezone(ET) <= end]
        try:
            if len(synchronized) < 2:
                raise DataExclusion("FEWER_THAN_TWO_SYNCHRONIZED_OPTION_BARS")
            if strategy == "directional_debit_momentum":
                long_symbol = str(selection["legs"]["long"])
                short_symbol = str(selection["legs"]["short"])
                frames = tuple(
                    SpreadFrame(
                        timestamp=timestamp,
                        long=bars[long_symbol][timestamp],
                        short=bars[short_symbol][timestamp],
                    )
                    for timestamp in synchronized
                )
                trade = simulate_debit_vertical(
                    session_date=session_date.isoformat(),
                    symbol=symbol,
                    family=momentum_lookup[family_name],
                    direction=selection["direction"],
                    width=Decimal(str(selection["width"])),
                    frames=frames,
                )
            elif strategy == "compression_iron_condor":
                legs = selection["legs"]
                frames = tuple(
                    CondorFrame(
                        timestamp=timestamp,
                        short_put=bars[str(legs["short_put"])][timestamp],
                        long_put=bars[str(legs["long_put"])][timestamp],
                        short_call=bars[str(legs["short_call"])][timestamp],
                        long_call=bars[str(legs["long_call"])][timestamp],
                    )
                    for timestamp in synchronized
                )
                trade = simulate_condor(
                    session_date=session_date.isoformat(),
                    symbol=symbol,
                    family=condor_lookup[family_name],
                    width=Decimal(str(selection["width"])),
                    frames=frames,
                )
            else:
                put_symbol = str(selection["legs"]["put"])
                call_symbol = str(selection["legs"]["call"])
                strangle_frames = tuple(
                    (bars[put_symbol][timestamp], bars[call_symbol][timestamp])
                    for timestamp in synchronized
                )
                trade = simulate_long_strangle(
                    session_date=session_date.isoformat(),
                    symbol=symbol,
                    family=strangle_lookup[family_name],
                    frames=strangle_frames,
                )
            trades[strategy][family_name].append(trade)
        except (DataExclusion, ArithmeticError, KeyError, ValueError) as exc:
            exclusions[strategy][family_name].append(
                {
                    "strategy": strategy,
                    "family": family_name,
                    "symbol": symbol,
                    "session_date": session_date.isoformat(),
                    "reason": str(exc),
                }
            )
    return (
        {
            strategy: {family: tuple(rows) for family, rows in families.items()}
            for strategy, families in trades.items()
        },
        {
            strategy: {family: tuple(rows) for family, rows in families.items()}
            for strategy, families in exclusions.items()
        },
    )


def _write_attempt(path: Path, result: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_attempt(
    ledger: dict[str, Any],
    *,
    attempt_id: str,
    artifact_path: str,
    artifact_sha256: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    existing = next((item for item in ledger["entries"] if item["attempt_id"] == attempt_id), None)
    if existing is not None:
        if (
            existing["artifact_path"] != artifact_path
            or existing["artifact_sha256"] != artifact_sha256
        ):
            raise RuntimeError("IMMUTABLE_ATTEMPT_ARTIFACT_CHANGED")
        return ledger
    metrics = result["rolling"]["metrics"]
    return append_attempt(
        ledger,
        attempt_id=attempt_id,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        summary={
            "strategy": result["strategy"],
            "verdict": result["verdict"],
            "sample_count": metrics["sample_count"],
            "net_pnl": metrics["net_pnl"],
            "expectancy_r": metrics["expectancy_r"],
            "operational_target_stop": result["rolling"]["operational_target_stop_minimum"],
            "profit_factor": metrics["profit_factor"],
            "failed_gates": result["failed_gates"],
        },
    )


def run(
    *,
    cache_path: Path,
    debit_output: Path,
    condor_output: Path,
    strangle_output: Path,
    ledger_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache_body = {key: value for key, value in cache.items() if key != "content_hash"}
    if canonical_hash(cache_body) != cache.get("content_hash"):
        raise RuntimeError("PIVOT_CACHE_HASH_MISMATCH")
    trades, exclusions = evaluate_cache(cache)
    debit = build_attempt_result(
        strategy="directional_debit_momentum",
        trades_by_family=trades["directional_debit_momentum"],
        exclusions=exclusions["directional_debit_momentum"],
        source_hash=cache["content_hash"],
    )
    condor = build_attempt_result(
        strategy="compression_iron_condor",
        trades_by_family=trades["compression_iron_condor"],
        exclusions=exclusions["compression_iron_condor"],
        source_hash=cache["content_hash"],
    )
    strangle = build_attempt_result(
        strategy="expansion_long_strangle",
        trades_by_family=trades["expansion_long_strangle"],
        exclusions=exclusions["expansion_long_strangle"],
        source_hash=cache["content_hash"],
    )
    debit_sha = _write_attempt(debit_output, debit)
    condor_sha = _write_attempt(condor_output, condor)
    strangle_sha = _write_attempt(strangle_output, strangle)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not verify_ledger(ledger):
        raise RuntimeError("ATTEMPT_LEDGER_INVALID")
    ledger = _record_attempt(
        ledger,
        attempt_id="attempt-02-directional-debit",
        artifact_path="results/attempt-02-directional-debit.json",
        artifact_sha256=debit_sha,
        result=debit,
    )
    ledger = _record_attempt(
        ledger,
        attempt_id="attempt-03-iron-condor",
        artifact_path="results/attempt-03-iron-condor.json",
        artifact_sha256=condor_sha,
        result=condor,
    )
    ledger = _record_attempt(
        ledger,
        attempt_id="attempt-04-long-strangle",
        artifact_path="results/attempt-04-long-strangle.json",
        artifact_sha256=strangle_sha,
        result=strangle,
    )
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return debit, condor, strangle, ledger


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=root / "data" / "pivot_market_cache.json")
    parser.add_argument(
        "--debit-output", type=Path, default=root / "results" / "attempt-02-directional-debit.json"
    )
    parser.add_argument(
        "--condor-output", type=Path, default=root / "results" / "attempt-03-iron-condor.json"
    )
    parser.add_argument(
        "--strangle-output", type=Path, default=root / "results" / "attempt-04-long-strangle.json"
    )
    parser.add_argument("--ledger", type=Path, default=root / "results" / "attempt-ledger.json")
    args = parser.parse_args()
    debit, condor, strangle, ledger = run(
        cache_path=args.cache,
        debit_output=args.debit_output,
        condor_output=args.condor_output,
        strangle_output=args.strangle_output,
        ledger_path=args.ledger,
    )
    print(
        json.dumps(
            {
                "debit": {"verdict": debit["verdict"], **debit["rolling"]["metrics"]},
                "condor": {"verdict": condor["verdict"], **condor["rolling"]["metrics"]},
                "strangle": {"verdict": strangle["verdict"], **strangle["rolling"]["metrics"]},
                "ledger_hash": ledger["ledger_hash"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
