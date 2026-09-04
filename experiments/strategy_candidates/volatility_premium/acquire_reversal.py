#!/usr/bin/env python3
"""Acquire only the read-only option bars needed by the reversal attempts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from acquire import _paged_records, canonical_hash
from candidate import Contract, DataExclusion
from pivots import (
    MOMENTUM_FAMILIES,
    lagged_market_features,
    momentum_direction,
    select_debit_pair,
)

ET = ZoneInfo("America/New_York")


def acquire(base_path: Path, output: Path, executable: Path, profile: str) -> dict[str, Any]:
    base = json.loads(base_path.read_text(encoding="utf-8"))
    base_body = {key: value for key, value in base.items() if key != "content_hash"}
    if canonical_hash(base_body) != base.get("content_hash"):
        raise RuntimeError("PIVOT_CACHE_HASH_MISMATCH")
    contracts: dict[str, list[Contract]] = defaultdict(list)
    for raw in base["contracts"]:
        contracts[str(raw["underlying_symbol"])].append(
            Contract(
                symbol=str(raw["symbol"]),
                expiration=date.fromisoformat(str(raw["expiration_date"])),
                strike=Decimal(str(raw["strike_price"])),
                option_type=str(raw["type"]),  # type: ignore[arg-type]
            )
        )
    sessions: dict[str, list[dict[str, str]]] = defaultdict(list)
    for raw in base["stock_sessions"]:
        sessions[str(raw["symbol"])].append(raw)
    selections: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for symbol, rows in sessions.items():
        closes = [
            (date.fromisoformat(item["session_date"]), Decimal(item["daily_close"]))
            for item in rows
        ]
        for row in rows:
            session_date = date.fromisoformat(row["session_date"])
            if not date(2026, 4, 1) <= session_date <= date(2026, 8, 31):
                continue
            spot = Decimal(row["signal_spot"])
            opening_return = spot / Decimal(row["session_open"]) - Decimal(1)
            for family in MOMENTUM_FAMILIES:
                try:
                    features = lagged_market_features(
                        closes,
                        session_date,
                        trend_lookback=family.trend_sessions,
                    )
                    source_direction = momentum_direction(family, opening_return, features)
                    if source_direction is None:
                        raise DataExclusion("REVERSAL_SIGNAL_FILTER_FALSE")
                    direction = "bearish" if source_direction == "bullish" else "bullish"
                    selected = select_debit_pair(
                        family,
                        direction=direction,
                        session_date=session_date,
                        spot=spot,
                        contracts=contracts[symbol],
                    )
                except DataExclusion as exc:
                    exclusions.append(
                        {
                            "family": family.name,
                            "symbol": symbol,
                            "session_date": session_date.isoformat(),
                            "reason": str(exc),
                        }
                    )
                    continue
                selections.append(
                    {
                        "family": family.name,
                        "symbol": symbol,
                        "session_date": session_date.isoformat(),
                        "direction": direction,
                        "width": str(selected.width),
                        "legs": {"long": selected.long.symbol, "short": selected.short.symbol},
                    }
                )
    weekly: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for selection in selections:
        day = date.fromisoformat(selection["session_date"])
        iso = day.isocalendar()
        weekly[(str(selection["symbol"]), iso.year, iso.week)].append(selection)
    option_bars: list[dict[str, Any]] = []
    commands: list[list[str]] = []
    for rows in weekly.values():
        days = [date.fromisoformat(item["session_date"]) for item in rows]
        symbols = sorted(
            {option_symbol for selection in rows for option_symbol in selection["legs"].values()}
        )
        for offset in range(0, len(symbols), 100):
            records, used = _paged_records(
                executable,
                profile,
                (
                    "data",
                    "option",
                    "bars",
                    "--symbols",
                    ",".join(symbols[offset : offset + 100]),
                    "--start",
                    datetime.combine(min(days), time(10), ET).isoformat(),
                    "--end",
                    datetime.combine(max(days), time(15, 45), ET).isoformat(),
                    "--timeframe",
                    "5Min",
                    "--limit",
                    "10000",
                    "--sort",
                    "asc",
                ),
                result_key="bars",
            )
            commands.extend(used)
            option_bars.extend(records)
    body = {
        "schema_version": "afterimage-reversal-supplement-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "base_cache_hash": base["content_hash"],
        "source": "official Alpaca CLI 0.0.14 authenticated read-only option bars",
        "selections": sorted(
            selections,
            key=lambda item: (item["family"], item["symbol"], item["session_date"]),
        ),
        "pre_bar_exclusions": exclusions,
        "option_bars": sorted(
            option_bars,
            key=lambda item: (str(item.get("symbol")), str(item.get("t"))),
        ),
        "source_commands": commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=root / "data" / "pivot_market_cache.json")
    parser.add_argument("--output", type=Path, default=root / "data" / "reversal_cache.json")
    parser.add_argument("--alpaca-cli", type=Path, default=Path(".tools/bin/alpaca"))
    parser.add_argument("--profile", default="afterimage-paper")
    args = parser.parse_args()
    result = acquire(args.base, args.output, args.alpaca_cli, args.profile)
    print(
        json.dumps(
            {
                "content_hash": result["content_hash"],
                "selections": len(result["selections"]),
                "option_bars": len(result["option_bars"]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
