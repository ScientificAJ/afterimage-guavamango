#!/usr/bin/env python3
"""Run the fixed-family chronological backtest from a sealed local cache."""

from __future__ import annotations

import argparse
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
from candidate import (
    FAMILIES,
    DataExclusion,
    Metrics,
    OptionBar,
    SpreadFrame,
    Trade,
    freeze_family,
    simulate_trade,
    summarize,
)

ET = ZoneInfo("America/New_York")
WALK_FORWARD_START = date(2026, 4, 1)
TRAINING_END = date(2026, 6, 23)
EMBARGO_START = date(2026, 6, 24)
EMBARGO_END = date(2026, 6, 30)
OOS_START = date(2026, 7, 1)
OOS_END = date(2026, 9, 3)


def partition_label(session_date: date) -> str:
    if session_date < WALK_FORWARD_START:
        return "burn_in"
    if WALK_FORWARD_START <= session_date <= TRAINING_END:
        return "walk_forward"
    if EMBARGO_START <= session_date <= EMBARGO_END:
        return "embargo"
    if OOS_START <= session_date <= OOS_END:
        return "oos"
    return "outside"


def _decimal_text(value: Decimal, *, money: bool = False) -> str:
    return str(value.quantize(Decimal("0.01"))) if money else str(value)


def _metrics_payload(metrics: Metrics) -> dict[str, Any]:
    return {
        "sample_count": metrics.sample_count,
        "wins": metrics.wins,
        "losses": metrics.losses,
        "flats": metrics.flats,
        "hit_rate": _decimal_text(metrics.hit_rate),
        "net_pnl": _decimal_text(metrics.net_pnl, money=True),
        "expectancy_r": _decimal_text(metrics.expectancy_r),
        "max_drawdown": _decimal_text(metrics.max_drawdown, money=True),
        "sample_stddev_r": _decimal_text(metrics.sample_stddev_r),
        "mean_ci95_lower_r": _decimal_text(metrics.mean_ci95_lower_r),
        "mean_ci95_upper_r": _decimal_text(metrics.mean_ci95_upper_r),
    }


def _trade_payload(trade: Trade) -> dict[str, Any]:
    raw = asdict(trade)
    return {
        key: value.isoformat()
        if isinstance(value, datetime)
        else str(value)
        if isinstance(value, Decimal)
        else value
        for key, value in raw.items()
    }


def _monthly_stability(trades: Sequence[Trade]) -> dict[str, Any]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.session_date[:7]].append(trade)
    months = {month: _metrics_payload(summarize(rows)) for month, rows in sorted(grouped.items())}
    positive = sum(Decimal(item["expectancy_r"]) > 0 for item in months.values())
    return {
        "months": months,
        "positive_months": positive,
        "observed_months": len(months),
        "positive_month_fraction": str(Decimal(positive) / len(months)) if months else "0",
    }


def build_backtest_result(
    trades_by_family: Mapping[str, Sequence[Trade]],
    *,
    exclusions: Mapping[str, Sequence[dict[str, Any]]],
    source_hash: str,
) -> dict[str, Any]:
    frozen = freeze_family(trades_by_family, training_cutoff=TRAINING_END)
    variants: dict[str, Any] = {}
    for family in FAMILIES:
        rows = tuple(trades_by_family.get(family.name, ()))
        walk_forward = tuple(
            trade
            for trade in rows
            if partition_label(date.fromisoformat(trade.session_date)) == "walk_forward"
        )
        oos = tuple(
            trade
            for trade in rows
            if partition_label(date.fromisoformat(trade.session_date)) == "oos"
        )
        variants[family.name] = {
            "parameters": {
                "sma_sessions": family.sma_sessions,
                "volatility_multiplier": str(family.volatility_multiplier),
                "minimum_distance_fraction": str(family.minimum_distance_fraction),
                "wing_width": str(family.wing_width),
                "minimum_dte": family.minimum_dte,
                "maximum_dte": family.maximum_dte,
            },
            "walk_forward": _metrics_payload(summarize(walk_forward)),
            "walk_forward_folds": _monthly_stability(walk_forward),
            "oos": _metrics_payload(summarize(oos)),
            "oos_stability": _monthly_stability(oos),
            "exclusion_count": len(exclusions.get(family.name, ())),
            "exclusions": list(
                exclusions.get(family.name, ()),
            ),
            "trades": [_trade_payload(item) for item in rows],
        }
    selected_rows = tuple(
        trade
        for trade in trades_by_family.get(frozen.family.name, ())
        if partition_label(date.fromisoformat(trade.session_date)) == "oos"
    )
    body = {
        "schema_version": "afterimage-volatility-premium-backtest-v1",
        "source_cache_hash": source_hash,
        "split": {
            "walk_forward_start": WALK_FORWARD_START.isoformat(),
            "walk_forward_end": TRAINING_END.isoformat(),
            "embargo_start": EMBARGO_START.isoformat(),
            "embargo_end": EMBARGO_END.isoformat(),
            "oos_start": OOS_START.isoformat(),
            "oos_end": OOS_END.isoformat(),
        },
        "pricing_model": {
            "basis": "adverse_synchronized_5min_trade_bar_extremes",
            "entry": "short bar low minus long bar high minus $0.01 per leg",
            "exit": "short bar high minus long bar low plus $0.01 per leg",
            "fee_per_contract_side": "0.03",
            "slippage_per_leg_side": "0.01",
            "quotes_used": False,
            "warning": "Trade-bar bounds are not historical bid/ask quotes or guaranteed fills.",
        },
        "selection": {
            "frozen_family": frozen.family.name,
            "rule": "highest walk-forward expectancy/R; lower drawdown; larger sample; declared order",
            "selected_without_oos": True,
            "walk_forward_metrics": _metrics_payload(frozen.metrics),
        },
        "variants": variants,
        "selected_oos": _metrics_payload(summarize(selected_rows)),
        "selected_oos_stability": _monthly_stability(selected_rows),
    }
    return {**body, "result_hash": canonical_hash(body)}


