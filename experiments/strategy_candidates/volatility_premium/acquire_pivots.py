#!/usr/bin/env python3
"""Acquire read-only SPY+QQQ stock/option data for the approved pivot attempts."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from acquire import _paged_records, canonical_hash
from candidate import Contract, DataExclusion
from pivots import (
    CONDOR_FAMILIES,
    MOMENTUM_FAMILIES,
    STRANGLE_FAMILIES,
    condor_signal,
    expansion_signal,
    lagged_market_features,
    momentum_direction,
    select_condor_legs,
    select_debit_pair,
    select_strangle_legs,
)

ET = ZoneInfo("America/New_York")
RESEARCH_START = date(2026, 4, 1)
RESEARCH_END = date(2026, 8, 31)


def normalize_stock_sessions(symbol: str, rows: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            timestamp = datetime.fromisoformat(str(row["t"])).astimezone(ET)
            values = {
                "timestamp": timestamp,
                "open": Decimal(str(row["o"])),
                "close": Decimal(str(row["c"])),
            }
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        if time(9, 30) <= timestamp.time() <= time(15, 55):
            grouped[timestamp.date()].append(values)
    sessions: list[dict[str, str]] = []
    for session_date, bars in sorted(grouped.items()):
        ordered = sorted(bars, key=lambda item: item["timestamp"])
        before_signal = [item for item in ordered if item["timestamp"].time() < time(10)]
        if not before_signal:
            continue
        sessions.append(
            {
                "symbol": symbol,
                "session_date": session_date.isoformat(),
                "session_open": str(ordered[0]["open"]),
                "signal_spot": str(before_signal[-1]["close"]),
                "signal_source_bar_start": before_signal[-1]["timestamp"].isoformat(),
                "daily_close": str(ordered[-1]["close"]),
            }
        )
    return sessions


def _normalize_contract(raw: dict[str, Any]) -> dict[str, str] | None:
    try:
        symbol = str(raw["symbol"])
        expiration = date.fromisoformat(str(raw["expiration_date"]))
        strike = Decimal(str(raw["strike_price"]))
        option_type = str(raw["type"]).lower()
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
    if not symbol or strike <= 0 or not strike.is_finite() or option_type not in {"put", "call"}:
        return None
    return {
        "symbol": symbol,
        "underlying_symbol": str(raw.get("underlying_symbol", "")),
        "expiration_date": expiration.isoformat(),
        "strike_price": str(strike),
        "type": option_type,
        "status_at_retrieval": str(raw.get("status", "unknown")),
    }


def _contract(raw: dict[str, str]) -> Contract:
    return Contract(
        symbol=raw["symbol"],
        expiration=date.fromisoformat(raw["expiration_date"]),
        strike=Decimal(raw["strike_price"]),
        option_type=raw["type"],  # type: ignore[arg-type]
    )


def _fetch_stock(
    executable: Path, profile: str, symbol: str
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    return _paged_records(
        executable,
        profile,
        (
            "data",
            "bars",
            "--symbol",
            symbol,
            "--start",
            datetime(2026, 1, 1, tzinfo=ET).isoformat(),
            "--end",
            datetime(2026, 9, 1, tzinfo=ET).isoformat(),
            "--timeframe",
            "5Min",
            "--feed",
            "iex",
            "--adjustment",
            "raw",
            "--limit",
            "10000",
            "--sort",
            "asc",
        ),
        result_key="bars",
    )


def acquire(*, output: Path, executable: Path, profile: str) -> dict[str, Any]:
    source_commands: list[list[str]] = []
    stock_sessions: list[dict[str, str]] = []
    for symbol in ("SPY", "QQQ"):
        rows, commands = _fetch_stock(executable, profile, symbol)
        source_commands.extend(commands)
        stock_sessions.extend(normalize_stock_sessions(symbol, rows))

    sessions_by_symbol: dict[str, list[dict[str, str]]] = defaultdict(list)
    for session in stock_sessions:
        sessions_by_symbol[session["symbol"]].append(session)
    contract_rows: dict[str, dict[str, str]] = {}
    for symbol, sessions in sessions_by_symbol.items():
        research_sessions = [
            item
            for item in sessions
            if RESEARCH_START <= date.fromisoformat(item["session_date"]) <= RESEARCH_END
        ]
        by_month: dict[str, list[dict[str, str]]] = defaultdict(list)
        for session in research_sessions:
            by_month[session["session_date"][:7]].append(session)
        for monthly in by_month.values():
            days = [date.fromisoformat(item["session_date"]) for item in monthly]
            spots = [Decimal(item["signal_spot"]) for item in monthly]
            base = [
                "option",
                "contracts",
                "--underlying-symbols",
                symbol,
                "--expiration-date-gte",
                (min(days) + timedelta(days=2)).isoformat(),
                "--expiration-date-lte",
                (max(days) + timedelta(days=9)).isoformat(),
                "--strike-price-gte",
                str((min(spots) - Decimal(60)).quantize(Decimal(1))),
                "--strike-price-lte",
                str((max(spots) + Decimal(60)).quantize(Decimal(1))),
                "--limit",
                "10000",
            ]
            for status in ("inactive", "active"):
                rows, commands = _paged_records(
                    executable,
                    profile,
                    (*base, "--status", status),
                    result_key="option_contracts",
                )
                source_commands.extend(commands)
                for raw in rows:
                    normalized = _normalize_contract(raw)
                    if normalized is not None and normalized["underlying_symbol"] == symbol:
                        contract_rows[normalized["symbol"]] = normalized

    contracts_by_symbol: dict[str, list[Contract]] = defaultdict(list)
    for row in contract_rows.values():
        contracts_by_symbol[row["underlying_symbol"]].append(_contract(row))

    selections: list[dict[str, Any]] = []
    pre_bar_exclusions: list[dict[str, str]] = []
    for symbol, sessions in sessions_by_symbol.items():
        closes = [
            (date.fromisoformat(item["session_date"]), Decimal(item["daily_close"]))
            for item in sessions
        ]
        for session in sessions:
            session_date = date.fromisoformat(session["session_date"])
            if not RESEARCH_START <= session_date <= RESEARCH_END:
                continue
            spot = Decimal(session["signal_spot"])
            opening_return = spot / Decimal(session["session_open"]) - Decimal(1)
            for family in MOMENTUM_FAMILIES:
                try:
                    features = lagged_market_features(
                        closes, session_date, trend_lookback=family.trend_sessions
                    )
                    direction = momentum_direction(family, opening_return, features)
                    if direction is None:
                        raise DataExclusion("MOMENTUM_SIGNAL_FILTER_FALSE")
                    selected = select_debit_pair(
                        family,
                        direction=direction,
                        session_date=session_date,
                        spot=spot,
                        contracts=contracts_by_symbol[symbol],
                    )
                except DataExclusion as exc:
                    pre_bar_exclusions.append(
                        {
                            "strategy": "directional_debit_momentum",
                            "family": family.name,
                            "symbol": symbol,
                            "session_date": session_date.isoformat(),
                            "reason": str(exc),
                        }
                    )
                    continue
                selections.append(
                    {
                        "strategy": "directional_debit_momentum",
                        "family": family.name,
                        "symbol": symbol,
                        "session_date": session_date.isoformat(),
                        "direction": direction,
                        "expiration_date": selected.expiration.isoformat(),
                        "width": str(selected.width),
                        "legs": {"long": selected.long.symbol, "short": selected.short.symbol},
                    }
                )
            for family in CONDOR_FAMILIES:
                try:
                    features = lagged_market_features(closes, session_date, trend_lookback=20)
                    if not condor_signal(family, opening_return, features):
                        raise DataExclusion("CONDOR_SIGNAL_FILTER_FALSE")
                    selected = select_condor_legs(
                        family,
                        session_date=session_date,
                        spot=spot,
                        volatility_20=features.volatility_20,
                        contracts=contracts_by_symbol[symbol],
                    )
                except DataExclusion as exc:
                    pre_bar_exclusions.append(
                        {
                            "strategy": "compression_iron_condor",
                            "family": family.name,
                            "symbol": symbol,
                            "session_date": session_date.isoformat(),
                            "reason": str(exc),
                        }
                    )
                    continue
                selections.append(
                    {
                        "strategy": "compression_iron_condor",
                        "family": family.name,
                        "symbol": symbol,
                        "session_date": session_date.isoformat(),
                        "direction": "market_neutral",
                        "expiration_date": selected.expiration.isoformat(),
                        "width": str(selected.width),
                        "legs": {
                            "short_put": selected.short_put.symbol,
                            "long_put": selected.long_put.symbol,
                            "short_call": selected.short_call.symbol,
                            "long_call": selected.long_call.symbol,
                        },
                    }
                )
            for family in STRANGLE_FAMILIES:
                try:
                    features = lagged_market_features(closes, session_date, trend_lookback=20)
                    if not expansion_signal(family, opening_return, features):
                        raise DataExclusion("STRANGLE_SIGNAL_FILTER_FALSE")
                    selected = select_strangle_legs(
                        family,
                        session_date=session_date,
                        spot=spot,
                        contracts=contracts_by_symbol[symbol],
                    )
                except DataExclusion as exc:
                    pre_bar_exclusions.append(
                        {
                            "strategy": "expansion_long_strangle",
                            "family": family.name,
                            "symbol": symbol,
                            "session_date": session_date.isoformat(),
                            "reason": str(exc),
                        }
                    )
                    continue
                selections.append(
                    {
                        "strategy": "expansion_long_strangle",
                        "family": family.name,
                        "symbol": symbol,
                        "session_date": session_date.isoformat(),
                        "direction": "long_volatility",
                        "expiration_date": selected.expiration.isoformat(),
                        "width": "unbounded_profit_defined_debit_risk",
                        "legs": {"put": selected.put.symbol, "call": selected.call.symbol},
                    }
                )

    weekly: dict[tuple[str, int, int], list[dict[str, Any]]] = defaultdict(list)
    for selection in selections:
        day = date.fromisoformat(selection["session_date"])
        iso = day.isocalendar()
        weekly[(selection["symbol"], iso.year, iso.week)].append(selection)
    option_bars: list[dict[str, Any]] = []
    for selections_in_week in weekly.values():
        days = [date.fromisoformat(item["session_date"]) for item in selections_in_week]
        symbols = sorted(
            {
                option_symbol
                for selection in selections_in_week
                for option_symbol in selection["legs"].values()
            }
        )
        for offset in range(0, len(symbols), 100):
            batch = symbols[offset : offset + 100]
            rows, commands = _paged_records(
                executable,
                profile,
                (
                    "data",
                    "option",
                    "bars",
                    "--symbols",
                    ",".join(batch),
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
            source_commands.extend(commands)
            option_bars.extend(rows)

    body = {
        "schema_version": "afterimage-spy-qqq-pivot-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only endpoints",
        "research_start": RESEARCH_START.isoformat(),
        "research_end": RESEARCH_END.isoformat(),
        "stock_sessions": sorted(
            stock_sessions, key=lambda item: (item["symbol"], item["session_date"])
        ),
        "contracts": sorted(contract_rows.values(), key=lambda item: item["symbol"]),
        "selections": sorted(
            selections,
            key=lambda item: (
                item["strategy"],
                item["family"],
                item["symbol"],
                item["session_date"],
            ),
        ),
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
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=root / "data" / "pivot_market_cache.json")
    parser.add_argument("--alpaca-cli", type=Path, default=Path(".tools/bin/alpaca"))
    parser.add_argument("--profile", default="afterimage-paper")
    args = parser.parse_args()
    result = acquire(output=args.output, executable=args.alpaca_cli, profile=args.profile)
    print(
        json.dumps(
            {
                "content_hash": result["content_hash"],
                "stock_sessions": len(result["stock_sessions"]),
                "contracts": len(result["contracts"]),
                "selections": len(result["selections"]),
                "option_bars": len(result["option_bars"]),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
