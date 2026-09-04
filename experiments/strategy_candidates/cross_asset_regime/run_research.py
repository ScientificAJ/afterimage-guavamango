#!/usr/bin/env python3
"""Acquire and evaluate the frozen cross-asset breadth option strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

try:
    from .candidate import (
        Costs,
        Contract,
        DataExclusion,
        Metrics,
        OptionBar,
        OptionFrame,
        ScoredTrade,
        Signal,
        StockBar,
        Trade,
        UNIVERSE,
        VARIANTS,
        Variant,
        enforce_non_overlapping,
        select_on_training,
        select_vertical,
        signal_for_session,
        simulate_trade,
        summarize,
    )
except ImportError:
    from candidate import (  # type: ignore[no-redef]
        Costs,
        Contract,
        DataExclusion,
        Metrics,
        OptionBar,
        OptionFrame,
        ScoredTrade,
        Signal,
        StockBar,
        Trade,
        UNIVERSE,
        VARIANTS,
        Variant,
        enforce_non_overlapping,
        select_on_training,
        select_vertical,
        signal_for_session,
        simulate_trade,
        summarize,
    )


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA_CACHE = HERE / "data" / "market_cache.json"
BACKTEST = HERE / "results" / "backtest.json"
ATTEMPT_LEDGER = HERE / "results" / "attempt_ledger.json"
REPORT = HERE / "REPORT.md"
ET = ZoneInfo("America/New_York")
PROFILE = "afterimage-paper"
START = datetime(2026, 1, 2, tzinfo=UTC)
END = datetime(2026, 9, 4, tzinfo=UTC)
DEVELOPMENT_END = date(2026, 7, 31)
HOLDOUT_START = date(2026, 8, 3)
HOLDOUT_END = date(2026, 9, 3)
STOCK_SYMBOLS = ("SPY", *UNIVERSE)
COSTS = Costs(Decimal("0.03"), Decimal("0.65"))
READ_PREFIXES = (
    ("data", "bars"),
    ("data", "option", "bars"),
    ("data", "option", "latest-quotes"),
    ("option", "contracts"),
    ("account", "get"),
    ("account", "config", "get"),
)
MUTATION_TOKENS = frozenset(
    {"order", "submit", "cancel", "replace", "close", "exercise", "patch", "delete", "post"}
)


@dataclass(frozen=True)
class DevelopmentFold:
    training_start: date
    training_end: date
    validation_start: date
    validation_end: date
    training_dates: tuple[date, ...]
    validation_dates: tuple[date, ...]


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )


def assert_read_only_arguments(arguments: Sequence[str]) -> None:
    normalized = tuple(str(item).lower() for item in arguments)
    if not any(normalized[: len(prefix)] == prefix for prefix in READ_PREFIXES):
        raise ValueError("READ_ONLY_ALPACA_COMMAND_REQUIRED")
    if any(item.lstrip("-") in MUTATION_TOKENS for item in normalized):
        raise ValueError("READ_ONLY_ALPACA_COMMAND_REQUIRED")


def partition_for(session: date) -> str:
    if START.date() <= session <= DEVELOPMENT_END:
        return "development"
    if HOLDOUT_START <= session <= HOLDOUT_END:
        return "untouched_holdout"
    return "outside"


def development_folds(sessions: Sequence[date]) -> tuple[DevelopmentFold, ...]:
    eligible = tuple(sorted(set(day for day in sessions if START.date() <= day <= DEVELOPMENT_END)))
    folds: list[DevelopmentFold] = []
    for month in (5, 6, 7):
        validation = tuple(day for day in eligible if day.month == month)
        training = tuple(day for day in eligible if day < date(2026, month, 1))
        if not training or not validation:
            continue
        folds.append(
            DevelopmentFold(
                training_start=training[0],
                training_end=training[-1],
                validation_start=validation[0],
                validation_end=validation[-1],
                training_dates=training,
                validation_dates=validation,
            )
        )
    return tuple(folds)


def freeze_candidate(
    rows_by_variant: Mapping[str, Sequence[ScoredTrade]],
    folds: Sequence[DevelopmentFold],
    *,
    minimum_samples: int,
) -> dict[str, Any]:
    validation_dates = {day for fold in folds for day in fold.validation_dates}
    candidates: list[tuple[Decimal, Decimal, str, Metrics]] = []
    for name, rows in rows_by_variant.items():
        validation = tuple(item for item in rows if item.session in validation_dates)
        if len(validation) < minimum_samples:
            continue
        metrics = summarize(validation)
        candidates.append((metrics.expectancy_r, metrics.net_pnl, name, metrics))
    if not candidates:
        return {
            "selected_variant": None,
            "validation_metrics": summarize(()),
            "observed_partitions": ("development_validation",),
        }
    expectancy, net_pnl, name, metrics = sorted(
        candidates, key=lambda item: (-item[0], -item[1], item[2])
    )[0]
    del expectancy, net_pnl
    return {
        "selected_variant": name,
        "validation_metrics": metrics,
        "observed_partitions": ("development_validation",),
    }


def _run_cli(
    executable: Path,
    profile: str,
    arguments: Sequence[str],
    *,
    timeout: int = 180,
) -> dict[str, Any]:
    assert_read_only_arguments(arguments)
    completed = subprocess.run(
        [str(executable), "--profile", profile, *arguments, "--quiet", "--timeout", "90"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or ["unknown"]
        raise RuntimeError(f"ALPACA_READ_FAILED:{' '.join(arguments[:3])}:{detail[0]}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ALPACA_READ_NON_JSON") from exc
    if not isinstance(result, dict):
        raise RuntimeError("ALPACA_READ_OBJECT_REQUIRED")
    return result


def _paged_rows(
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
        request = list(arguments)
        if page_token:
            request.extend(("--page-token", page_token))
        payload = _run_cli(executable, profile, request)
        commands.append(request)
        raw = payload.get(result_key)
        rows.extend(_normalize_result_rows(raw, request, result_key=result_key))
        page_token = str(payload.get("next_page_token") or "")
        if not page_token:
            return rows, commands
        if page_token in seen:
            raise RuntimeError("ALPACA_PAGINATION_LOOP")
        seen.add(page_token)


def _normalize_result_rows(
    raw: Any, arguments: Sequence[str], *, result_key: str
) -> list[dict[str, Any]]:
    if result_key == "bars" and isinstance(raw, dict):
        rows: list[dict[str, Any]] = []
        for symbol, items in raw.items():
            if not isinstance(items, list):
                raise RuntimeError("ALPACA_BAR_LIST_REQUIRED")
            rows.extend({"symbol": symbol, **item} for item in items if isinstance(item, dict))
        return rows
    if isinstance(raw, list):
        rows = [dict(item) for item in raw if isinstance(item, dict)]
        if result_key == "bars":
            values = tuple(arguments)
            symbol = ""
            for flag in ("--symbol", "--symbols"):
                if flag in values:
                    candidate = values[values.index(flag) + 1]
                    if "," not in candidate:
                        symbol = candidate
            if symbol:
                rows = [{"symbol": symbol, **item} for item in rows]
        return rows
    raise RuntimeError(f"ALPACA_RESULT_MALFORMED:{result_key}")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _stock_objects(rows: Sequence[Mapping[str, Any]]) -> tuple[StockBar, ...]:
    parsed: list[StockBar] = []
    for row in rows:
        timestamp = _parse_timestamp(str(row["t"]))
        local = timestamp.astimezone(ET)
        if local.weekday() >= 5 or not (time(9, 30) <= local.time() < time(16, 0)):
            continue
        parsed.append(
            StockBar(
                symbol=str(row["symbol"]),
                timestamp=timestamp,
                open=Decimal(str(row["o"])),
                high=Decimal(str(row["h"])),
                low=Decimal(str(row["l"])),
                close=Decimal(str(row["c"])),
                volume=int(row["v"]),
            )
        )
    return tuple(sorted(parsed, key=lambda item: (item.timestamp, item.symbol)))


def _spy_daily_closes(bars: Sequence[StockBar]) -> tuple[tuple[date, Decimal], ...]:
    grouped: dict[date, list[StockBar]] = defaultdict(list)
    for bar in bars:
        if bar.symbol == "SPY":
            grouped[bar.timestamp.astimezone(ET).date()].append(bar)
    return tuple(
        (session, sorted(rows, key=lambda item: item.timestamp)[-1].close)
        for session, rows in sorted(grouped.items())
    )


def _signals(
    stock: Sequence[StockBar],
) -> tuple[dict[str, tuple[Any, ...]], list[dict[str, str]]]:
    by_session: dict[date, list[StockBar]] = defaultdict(list)
    for bar in stock:
        if bar.symbol in UNIVERSE:
            by_session[bar.timestamp.astimezone(ET).date()].append(bar)
    daily = _spy_daily_closes(stock)
    signals: dict[str, list[Any]] = {variant.name: [] for variant in VARIANTS}
    exclusions: list[dict[str, str]] = []
    for session, bars in sorted(by_session.items()):
        if partition_for(session) == "outside":
            continue
        for variant in VARIANTS:
            try:
                signal = signal_for_session(variant, bars, daily, session)
            except DataExclusion as exc:
                exclusions.append(
                    {"stage": "signal", "session": session.isoformat(), "variant": variant.name, "reason": str(exc)}
                )
                continue
            if signal is not None:
                signals[variant.name].append(signal)
    return {key: tuple(value) for key, value in signals.items()}, exclusions


def _normalize_contract(raw: Mapping[str, Any], underlying: str) -> dict[str, str] | None:
    try:
        symbol = str(raw["symbol"])
        expiration = date.fromisoformat(str(raw["expiration_date"]))
        strike = Decimal(str(raw["strike_price"]))
        option_type = str(raw["type"]).lower()
    except (KeyError, ValueError, ArithmeticError):
        return None
    if not symbol or strike <= 0 or option_type not in {"call", "put"}:
        return None
    return {
        "symbol": symbol,
        "underlying": underlying,
        "expiration_date": expiration.isoformat(),
        "strike_price": str(strike),
        "type": option_type,
        "status_at_retrieval": str(raw.get("status", "unknown")),
    }


def _contract_object(raw: Mapping[str, Any]) -> Contract:
    return Contract(
        symbol=str(raw["symbol"]),
        underlying=str(raw["underlying"]),
        expiration=date.fromisoformat(str(raw["expiration_date"])),
        strike=Decimal(str(raw["strike_price"])),
        option_type=str(raw["type"]),  # type: ignore[arg-type]
    )


def _chunks(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def acquire(*, executable: Path, profile: str, output: Path) -> dict[str, Any]:
    stock_rows: list[dict[str, Any]] = []
    source_commands: list[list[str]] = []
    for symbol in STOCK_SYMBOLS:
        rows, commands = _paged_rows(
            executable,
            profile,
            (
                "data", "bars", "--symbol", symbol,
                "--start", START.isoformat(), "--end", END.isoformat(),
                "--timeframe", "15Min", "--feed", "iex", "--adjustment", "raw",
                "--sort", "asc", "--limit", "10000",
            ),
            result_key="bars",
        )
        stock_rows.extend(rows)
        source_commands.extend(commands)
    stock = _stock_objects(stock_rows)
    signals_by_variant, signal_exclusions = _signals(stock)
    unique_signals: dict[tuple[Any, ...], Any] = {}
    for signals in signals_by_variant.values():
        for signal in signals:
            key = (signal.session, signal.direction, signal.underlying, signal.reference_price)
            unique_signals[key] = signal

    signal_groups: dict[tuple[int, int, str], list[Any]] = defaultdict(list)
    for signal in unique_signals.values():
        signal_groups[(signal.session.year, signal.session.month, signal.underlying)].append(signal)
    contract_rows: dict[str, dict[str, str]] = {}
    for (_, _, underlying), signals in sorted(signal_groups.items()):
        spots = [signal.reference_price for signal in signals]
        lower = (min(spots) - Decimal(8)).quantize(Decimal(1), rounding=ROUND_FLOOR)
        upper = (max(spots) + Decimal(8)).quantize(Decimal(1), rounding=ROUND_CEILING)
        base = (
            "option", "contracts", "--underlying-symbols", underlying,
            "--expiration-date-gte", (min(item.session for item in signals) + timedelta(days=3)).isoformat(),
            "--expiration-date-lte", (max(item.session for item in signals) + timedelta(days=9)).isoformat(),
            "--strike-price-gte", str(lower), "--strike-price-lte", str(upper), "--limit", "10000",
        )
        for status in ("inactive", "active"):
            rows, commands = _paged_rows(
                executable, profile, (*base, "--status", status), result_key="option_contracts"
            )
            source_commands.extend(commands)
            for raw in rows:
                normalized = _normalize_contract(raw, underlying)
                if normalized is not None:
                    contract_rows[normalized["symbol"]] = normalized
    contracts = tuple(_contract_object(row) for row in contract_rows.values())
    selections: list[dict[str, Any]] = []
    exclusions = list(signal_exclusions)
    for variant in VARIANTS:
        for signal in signals_by_variant[variant.name]:
            try:
                vertical = select_vertical(signal, contracts)
            except DataExclusion as exc:
                exclusions.append(
                    {"stage": "contract", "session": signal.session.isoformat(), "variant": variant.name, "reason": str(exc)}
                )
                continue
            selections.append(
                {
                    "session": signal.session.isoformat(),
                    "variant": variant.name,
                    "direction": signal.direction,
                    "underlying": signal.underlying,
                    "completed_at": signal.completed_at.isoformat(),
                    "reference_price": str(signal.reference_price),
                    "breadth_count": signal.breadth_count,
                    "mean_return": str(signal.mean_return),
                    "long_symbol": vertical.long.symbol,
                    "long_strike": str(vertical.long.strike),
                    "short_symbol": vertical.short.symbol,
                    "short_strike": str(vertical.short.strike),
                    "expiration": vertical.long.expiration.isoformat(),
                }
            )
    option_rows: list[dict[str, Any]] = []
    symbols = sorted(
        {str(item[key]) for item in selections for key in ("long_symbol", "short_symbol")}
    )
    for batch in _chunks(symbols, 80):
        rows, commands = _paged_rows(
            executable,
            profile,
            (
                "data", "option", "bars", "--symbols", ",".join(batch),
                "--start", START.isoformat(), "--end", END.isoformat(),
                "--timeframe", "15Min", "--sort", "asc", "--limit", "10000",
            ),
            result_key="bars",
        )
        option_rows.extend(rows)
        source_commands.extend(commands)
    body = {
        "schema_version": "afterimage-cross-asset-market-cache-v1",
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source": "official Alpaca CLI 0.0.14 authenticated read-only endpoints",
        "profile": profile,
        "bounds": {"start": START, "end_exclusive": END},
        "stock": {"feed": "iex", "adjustment": "raw", "timeframe": "15Min", "bars": stock_rows},
        "contracts": sorted(contract_rows.values(), key=lambda item: item["symbol"]),
        "selections": sorted(selections, key=lambda item: (item["session"], item["variant"])),
        "option": {"timeframe": "15Min", "bars": sorted(option_rows, key=lambda item: (str(item.get("symbol")), str(item.get("t"))))},
        "exclusions": exclusions,
        "source_commands": source_commands,
    }
    result = {**body, "content_hash": canonical_hash(body)}
    _write_json(output, result)
    return result


def _option_frames(
    rows: Sequence[Mapping[str, Any]], long_symbol: str, short_symbol: str, session: date
) -> tuple[OptionFrame, ...]:
    by_symbol: dict[str, dict[datetime, OptionBar]] = defaultdict(dict)
    for row in rows:
        symbol = str(row.get("symbol", ""))
        if symbol not in {long_symbol, short_symbol}:
            continue
        timestamp = _parse_timestamp(str(row["t"]))
        if timestamp.astimezone(ET).date() != session:
            continue
        bar = OptionBar(
            symbol=symbol,
            timestamp=timestamp,
            open=Decimal(str(row["o"])), high=Decimal(str(row["h"])),
            low=Decimal(str(row["l"])), close=Decimal(str(row["c"])), volume=int(row["v"]),
        )
        by_symbol[symbol][timestamp] = bar
    timestamps = sorted(set(by_symbol[long_symbol]) & set(by_symbol[short_symbol]))
    return tuple(
        OptionFrame(timestamp, by_symbol[long_symbol][timestamp], by_symbol[short_symbol][timestamp])
        for timestamp in timestamps
    )


def _signal_from_selection(item: Mapping[str, Any]) -> Any:
    from_types = {variant.name: variant for variant in VARIANTS}
    variant = from_types[str(item["variant"])]
    return Signal(
        session=date.fromisoformat(str(item["session"])),
        completed_at=_parse_timestamp(str(item["completed_at"])),
        direction=str(item["direction"]),
        underlying=str(item["underlying"]),
        reference_price=Decimal(str(item["reference_price"])),
        breadth_count=int(item["breadth_count"]),
        mean_return=Decimal(str(item["mean_return"])),
        variant=variant.name,
    )


def _evaluate_partition(
    cache: Mapping[str, Any],
    *,
    start: date,
    end: date,
) -> tuple[dict[str, tuple[Trade, ...]], list[dict[str, str]]]:
    option_rows = cache["option"]["bars"]
    variant_lookup = {variant.name: variant for variant in VARIANTS}
    contract_lookup = {
        item.symbol: item for item in (_contract_object(raw) for raw in cache["contracts"])
    }
    rows_by_variant: dict[str, list[Trade]] = {variant.name: [] for variant in VARIANTS}
    exclusions: list[dict[str, str]] = []
    for item in cache["selections"]:
        session = date.fromisoformat(str(item["session"]))
        if not start <= session <= end:
            continue
        name = str(item["variant"])
        signal = _signal_from_selection(item)
        try:
            frames = _option_frames(option_rows, str(item["long_symbol"]), str(item["short_symbol"]), session)
            variant = variant_lookup[name]
            trade = simulate_trade(
                signal,
                contract_lookup[str(item["long_symbol"])],
                contract_lookup[str(item["short_symbol"])],
                frames,
                hold_bars=variant.hold_bars,
                costs=COSTS,
                exit_mode=variant.exit_mode,
            )
        except (DataExclusion, KeyError, ValueError) as exc:
            exclusions.append(
                {"stage": "execution", "session": session.isoformat(), "variant": name, "reason": str(exc)}
            )
            continue
        rows_by_variant[name].append(trade)
    return (
        {name: enforce_non_overlapping(rows) for name, rows in rows_by_variant.items()},
        exclusions,
    )


def _metric_dict(metrics: Metrics) -> dict[str, Any]:
    return asdict(metrics)


def _scored(rows: Mapping[str, Sequence[Trade]]) -> dict[str, tuple[ScoredTrade, ...]]:
    return {
        name: tuple(ScoredTrade(item.session, item.return_r, item.net_pnl) for item in values)
        for name, values in rows.items()
    }


def evaluate(cache: Mapping[str, Any]) -> dict[str, Any]:
    stock = _stock_objects(cache["stock"]["bars"])
    sessions = tuple(sorted({bar.timestamp.astimezone(ET).date() for bar in stock if bar.symbol == "QQQ"}))
    folds = development_folds(sessions)
    development_rows, development_exclusions = _evaluate_partition(
        cache, start=START.date(), end=DEVELOPMENT_END
    )
    scored_development = _scored(development_rows)
    eligible_3r = {name: rows for name, rows in scored_development.items() if name.endswith("_3r")}
    fold_results: list[dict[str, Any]] = []
    rolling_rows: list[Trade] = []
    for number, fold in enumerate(folds, start=1):
        selected = select_on_training(
            eligible_3r, fold.training_dates, minimum_samples=8
        )
        validation_rows = tuple(
            item for item in development_rows.get(selected or "", ()) if item.session in set(fold.validation_dates)
        )
        rolling_rows.extend(validation_rows)
        fold_results.append(
            {
                "fold": number,
                "training": {"start": fold.training_start, "end": fold.training_end, "sessions": len(fold.training_dates)},
                "validation": {"start": fold.validation_start, "end": fold.validation_end, "sessions": len(fold.validation_dates)},
                "selected_variant": selected,
                "validation_metrics": _metric_dict(summarize(validation_rows)),
            }
        )
    frozen = freeze_candidate(eligible_3r, folds, minimum_samples=8)
    selected_name = frozen["selected_variant"]
    selected_validation = tuple(
        item
        for item in development_rows.get(selected_name or "", ())
        if any(item.session in set(fold.validation_dates) for fold in folds)
    )
    positive_months = sum(
        summarize(tuple(item for item in selected_validation if item.session.month == month)).net_pnl > 0
        for month in (5, 6, 7)
    ) if selected_name else 0
    development_robust = bool(
        selected_name
        and frozen["validation_metrics"].expectancy_r > 0
        and positive_months >= 2
    )

    # This is the sole holdout evaluation call and occurs only after the candidate is frozen.
    holdout_rows, holdout_exclusions = _evaluate_partition(
        cache, start=HOLDOUT_START, end=HOLDOUT_END
    )
    selected_holdout = tuple(holdout_rows.get(selected_name or "", ()))
    rolling_rows.extend(selected_holdout)
    rolling_metrics = summarize(rolling_rows)
    holdout_metrics = summarize(selected_holdout)
    selected_variant = next((item for item in VARIANTS if item.name == selected_name), None)
    target_stop_ratio = Decimal(3) if selected_variant and selected_variant.exit_mode == "target_stop_3r" else Decimal(0)
    promotion = bool(
        development_robust
        and holdout_metrics.sample_count >= 5
        and holdout_metrics.net_pnl > 0
        and target_stop_ratio >= 3
        and rolling_metrics.profit_factor >= 3
    )
    variant_results: dict[str, Any] = {}
    exclusion_counter = Counter(
        (item.get("variant", "unknown"), item.get("reason", "unknown"))
        for item in (*development_exclusions, *holdout_exclusions)
    )
    for variant in VARIANTS:
        dev = development_rows[variant.name]
        oos = holdout_rows[variant.name]
        variant_results[variant.name] = {
            "parameters": asdict(variant),
            "development": _metric_dict(summarize(dev)),
            "untouched_oos_sensitivity_diagnostic": _metric_dict(summarize(oos)),
            "untouched_oos_trades": [asdict(item) for item in oos],
            "exclusions": {
                reason: count for (name, reason), count in exclusion_counter.items() if name == variant.name
            },
        }
    result = {
        "schema_version": "afterimage-cross-asset-backtest-v1",
        "strategy_family": "cross-asset breadth-confirmed QQQ/IWM relative-strength rotation via debit verticals",
        "data": {
            "source": cache["source"],
            "cache_content_hash": cache["content_hash"],
            "stock_feed": cache["stock"]["feed"],
            "stock_adjustment": cache["stock"]["adjustment"],
            "timeframe": "15Min",
            "sessions": len(sessions),
            "development": {"start": START.date(), "end": DEVELOPMENT_END},
            "untouched_holdout": {"start": HOLDOUT_START, "end": HOLDOUT_END, "evaluations": 1},
        },
        "method": {
            "signal_known_at": "10:30 America/New_York after 10:15 stock bar completes",
            "entry": "first synchronized option bar beginning at/after signal completion",
            "entry_fill": "long high - short low + $0.03 slippage per leg",
            "exit_fill": "long low - short high - $0.03 slippage per leg; 3R targets require adverse bound",
            "fees": "$0.65 per contract per side; $2.60 round trip",
            "selection": "3R variants only; expanding Jan-Apr/May/Jun training, next-month validation, pooled May-Jul freeze",
            "max_positions": 1,
        },
        "variants": variant_results,
        "walk_forward_folds": fold_results,
        "frozen_candidate": {
            "variant": selected_name,
            "frozen_before_holdout": True,
            "selection_observed_partitions": frozen["observed_partitions"],
            "pooled_validation": _metric_dict(frozen["validation_metrics"]),
            "positive_validation_months": positive_months,
            "development_robust": development_robust,
            "operational_target_to_stop": target_stop_ratio,
        },
        "rolling_oos": {
            "scope": "selected next-month validation trades plus frozen untouched final holdout",
            "metrics": _metric_dict(rolling_metrics),
            "profit_factor_target": Decimal(3),
        },
        "untouched_oos": {
            "variant": selected_name,
            "metrics": _metric_dict(holdout_metrics),
            "trades": [asdict(item) for item in selected_holdout],
        },
        "decision": {
            "recommendation": "PROMOTE_TO_PARENT_REVIEW" if promotion else "REJECT",
            "criteria": {
                "development_robust": development_robust,
                "minimum_holdout_samples_5": holdout_metrics.sample_count >= 5,
                "positive_holdout_net_pnl": holdout_metrics.net_pnl > 0,
                "operational_target_to_stop_at_least_3": target_stop_ratio >= 3,
                "rolling_oos_profit_factor_at_least_3": rolling_metrics.profit_factor >= 3,
            },
        },
        "limitations": [
            "Alpaca option trade bars are not contemporaneous NBBO quotes; paired-leg extrema are deliberately adverse but not executable quote replay.",
            "IEX stock bars are not the full SIP and can differ from consolidated prices.",
            "Historical contract discovery depends on Alpaca's retained inactive-contract catalog.",
            "The final holdout is short and contains one market regime; confidence intervals remain wide.",
            "A 3R target can be skipped when it exceeds the $5 vertical's achievable value.",
        ],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _fmt_metric(value: Any, places: int = 2) -> str:
    decimal = Decimal(str(value))
    return f"{decimal:.{places}f}" if decimal.is_finite() else str(decimal)


def render_report(result: Mapping[str, Any]) -> str:
    oos = result["untouched_oos"]["metrics"]
    rolling = result["rolling_oos"]["metrics"]
    frozen = result["frozen_candidate"]
    lines = [
        "# Cross-asset breadth rotation option candidate",
        "",
        "## Verdict",
        "",
        f"**{result['decision']['recommendation']}**. Frozen variant `{frozen['variant']}` produced "
        f"{oos['sample_count']} untouched OOS trades, ${oos['net_pnl']} net P&L, "
        f"{_fmt_metric(oos['expectancy_r'], 4)} expectancy/R, {_fmt_metric(Decimal(str(oos['hit_rate'])) * 100, 1)}% hit rate, "
        f"${oos['max_drawdown']} max drawdown, and {_fmt_metric(oos['profit_factor'])} profit factor.",
        "",
        f"Aggregate rolling-OOS profit factor was **{_fmt_metric(rolling['profit_factor'])}** versus the 3.00 target. "
        f"The operational target:stop is **{frozen['operational_target_to_stop']}:1** after modeled fees and slippage.",
        "",
        "## Expanding walk-forward selection",
        "",
        "| Fold | Training | Validation | Selected | n | Net P&L | Exp/R | PF | Hit | Max DD |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for fold in result["walk_forward_folds"]:
        stats = fold["validation_metrics"]
        lines.append(
            f"| {fold['fold']} | {fold['training']['start']}..{fold['training']['end']} | "
            f"{fold['validation']['start']}..{fold['validation']['end']} | {fold['selected_variant']} | "
            f"{stats['sample_count']} | ${stats['net_pnl']} | {_fmt_metric(stats['expectancy_r'], 4)} | "
            f"{_fmt_metric(stats['profit_factor'])} | {_fmt_metric(Decimal(str(stats['hit_rate'])) * 100, 1)}% | ${stats['max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## Every predeclared variant",
            "",
            "The per-variant holdout rows were computed together in the sole holdout pass after the winner was frozen; only the frozen row is selection OOS, while the rest are sensitivity diagnostics.",
            "",
            "| Variant | Exit | Dev n | Dev P&L | OOS n | OOS P&L | OOS Exp/R | OOS PF | OOS hit | OOS max DD |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, row in result["variants"].items():
        dev = row["development"]
        stats = row["untouched_oos_sensitivity_diagnostic"]
        lines.append(
            f"| `{name}` | {row['parameters']['exit_mode']} | {dev['sample_count']} | ${dev['net_pnl']} | "
            f"{stats['sample_count']} | ${stats['net_pnl']} | {_fmt_metric(stats['expectancy_r'], 4)} | "
            f"{_fmt_metric(stats['profit_factor'])} | {_fmt_metric(Decimal(str(stats['hit_rate'])) * 100, 1)}% | ${stats['max_drawdown']} |"
        )
    lines.extend(
        [
            "",
            "## Production integration contract",
            "",
            "- Input synchronized completed 15-minute IEX bars for QQQ, IWM, XLK, XLF, XLE, XLV, and XLY plus SPY daily closes; evaluate once at 10:30 New York time.",
            "- Require the frozen breadth/magnitude/regime rules; select QQQ/IWM from completed-bar relative strength only.",
            "- Resolve the earliest listed 3–9 DTE exact $5 debit vertical from the live contract catalog. Reject missing legs, stale quotes, non-positive debit, or an unattainable 3R target.",
            "- Emit one-lot `order_class=mleg`, limit debit, buy-to-open long leg and sell-to-open short leg. Enforce global max one open strategy position.",
            "- Attach the precomputed net-of-cost 3R target and 1R stop to lifecycle state; stop evaluation precedes target evaluation within a bar. Time out after the frozen hold count and close both legs as one MLEG.",
            "- Route only through AFTERIMAGE warrant, risk-governor, serialized executor, lifecycle reconciliation, and evidence-vault gates. The included artifact is `--dry-run` only and submits nothing.",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in result["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def build_attempt_ledger(result: Mapping[str, Any]) -> dict[str, Any]:
    entry = {
        "attempt_id": "cross_asset_breadth_rotation_v1",
        "status": "evaluated",
        "predeclared_family": [asdict(item) for item in VARIANTS],
        "development_window": {"start": START.date(), "end": DEVELOPMENT_END},
        "revealed_holdout_window": {"start": HOLDOUT_START, "end": HOLDOUT_END, "may_be_reused_as_untouched": False},
        "selected_variant": result["frozen_candidate"]["variant"],
        "untouched_oos_metrics": result["untouched_oos"]["metrics"],
        "rolling_oos_metrics": result["rolling_oos"]["metrics"],
        "recommendation": result["decision"]["recommendation"],
        "result_hash": result["result_hash"],
    }
    body = {
        "schema_version": "afterimage-strategy-attempt-ledger-v1",
        "rule": "A revealed date range can never be relabeled untouched by a later attempt.",
        "attempts": [entry],
    }
    return {**body, "ledger_hash": canonical_hash(body)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="refresh authenticated Alpaca caches")
    parser.add_argument("--alpaca-cli", type=Path, default=REPO / ".tools" / "bin" / "alpaca")
    parser.add_argument("--profile", default=PROFILE)
    arguments = parser.parse_args()
    if arguments.fetch or not DATA_CACHE.exists():
        cache = acquire(executable=arguments.alpaca_cli, profile=arguments.profile, output=DATA_CACHE)
    else:
        cache = json.loads(DATA_CACHE.read_text(encoding="utf-8"))
    result = evaluate(cache)
    _write_json(BACKTEST, result)
    _write_json(ATTEMPT_LEDGER, build_attempt_ledger(result))
    REPORT.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"decision": result["decision"], "untouched_oos": result["untouched_oos"]["metrics"]}, default=_json_default, sort_keys=True))


if __name__ == "__main__":
    main()