def _parse_bar(raw: dict[str, Any]) -> OptionBar:
    timestamp = datetime.fromisoformat(str(raw["t"]))
    return OptionBar(
        symbol=str(raw["symbol"]),
        timestamp=timestamp,
        open=Decimal(str(raw["o"])),
        high=Decimal(str(raw["h"])),
        low=Decimal(str(raw["l"])),
        close=Decimal(str(raw["c"])),
        volume=int(raw.get("v", 0)),
    )


def evaluate_cache(
    cache: dict[str, Any],
) -> tuple[dict[str, tuple[Trade, ...]], dict[str, tuple[dict[str, Any], ...]]]:
    bars: dict[str, dict[datetime, OptionBar]] = defaultdict(dict)
    for raw in cache["option_bars"]:
        try:
            parsed = _parse_bar(raw)
        except (KeyError, TypeError, ValueError, ArithmeticError, DataExclusion):
            continue
        bars[parsed.symbol][parsed.timestamp] = parsed

    trades: dict[str, list[Trade]] = {family.name: [] for family in FAMILIES}
    exclusions: dict[str, list[dict[str, Any]]] = {family.name: [] for family in FAMILIES}
    for raw in cache.get("pre_bar_exclusions", []):
        family = str(raw.get("family"))
        if family in exclusions:
            exclusions[family].append(dict(raw))
    for selection in cache["selections"]:
        family = str(selection["family"])
        day = date.fromisoformat(str(selection["session_date"]))
        short_symbol = str(selection["short_symbol"])
        long_symbol = str(selection["long_symbol"])
        start = datetime.combine(day, time(10, 0), ET)
        latest_start = datetime.combine(day, time(15, 40), ET)
        synchronized = sorted(set(bars[short_symbol]).intersection(bars[long_symbol]))
        frames: list[SpreadFrame] = []
        for timestamp in synchronized:
            eastern = timestamp.astimezone(ET)
            if not start <= eastern <= latest_start:
                continue
            try:
                frames.append(
                    SpreadFrame(
                        timestamp=timestamp,
                        short=bars[short_symbol][timestamp],
                        long=bars[long_symbol][timestamp],
                    )
                )
            except DataExclusion:
                continue
        try:
            if len(frames) < 2:
                raise DataExclusion("FEWER_THAN_TWO_SYNCHRONIZED_OPTION_BARS")
            trades[family].append(
                simulate_trade(
                    session_date=day.isoformat(),
                    family=family,
                    short_symbol=short_symbol,
                    long_symbol=long_symbol,
                    width=Decimal(str(selection["width"])),
                    frames=frames,
                )
            )
        except (DataExclusion, ArithmeticError, ValueError) as exc:
            exclusions[family].append(
                {"session_date": day.isoformat(), "family": family, "reason": str(exc)}
            )
    return (
        {name: tuple(rows) for name, rows in trades.items()},
        {name: tuple(rows) for name, rows in exclusions.items()},
    )


def run(cache_path: Path, output: Path) -> dict[str, Any]:
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    body = {key: value for key, value in cache.items() if key != "content_hash"}
    if canonical_hash(body) != cache.get("content_hash"):
        raise RuntimeError("CACHE_HASH_MISMATCH")
    trades, exclusions = evaluate_cache(cache)
    result = build_backtest_result(trades, exclusions=exclusions, source_hash=cache["content_hash"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=root / "data" / "market_cache.json")
    parser.add_argument("--output", type=Path, default=root / "results" / "backtest.json")
    args = parser.parse_args()
    result = run(args.cache, args.output)
    print(
        json.dumps(
            {
                "result_hash": result["result_hash"],
                "frozen_family": result["selection"]["frozen_family"],
                "selected_oos": result["selected_oos"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
