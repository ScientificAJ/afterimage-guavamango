#!/usr/bin/env python3
"""Score and record opening-move reversal option attempts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from acquire import canonical_hash
from candidate import DataExclusion, OptionBar, SpreadFrame
from ledger import verify_ledger
from pivots import (
    MOMENTUM_FAMILIES,
    PivotTrade,
    simulate_debit_vertical,
    simulate_long_option,
)
from run_pivots import _record_attempt, _write_attempt, build_attempt_result

ET = ZoneInfo("America/New_York")


def _bar(raw: dict[str, Any]) -> OptionBar:
    return OptionBar(
        symbol=str(raw["symbol"]),
        timestamp=datetime.fromisoformat(str(raw["t"])),
        open=Decimal(str(raw["o"])),
        high=Decimal(str(raw["h"])),
        low=Decimal(str(raw["l"])),
        close=Decimal(str(raw["c"])),
        volume=int(raw.get("v", 0)),
    )


def evaluate(
    cache: dict[str, Any],
) -> tuple[
    dict[str, dict[str, tuple[PivotTrade, ...]]],
    dict[str, dict[str, tuple[dict[str, Any], ...]]],
]:
    bars: dict[str, dict[datetime, OptionBar]] = defaultdict(dict)
    for raw in cache["option_bars"]:
        try:
            parsed = _bar(raw)
        except (KeyError, TypeError, ValueError, ArithmeticError, DataExclusion):
            continue
        bars[parsed.symbol][parsed.timestamp] = parsed
    strategies = ("directional_long_reversal", "directional_debit_reversal")
    family_names = tuple(item.name for item in MOMENTUM_FAMILIES)
    trades: dict[str, dict[str, list[PivotTrade]]] = {
        strategy: {family: [] for family in family_names} for strategy in strategies
    }
    exclusions: dict[str, dict[str, list[dict[str, Any]]]] = {
        strategy: {family: [] for family in family_names} for strategy in strategies
    }
    family_lookup = {item.name: item for item in MOMENTUM_FAMILIES}
    for selection in cache["selections"]:
        family_name = str(selection["family"])
        family = family_lookup[family_name]
        symbol = str(selection["symbol"])
        session_date = date.fromisoformat(str(selection["session_date"]))
        direction = str(selection["direction"])
        long_symbol = str(selection["legs"]["long"])
        short_symbol = str(selection["legs"]["short"])
        start = datetime.combine(session_date, time(10), ET)
        end = datetime.combine(session_date, time(15, 40), ET)
        long_timestamps = sorted(
            timestamp for timestamp in bars[long_symbol] if start <= timestamp.astimezone(ET) <= end
        )
        try:
            trade = simulate_long_option(
                session_date=session_date.isoformat(),
                symbol=symbol,
                family=family,
                direction=direction,  # type: ignore[arg-type]
                bars=tuple(bars[long_symbol][timestamp] for timestamp in long_timestamps),
                strategy="directional_long_reversal",
            )
            trades["directional_long_reversal"][family_name].append(trade)
        except (DataExclusion, ArithmeticError, KeyError, ValueError) as exc:
            exclusions["directional_long_reversal"][family_name].append(
                {
                    "strategy": "directional_long_reversal",
                    "family": family_name,
                    "symbol": symbol,
                    "session_date": session_date.isoformat(),
                    "reason": str(exc),
                }
            )
        timestamps = sorted(
            timestamp
            for timestamp in set(bars[long_symbol]).intersection(bars[short_symbol])
            if start <= timestamp.astimezone(ET) <= end
        )
        try:
            trade = simulate_debit_vertical(
                session_date=session_date.isoformat(),
                symbol=symbol,
                family=family,
                direction=direction,  # type: ignore[arg-type]
                width=Decimal(str(selection["width"])),
                frames=tuple(
                    SpreadFrame(
                        timestamp=timestamp,
                        long=bars[long_symbol][timestamp],
                        short=bars[short_symbol][timestamp],
                    )
                    for timestamp in timestamps
                ),
                strategy="directional_debit_reversal",
            )
            trades["directional_debit_reversal"][family_name].append(trade)
        except (DataExclusion, ArithmeticError, KeyError, ValueError) as exc:
            exclusions["directional_debit_reversal"][family_name].append(
                {
                    "strategy": "directional_debit_reversal",
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


def run(cache_path: Path, output_dir: Path, ledger_path: Path) -> dict[str, dict[str, Any]]:
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    body = {key: value for key, value in cache.items() if key != "content_hash"}
    if canonical_hash(body) != cache.get("content_hash"):
        raise RuntimeError("REVERSAL_CACHE_HASH_MISMATCH")
    trades, exclusions = evaluate(cache)
    specs = (
        ("directional_long_reversal", "attempt-07-long-reversal", "attempt-07-long-reversal.json"),
        (
            "directional_debit_reversal",
            "attempt-08-debit-reversal",
            "attempt-08-debit-reversal.json",
        ),
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not verify_ledger(ledger):
        raise RuntimeError("ATTEMPT_LEDGER_INVALID")
    results: dict[str, dict[str, Any]] = {}
    for strategy, attempt_id, filename in specs:
        result = build_attempt_result(
            strategy=strategy,
            trades_by_family=trades[strategy],
            exclusions=exclusions[strategy],
            source_hash=cache["content_hash"],
        )
        sha256 = _write_attempt(output_dir / filename, result)
        ledger = _record_attempt(
            ledger,
            attempt_id=attempt_id,
            artifact_path=f"results/{filename}",
            artifact_sha256=sha256,
            result=result,
        )
        results[strategy] = result
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=root / "data" / "reversal_cache.json")
    parser.add_argument("--output-dir", type=Path, default=root / "results")
    parser.add_argument("--ledger", type=Path, default=root / "results" / "attempt-ledger.json")
    args = parser.parse_args()
    results = run(args.cache, args.output_dir, args.ledger)
    print(
        json.dumps(
            {
                strategy: {"verdict": result["verdict"], **result["rolling"]["metrics"]}
                for strategy, result in results.items()
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
