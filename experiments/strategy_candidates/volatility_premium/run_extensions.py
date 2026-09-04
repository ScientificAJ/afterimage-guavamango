#!/usr/bin/env python3
"""Score additional predeclared option hypotheses from the immutable pivot cache."""

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
from candidate import DataExclusion, OptionBar
from ledger import verify_ledger
from pivots import (
    CONDOR_FAMILIES,
    MOMENTUM_FAMILIES,
    PivotTrade,
    StrangleFamily,
    simulate_long_option,
    simulate_long_strangle,
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


def evaluate_extensions(
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
    strategies = {
        "directional_long_momentum": tuple(item.name for item in MOMENTUM_FAMILIES),
        "compression_long_strangle": tuple(item.name for item in CONDOR_FAMILIES),
    }
    trades: dict[str, dict[str, list[PivotTrade]]] = {
        strategy: {family: [] for family in families} for strategy, families in strategies.items()
    }
    exclusions: dict[str, dict[str, list[dict[str, Any]]]] = {
        strategy: {family: [] for family in families} for strategy, families in strategies.items()
    }
    momentum = {item.name: item for item in MOMENTUM_FAMILIES}
    condors = {item.name: item for item in CONDOR_FAMILIES}
    for selection in cache["selections"]:
        source_strategy = str(selection["strategy"])
        if source_strategy not in {"directional_debit_momentum", "compression_iron_condor"}:
            continue
        family_name = str(selection["family"])
        symbol = str(selection["symbol"])
        session_date = date.fromisoformat(str(selection["session_date"]))
        start = datetime.combine(session_date, time(10), ET)
        end = datetime.combine(session_date, time(15, 40), ET)
        if source_strategy == "directional_debit_momentum":
            strategy = "directional_long_momentum"
            option_symbol = str(selection["legs"]["long"])
            timestamps = sorted(
                timestamp
                for timestamp in bars[option_symbol]
                if start <= timestamp.astimezone(ET) <= end
            )
            try:
                trade = simulate_long_option(
                    session_date=session_date.isoformat(),
                    symbol=symbol,
                    family=momentum[family_name],
                    direction=selection["direction"],
                    bars=tuple(bars[option_symbol][timestamp] for timestamp in timestamps),
                )
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
                continue
        else:
            strategy = "compression_long_strangle"
            put_symbol = str(selection["legs"]["short_put"])
            call_symbol = str(selection["legs"]["short_call"])
            timestamps = sorted(
                timestamp
                for timestamp in set(bars[put_symbol]).intersection(bars[call_symbol])
                if start <= timestamp.astimezone(ET) <= end
            )
            source = condors[family_name]
            family = StrangleFamily(
                name=family_name,
                opening_threshold=Decimal(0),
                minimum_volatility_ratio=Decimal(0),
                distance_fraction=Decimal(0),
                minimum_dte=source.minimum_dte,
                maximum_dte=source.maximum_dte,
                stop_fraction_of_debit=source.stop_fraction_of_credit,
            )
            try:
                trade = simulate_long_strangle(
                    session_date=session_date.isoformat(),
                    symbol=symbol,
                    family=family,
                    frames=tuple(
                        (bars[put_symbol][timestamp], bars[call_symbol][timestamp])
                        for timestamp in timestamps
                    ),
                    strategy=strategy,
                )
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
                continue
        trades[strategy][family_name].append(trade)
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
    cache_body = {key: value for key, value in cache.items() if key != "content_hash"}
    if canonical_hash(cache_body) != cache.get("content_hash"):
        raise RuntimeError("PIVOT_CACHE_HASH_MISMATCH")
    trades, exclusions = evaluate_extensions(cache)
    results: dict[str, dict[str, Any]] = {}
    attempt_specs = (
        (
            "directional_long_momentum",
            "attempt-05-directional-long",
            "attempt-05-directional-long.json",
        ),
        (
            "compression_long_strangle",
            "attempt-06-compression-long-strangle",
            "attempt-06-compression-long-strangle.json",
        ),
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not verify_ledger(ledger):
        raise RuntimeError("ATTEMPT_LEDGER_INVALID")
    for strategy, attempt_id, filename in attempt_specs:
        result = build_attempt_result(
            strategy=strategy,
            trades_by_family=trades[strategy],
            exclusions=exclusions[strategy],
            source_hash=cache["content_hash"],
        )
        artifact_sha256 = _write_attempt(output_dir / filename, result)
        ledger = _record_attempt(
            ledger,
            attempt_id=attempt_id,
            artifact_path=f"results/{filename}",
            artifact_sha256=artifact_sha256,
            result=result,
        )
        results[strategy] = result
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return results


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=root / "data" / "pivot_market_cache.json")
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
