#!/usr/bin/env python3
"""Acquire real Alpaca option history through read-only official CLI commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from candidate import FAMILIES, Contract, DataExclusion, daily_features, select_contract_pair

ET = ZoneInfo("America/New_York")
READ_PREFIXES = (("data",), ("option", "contracts"))
MUTATION_TOKENS = frozenset({"order", "submit", "cancel", "replace", "close", "exercise"})
WALK_FORWARD_START = date(2026, 4, 1)
TRAINING_END = date(2026, 6, 23)
OOS_START = date(2026, 7, 1)
OOS_END = date(2026, 9, 3)


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def assert_read_only_arguments(arguments: Sequence[str]) -> None:
    normalized = tuple(str(item).lower() for item in arguments)
    permitted = any(normalized[: len(prefix)] == prefix for prefix in READ_PREFIXES)
    if not normalized or not permitted or any(item in MUTATION_TOKENS for item in normalized):
        raise ValueError("READ_ONLY_ACQUISITION_COMMAND_REQUIRED")


def _run_cli(
    executable: Path,
    profile: str,
    arguments: Sequence[str],
    *,
    timeout: int = 180,
) -> dict[str, Any]:
    assert_read_only_arguments(arguments)
    command = [str(executable), "--profile", profile, *arguments, "--quiet", "--timeout", "90"]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ALPACA_READ_FAILED:{' '.join(arguments[:3])}:{completed.returncode}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ALPACA_READ_NON_JSON") from exc
    if not isinstance(value, dict):
        raise TypeError("ALPACA_READ_OBJECT_REQUIRED")
    return value


def _paged_records(
    executable: Path,
    profile: str,
    arguments: Sequence[str],
    *,
    result_key: str,
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    rows: list[dict[str, Any]] = []
    commands: list[list[str]] = []
    page_token = ""
    seen: set[str] = set()
    while True:
        page_arguments = list(arguments)
        if page_token:
            page_arguments.extend(("--page-token", page_token))
        payload = _run_cli(executable, profile, page_arguments)
        commands.append(page_arguments)
        raw = payload.get(result_key)
        if result_key == "bars" and isinstance(raw, dict):
            for symbol, bars in raw.items():
                if not isinstance(bars, list):
                    raise TypeError("ALPACA_BAR_LIST_REQUIRED")
                rows.extend({"symbol": symbol, **item} for item in bars if isinstance(item, dict))
        elif isinstance(raw, list) and all(isinstance(item, dict) for item in raw):
            rows.extend(raw)
        else:
            raise RuntimeError(f"ALPACA_RESULT_MALFORMED:{result_key}")
        page_token = str(payload.get("next_page_token", "") or "")
        if not page_token:
            return rows, commands
        if page_token in seen:
            raise RuntimeError("ALPACA_PAGINATION_LOOP")
        seen.add(page_token)


def load_stock_sessions(path: Path) -> tuple[list[dict[str, Any]], str]:
    raw_bytes = path.read_bytes()
    payload = json.loads(raw_bytes)
    records = [
        *payload.get("training", {}).get("records", []),
        *payload.get("holdout", {}).get("records", []),
    ]
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        timestamp = datetime.fromisoformat(str(record["timestamp"])).astimezone(ET)
        if timestamp.date() < date(2025, 1, 1) or timestamp.date() > OOS_END:
            continue
        grouped[timestamp.date()].append({"timestamp": timestamp, **record["values"]})
    sessions: list[dict[str, Any]] = []
    for session_date, bars in sorted(grouped.items()):
        ordered = sorted(bars, key=lambda item: item["timestamp"])
        before_signal = [item for item in ordered if item["timestamp"].time() < time(10, 0)]
        if not before_signal:
            continue
        sessions.append(
            {
                "session_date": session_date.isoformat(),
                "daily_close": str(ordered[-1]["close"]),
                "signal_spot": str(before_signal[-1]["close"]),
                "signal_source_bar_start": before_signal[-1]["timestamp"].isoformat(),
            }
        )
    return sessions, hashlib.sha256(raw_bytes).hexdigest()


def _research_dates(sessions: Sequence[dict[str, Any]]) -> list[date]:
    return [
        date.fromisoformat(item["session_date"])
        for item in sessions
        if WALK_FORWARD_START <= date.fromisoformat(item["session_date"]) <= TRAINING_END
        or OOS_START <= date.fromisoformat(item["session_date"]) <= OOS_END
    ]


def _normalized_contract(raw: dict[str, Any]) -> dict[str, str] | None:
    try:
        symbol = str(raw["symbol"])
        expiration = date.fromisoformat(str(raw["expiration_date"]))
        strike = Decimal(str(raw["strike_price"]))
        option_type = str(raw["type"]).lower()
    except (KeyError, ValueError, ArithmeticError):
        return None
    if not symbol or not strike.is_finite() or strike <= 0 or option_type != "put":
        return None
    return {
        "symbol": symbol,
        "expiration_date": expiration.isoformat(),
        "strike_price": str(strike),
        "type": option_type,
        "status_at_retrieval": str(raw.get("status", "unknown")),
    }


def _contract_object(raw: dict[str, Any]) -> Contract:
    return Contract(
        symbol=str(raw["symbol"]),
        expiration=date.fromisoformat(str(raw["expiration_date"])),
        strike=Decimal(str(raw["strike_price"])),
        option_type="put",
    )


def acquire(
    *,
    stock_dataset: Path,
    output: Path,
    executable: Path,
    profile: str,
) -> dict[str, Any]:
    sessions, stock_hash = load_stock_sessions(stock_dataset)
    closes = [
        (date.fromisoformat(item["session_date"]), Decimal(item["daily_close"]))
        for item in sessions
    ]
    session_by_date = {date.fromisoformat(item["session_date"]): item for item in sessions}
    research_dates = _research_dates(sessions)
    month_dates: dict[tuple[int, int], list[date]] = defaultdict(list)
    for session_date in research_dates:
        month_dates[(session_date.year, session_date.month)].append(session_date)

    contract_rows: dict[str, dict[str, str]] = {}
    source_commands: list[list[str]] = []
    for dates in month_dates.values():
        spots = [Decimal(session_by_date[item]["signal_spot"]) for item in dates]
        lower = min(spots) - Decimal(50)
        upper = max(spots)
        base = [
            "option",
            "contracts",
            "--underlying-symbols",
            "SPY",
            "--expiration-date-gte",
            (min(dates) + timedelta(days=3)).isoformat(),
            "--expiration-date-lte",
            (max(dates) + timedelta(days=9)).isoformat(),
            "--strike-price-gte",
            str(lower.quantize(Decimal(1))),
            "--strike-price-lte",
            str(upper.quantize(Decimal(1))),
            "--type",
            "put",
            "--limit",
            "10000",
        ]
        for status in ("inactive", "active"):
            raw_rows, commands = _paged_records(
                executable,
                profile,
                [*base, "--status", status],
                result_key="option_contracts",
            )
            source_commands.extend(commands)
            for raw in raw_rows:
                normalized = _normalized_contract(raw)
                if normalized is not None:
                    contract_rows[normalized["symbol"]] = normalized

    contracts = tuple(_contract_object(item) for item in contract_rows.values())
    selections: list[dict[str, str]] = []
    pre_bar_exclusions: list[dict[str, str]] = []
    for session_date in research_dates:
        spot = Decimal(session_by_date[session_date]["signal_spot"])
        for family in FAMILIES:
            try:
                feature = daily_features(closes, session_date, lookback=family.sma_sessions)
                selected = select_contract_pair(
                    family,
                    session_date=session_date,
                    spot=spot,
                    feature=feature,
                    contracts=contracts,
                )
            except DataExclusion as exc:
                pre_bar_exclusions.append(
                    {
                        "session_date": session_date.isoformat(),
                        "family": family.name,
                        "reason": str(exc),
                    }
                )
                continue
            selections.append(
                {
                    "session_date": session_date.isoformat(),
                    "family": family.name,
                    "short_symbol": selected.short.symbol,
                    "long_symbol": selected.long.symbol,
                    "expiration_date": selected.expiration.isoformat(),
                    "short_strike": str(selected.short.strike),
                    "long_strike": str(selected.long.strike),
                    "width": str(selected.width),
                    "signal_spot": str(spot),
                    "target_short_strike": str(selected.target_short_strike),
                }
            )

    selections_by_week: dict[tuple[int, int], list[dict[str, str]]] = defaultdict(list)
    for selection in selections:
        day = date.fromisoformat(selection["session_date"])
        iso = day.isocalendar()
        selections_by_week[(iso.year, iso.week)].append(selection)
    option_bars: list[dict[str, Any]] = []
    for weekly in selections_by_week.values():
        dates = [date.fromisoformat(item["session_date"]) for item in weekly]
        symbols = sorted(
            {symbol for item in weekly for symbol in (item["short_symbol"], item["long_symbol"])}
        )
        for offset in range(0, len(symbols), 100):
            batch = symbols[offset : offset + 100]
            start = datetime.combine(min(dates), time(10, 0), ET)
            end = datetime.combine(max(dates), time(15, 45), ET)
            rows, commands = _paged_records(
                executable,
                profile,
                [
                    "data",
                    "option",
                    "bars",
                    "--symbols",
                    ",".join(batch),
                    "--start",
                    start.isoformat(),
                    "--end",
                    end.isoformat(),
                    "--timeframe",
                    "5Min",
                    "--limit",
                    "10000",
                    "--sort",
                    "asc",
                ],
                result_key="bars",
            )
            source_commands.extend(commands)
            option_bars.extend(rows)

    retrieved_at = datetime.now().astimezone().isoformat()
    body = {
        "schema_version": "afterimage-volatility-premium-cache-v1",
        "retrieved_at": retrieved_at,
        "source": "official Alpaca CLI 0.0.14 authenticated read-only endpoints",
        "stock_dataset": {"path": str(stock_dataset), "sha256": stock_hash},
        "sessions": sessions,
        "contracts": sorted(contract_rows.values(), key=lambda item: item["symbol"]),
        "selections": sorted(selections, key=lambda item: (item["session_date"], item["family"])),
        "pre_bar_exclusions": pre_bar_exclusions,
        "option_bars": sorted(
            option_bars, key=lambda item: (str(item.get("symbol")), str(item.get("t")))
        ),
        "source_commands": source_commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stock-dataset", type=Path, default=Path(".afterimage/research/spy-real-v1.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("data") / "market_cache.json"
    )
    parser.add_argument("--alpaca-cli", type=Path, default=Path(".tools/bin/alpaca"))
    parser.add_argument("--profile", default="afterimage-paper")
    args = parser.parse_args()
    result = acquire(
        stock_dataset=args.stock_dataset,
        output=args.output,
        executable=args.alpaca_cli,
        profile=args.profile,
    )
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
