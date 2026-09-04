"""Run and preserve three materially distinct event/flow strategy attempts."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .engine import Bar, Costs, Signal, StrategyParameters, Trade, simulate_trade
from .ledger import append_attempt, verify_ledger
from .market_data import aggregate_daily, parse_cache, session_close
from .metrics import Metrics, summarize_returns
from .strategies import (
    CompressionVariant,
    DailyFeature,
    ShockVariant,
    VolumeBreakoutVariant,
    choose_compression_signal,
    choose_shock_signal,
    choose_volume_breakout_signal,
)
from .walkforward import select_for_fold

HERE = Path(__file__).resolve().parent
CACHE = HERE / "data" / "alpaca_15min.json"
RESULTS = HERE / "results"
LEDGER = RESULTS / "attempt-ledger.json"
REPORT = HERE / "REPORT.md"
DRY_RUN = RESULTS / "alpaca-equity-dry-run.json"
UNIVERSE = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "TLT", "GLD")
BASE_COSTS = Costs(Decimal(1), Decimal("0.005"))
STRESSED_COSTS = Costs(Decimal("1.5"), Decimal("0.0075"))


def _decimal_mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def build_features(daily: Mapping[str, Sequence[Bar]]) -> Mapping[date, tuple[DailyFeature, ...]]:
    grouped: dict[date, list[DailyFeature]] = defaultdict(list)
    for symbol, rows in daily.items():
        for index in range(110, len(rows) - 1):
            current = rows[index]
            true_ranges = []
            for cursor in range(index - 13, index + 1):
                previous_close = rows[cursor - 1].close
                item = rows[cursor]
                true_ranges.append(
                    max(
                        item.high - item.low,
                        abs(item.high - previous_close),
                        abs(item.low - previous_close),
                    )
                )
            atr = _decimal_mean(true_ranges)
            sma50 = _decimal_mean(tuple(item.close for item in rows[index - 49 : index + 1]))
            sma100 = _decimal_mean(tuple(item.close for item in rows[index - 99 : index + 1]))
            trend = (
                1
                if current.close > sma100 and sma50 > sma100
                else -1
                if current.close < sma100 and sma50 < sma100
                else 0
            )
            location = (
                (current.close - current.low) / (current.high - current.low)
                if current.high > current.low
                else Decimal("0.5")
            )
            volume_average = _decimal_mean(
                tuple(Decimal(item.volume) for item in rows[index - 20 : index])
            )
            two_return = (current.close / rows[index - 2].close - 1) / (atr / current.close)
            three_return = (current.close / rows[index - 3].close - 1) / (atr / current.close)
            if trend == 1:
                sequence = current.close < rows[index - 1].close < rows[index - 2].close
            elif trend == -1:
                sequence = current.close > rows[index - 1].close > rows[index - 2].close
            else:
                sequence = False
            breakouts = {
                lookback: (
                    current.close >= max(item.high for item in rows[index - lookback : index])
                    if trend == 1
                    else current.close <= min(item.low for item in rows[index - lookback : index])
                    if trend == -1
                    else False
                )
                for lookback in (5, 10, 20, 40)
            }
            grouped[current.timestamp.date()].append(
                DailyFeature(
                    session=current.timestamp.date(),
                    symbol=symbol,
                    completed_at=session_close(current),
                    trend=trend,
                    atr_fraction=atr / current.close,
                    two_day_atr_return=two_return,
                    three_day_atr_return=three_return,
                    close_location=location,
                    consecutive_countertrend=sequence,
                    compression_ratio=(current.high - current.low) / atr,
                    inside_day=(
                        current.high < rows[index - 1].high and current.low > rows[index - 1].low
                    ),
                    volume_ratio=Decimal(current.volume) / volume_average,
                    breakouts=breakouts,
                )
            )
    return {session: tuple(items) for session, items in sorted(grouped.items())}


def _stop_atr(variant: object) -> Decimal:
    return variant.stop_atr


def _hold_days(variant: object) -> int:
    return variant.hold_days


def simulate_variant(
    variant: ShockVariant | VolumeBreakoutVariant | CompressionVariant,
    features: Mapping[date, Sequence[DailyFeature]],
    daily: Mapping[str, Sequence[Bar]],
    chooser: Callable[[Sequence[DailyFeature], Any], Signal | None],
    costs: Costs,
) -> tuple[Trade, ...]:
    result: list[Trade] = []
    unavailable_until: datetime | None = None
    for items in features.values():
        signal = chooser(items, variant)
        if signal is None or (
            unavailable_until is not None and signal.completed_at <= unavailable_until
        ):
            continue
        selected = next(item for item in items if item.symbol == signal.symbol)
        parameters = StrategyParameters(
            stop_fraction=max(
                Decimal("0.001"), min(Decimal("0.03"), selected.atr_fraction * _stop_atr(variant))
            ),
            max_holding_bars=_hold_days(variant),
        )
        try:
            trade = simulate_trade(signal, daily[signal.symbol], parameters, costs)
        except ValueError:
            continue
        result.append(trade)
        unavailable_until = trade.exit_at
    return tuple(result)


def _months() -> tuple[tuple[int, int], ...]:
    values = []
    year, month = 2025, 1
    while (year, month) <= (2026, 9):
        values.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return tuple(values)


def walk_forward(
    base_by_variant: Mapping[str, Sequence[Trade]],
    scored_by_variant: Mapping[str, Sequence[Trade]],
) -> tuple[tuple[Trade, ...], list[dict[str, Any]]]:
    selected_rows: list[Trade] = []
    folds: list[dict[str, Any]] = []
    unavailable_until: datetime | None = None
    for year, month in _months():
        fold_start = datetime(year, month, 1, tzinfo=UTC)
        selected = select_for_fold(base_by_variant, fold_start, minimum_samples=12)
        candidates = tuple(
            item
            for item in scored_by_variant.get(selected or "", ())
            if (item.entry_at.year, item.entry_at.month) == (year, month)
            and (unavailable_until is None or item.entry_at > unavailable_until)
        )
        selected_rows.extend(candidates)
        if candidates:
            unavailable_until = candidates[-1].exit_at
        fold_metrics = _metrics(candidates)
        folds.append(
            {
                "month": f"{year:04d}-{month:02d}",
                "selected_variant": selected,
                "trade_count": len(candidates),
                "net_r": fold_metrics.net_r,
            }
        )
    return tuple(selected_rows), folds


def _metrics(trades: Sequence[Trade]) -> Metrics:
    return summarize_returns((item.entry_at.date(), item.symbol, item.return_r) for item in trades)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _hash(value: Any) -> str:
    raw = json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _variant_payload(variant: object) -> dict[str, Any]:
    return _jsonable(asdict(variant))


def _admission(
    metrics: Metrics,
    stress: Metrics,
    trades: Sequence[Trade],
    neighbor_fraction: Decimal,
) -> dict[str, Any]:
    minimum_ratio = min((item.target_to_stop for item in trades), default=Decimal(0))
    checks = {
        "after_cost_target_to_stop_gte_3": minimum_ratio >= Decimal(3),
        "profit_factor_gte_2": metrics.profit_factor >= Decimal(2),
        "expectancy_gte_0_25r": metrics.expectancy_r >= Decimal("0.25"),
        "sample_count_gte_30": metrics.sample_count >= 30,
        "max_drawdown_lte_6r": metrics.max_drawdown_r <= Decimal(6),
        "positive_two_underlyings": metrics.positive_underlyings >= 2,
        "positive_month_fraction_gte_60pct": metrics.positive_month_fraction >= Decimal("0.60"),
        "positive_at_1_5x_costs": stress.net_r > 0,
        "positive_neighbor_fraction_gte_60pct": neighbor_fraction >= Decimal("0.60"),
        "largest_win_lte_25pct_gross": metrics.largest_win_fraction <= Decimal("0.25"),
    }
    return {
        "admitted": all(checks.values()),
        "checks": checks,
        "minimum_target_to_stop": minimum_ratio,
    }


def evaluate_family(
    *,
    attempt_id: str,
    family: str,
    variants: Sequence[ShockVariant | VolumeBreakoutVariant | CompressionVariant],
    chooser: Callable[[Sequence[DailyFeature], Any], Signal | None],
    features: Mapping[date, Sequence[DailyFeature]],
    daily: Mapping[str, Sequence[Bar]],
    provenance: Mapping[str, object],
) -> dict[str, Any]:
    base = {
        variant.name: simulate_variant(variant, features, daily, chooser, BASE_COSTS)
        for variant in variants
    }
    stressed = {
        variant.name: simulate_variant(variant, features, daily, chooser, STRESSED_COSTS)
        for variant in variants
    }
    rolling, folds = walk_forward(base, base)
    rolling_stress, _ = walk_forward(base, stressed)
    metrics = _metrics(rolling)
    stress_metrics = _metrics(rolling_stress)
    fixed_window = {
        name: tuple(item for item in trades if item.entry_at.year >= 2025)
        for name, trades in base.items()
    }
    positive_neighbors = sum(_metrics(trades).net_r > 0 for trades in fixed_window.values())
    neighbor_fraction = Decimal(positive_neighbors) / Decimal(len(variants) or 1)
    ranked = sorted(
        (
            {
                "variant": name,
                "parameters": _variant_payload(
                    next(item for item in variants if item.name == name)
                ),
                "metrics_2025_2026": asdict(_metrics(trades)),
            }
            for name, trades in fixed_window.items()
        ),
        key=lambda item: (
            item["metrics_2025_2026"]["expectancy_r"],
            item["metrics_2025_2026"]["profit_factor"],
        ),
        reverse=True,
    )
    admission = _admission(metrics, stress_metrics, rolling, neighbor_fraction)
    result: dict[str, Any] = {
        "schema_version": "afterimage-event-flow-attempt-v1",
        "attempt_id": attempt_id,
        "family": family,
        "data": {
            "source": provenance["source"],
            "content_hash": provenance["content_hash"],
            "feed": provenance["feed"],
            "timeframe": provenance["timeframe"],
            "bounds": provenance["bounds"],
            "symbols": list(UNIVERSE),
        },
        "method": {
            "selection": "monthly expanding walk-forward; variant selected on completed prior trades only",
            "rolling_oos_months": [f"{year:04d}-{month:02d}" for year, month in _months()],
            "entry": "next daily regular-session open after a completed signal day",
            "execution": "split-adjusted Alpaca IEX OHLC; stop-first; one serialized position",
            "costs": "1 bp adverse slippage plus $0.005/share/side; stress is 1.5x",
        },
        "variant_count": len(variants),
        "rolling_oos": {
            "metrics": asdict(metrics),
            "stress_1_5x_metrics": asdict(stress_metrics),
            "folds": folds,
            "trades": [asdict(item) for item in rolling],
        },
        "neighborhood": {
            "positive_fraction_2025_2026": neighbor_fraction,
            "positive_count": positive_neighbors,
            "total": len(variants),
        },
        "leaderboard": ranked[:30],
        "admission": admission,
        "decision": "ADMIT" if admission["admitted"] else "REJECT",
        "limitations": [
            "IEX is not consolidated SIP and historical OHLC has no intrabar ordering.",
            "The 2025-2026 window is rolling pseudo-OOS, not a never-observed external future.",
            "Direct ETF-share fills do not model short-locate availability or market impact.",
            "A large neighboring grid raises multiple-testing risk; fold selection is past-only but cannot erase that risk.",
        ],
    }
    result["result_hash"] = _hash(result)
    return _jsonable(result)


def _shock_variants() -> tuple[ShockVariant, ...]:
    values = []
    for lookback in (2, 3):
        for shock in (Decimal("0.5"), Decimal("0.75"), Decimal(1)):
            for location in (Decimal("0.25"), Decimal(1)):
                for stop in (Decimal(1), Decimal("1.25")):
                    for hold in (5, 10):
                        values.append(
                            ShockVariant(
                                f"shock_l{lookback}_z{shock}_c{location}_s{stop}_h{hold}",
                                lookback,
                                shock,
                                location,
                                False,
                                True,
                                stop,
                                hold,
                            )
                        )
    return tuple(values)


def _breakout_variants() -> tuple[VolumeBreakoutVariant, ...]:
    return tuple(
        VolumeBreakoutVariant(
            f"breakout_l{lookback}_v{volume}_s{stop}_h{hold}",
            lookback,
            volume,
            stop,
            hold,
        )
        for lookback in (5, 10, 20)
        for volume in (Decimal("1.2"), Decimal("1.5"))
        for stop in (Decimal("0.5"), Decimal("0.75"), Decimal(1))
        for hold in (10, 15, 20)
    )


def _compression_variants() -> tuple[CompressionVariant, ...]:
    return tuple(
        CompressionVariant(
            f"compression_r{maximum}_c{location}_i{int(inside)}_s{stop}_h{hold}",
            maximum,
            location,
            inside,
            stop,
            hold,
        )
        for maximum in (Decimal("0.6"), Decimal("0.8"), Decimal(1))
        for location in (Decimal("0.65"), Decimal("0.75"))
        for inside in (False, True)
        for stop in (Decimal("0.75"), Decimal(1))
        for hold in (10, 15)
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_result(result: Mapping[str, Any]) -> None:
    if LEDGER.exists():
        if not verify_ledger(LEDGER):
            raise ValueError("LEDGER_HASH_INVALID")
        payload = json.loads(LEDGER.read_text(encoding="utf-8"))
        if any(item.get("attempt_id") == result["attempt_id"] for item in payload["attempts"]):
            return
    append_attempt(
        LEDGER,
        {
            "attempt_id": result["attempt_id"],
            "family": result["family"],
            "decision": result["decision"],
            "result_hash": result["result_hash"],
            "rolling_oos_metrics": result["rolling_oos"]["metrics"],
            "admission": result["admission"],
        },
    )


def _dry_run(winner: Mapping[str, Any]) -> dict[str, Any]:
    trades = winner["rolling_oos"]["trades"]
    if not trades:
        return {"submit": False, "reason": "NO_ROLLING_OOS_TRADE"}
    trade = trades[-1]
    side = "buy" if int(trade["direction"]) == 1 else "sell"
    return {
        "schema_version": "afterimage-alpaca-equity-bracket-dry-run-v1",
        "submit": False,
        "transport": "official Alpaca Trading API via authenticated CLI profile afterimage-paper",
        "endpoint": "POST https://paper-api.alpaca.markets/v2/orders",
        "historical_replay_at": trade["entry_at"],
        "attempt_id": winner["attempt_id"],
        "variant": trade["variant"],
        "payload": {
            "symbol": trade["symbol"],
            "qty": str(trade["shares"]),
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "order_class": "bracket",
            "take_profit": {"limit_price": str(trade["target_price"])},
            "stop_loss": {"stop_price": str(trade["stop_price"])},
            "client_order_id": f"afterimage-{winner['attempt_id']}-dry-run",
        },
    }


def _report(results: Sequence[Mapping[str, Any]], winner: Mapping[str, Any]) -> str:
    lines = [
        "# Event/flow strategy-search report",
        "",
        "Real authenticated Alpaca data was used. No order was submitted.",
        "",
        "| Attempt | Decision | Trades | PF | Expectancy | Max DD | Positive months | Stress net |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        metrics = result["rolling_oos"]["metrics"]
        stress = result["rolling_oos"]["stress_1_5x_metrics"]
        lines.append(
            f"| {result['family']} | **{result['decision']}** | {metrics['sample_count']} | "
            f"{Decimal(metrics['profit_factor']):.2f} | {Decimal(metrics['expectancy_r']):+.3f}R | "
            f"{Decimal(metrics['max_drawdown_r']):.2f}R | {Decimal(metrics['positive_month_fraction']):.0%} | "
            f"{Decimal(stress['net_r']):+.2f}R |"
        )
    lines.extend(
        [
            "",
            f"## Ranked winner: {winner['family']}",
            "",
            f"Decision: **{winner['decision']}**. A rank winner is not called admitted unless every floor passes.",
            "",
            (
                "The production concept is a monthly past-only selector over a deliberately small "
                "neighboring grid. Signals use completed daily bars and execute at the next regular-session "
                "open with a cent-rounded after-cost 3R target and 1R stop."
            ),
            "",
            "## Data provenance",
            "",
            f"- Source: {winner['data']['source']}",
            f"- Content hash: `{winner['data']['content_hash']}`",
            f"- Bounds: {winner['data']['bounds']}",
            f"- Universe: {', '.join(winner['data']['symbols'])}",
            "",
            "## Honest limitations",
            "",
            *[f"- {item}" for item in winner["limitations"]],
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parsed, provenance = parse_cache(CACHE)
    daily = {symbol: aggregate_daily(parsed[symbol]) for symbol in UNIVERSE}
    features = build_features(daily)
    specs = (
        (
            "event_flow_01_compression",
            "trend compression release",
            _compression_variants(),
            choose_compression_signal,
        ),
        (
            "event_flow_02_volume_breakout",
            "volume-confirmed range breakout",
            _breakout_variants(),
            choose_volume_breakout_signal,
        ),
        (
            "event_flow_03_shock_reversal",
            "trend-aligned multi-day shock reversal",
            _shock_variants(),
            choose_shock_signal,
        ),
    )
    results = []
    for attempt_id, family, variants, chooser in specs:
        result = evaluate_family(
            attempt_id=attempt_id,
            family=family,
            variants=variants,
            chooser=chooser,
            features=features,
            daily=daily,
            provenance=provenance,
        )
        _write_json(RESULTS / f"{attempt_id}.json", result)
        _append_result(result)
        results.append(result)
    winner = max(
        results,
        key=lambda item: (
            item["decision"] == "ADMIT",
            Decimal(item["rolling_oos"]["metrics"]["expectancy_r"]),
            Decimal(item["rolling_oos"]["metrics"]["profit_factor"]),
        ),
    )
    _write_json(RESULTS / "winner.json", winner)
    _write_json(DRY_RUN, _dry_run(winner))
    REPORT.write_text(_report(results, winner), encoding="utf-8")
    print(
        json.dumps(
            {
                "winner": winner["family"],
                "decision": winner["decision"],
                "metrics": winner["rolling_oos"]["metrics"],
                "attempts": [
                    {
                        "id": item["attempt_id"],
                        "decision": item["decision"],
                        "metrics": item["rolling_oos"]["metrics"],
                    }
                    for item in results
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
