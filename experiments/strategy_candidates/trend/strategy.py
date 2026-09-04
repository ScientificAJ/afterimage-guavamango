from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float


@dataclass(frozen=True)
class OptionBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class StrategyParams:
    family: str
    signal_minutes: int
    drive_threshold: float
    efficiency_threshold: float
    rel_volume_threshold: float
    breakout_buffer: float
    stop_fraction: float
    target_fraction: float
    hold_minutes: int


@dataclass(frozen=True)
class Signal:
    session_date: date
    direction: str
    signal_at: datetime
    entry_at: datetime
    signal_price: float
    entry_price: float
    signal_bar_count: int
    features: dict[str, float]


@dataclass(frozen=True)
class UnderlyingTrade:
    session_date: date
    direction: str
    signal_at: datetime
    entry_at: datetime
    exit_at: datetime
    entry_price: float
    exit_price: float
    exit_reason: str
    net_pnl_dollars: float
    return_r: float


@dataclass(frozen=True)
class OptionTrade:
    entry_at: datetime
    exit_at: datetime
    entry_debit: float
    exit_credit: float
    net_pnl_dollars: float
    risk_dollars: float
    return_r: float
    exit_reason: str
    synchronized_bars: int


def select_contract_pair(
    contracts: list[dict[str, Any]], *, signal_price: float, direction: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    option_type = "call" if direction == "bullish" else "put" if direction == "bearish" else ""
    if not option_type:
        raise ValueError("direction must be bullish or bearish")
    parsed: list[tuple[date, float, dict[str, Any]]] = []
    for contract in contracts:
        try:
            if str(contract.get("type", "")).lower() != option_type:
                continue
            expiration = date.fromisoformat(str(contract["expiration_date"]))
            strike = float(contract["strike_price"])
            if not math.isfinite(strike) or not str(contract["symbol"]):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        parsed.append((expiration, strike, contract))
    for expiration in sorted({item[0] for item in parsed}):
        same_expiry = [item for item in parsed if item[0] == expiration]
        long_item = min(same_expiry, key=lambda item: (abs(item[1] - signal_price), item[1]))
        if option_type == "call":
            shorts = [item for item in same_expiry if 5.0 <= item[1] - long_item[1] <= 10.0]
        else:
            shorts = [item for item in same_expiry if 5.0 <= long_item[1] - item[1] <= 10.0]
        if shorts:
            short_item = min(
                shorts, key=lambda item: (abs(abs(item[1] - long_item[1]) - 6.0), item[1])
            )
            return long_item[2], short_item[2]
    raise ValueError("NO_DEFINED_RISK_VERTICAL_AVAILABLE")


def _minutes_after_open(bar: Bar) -> int:
    local = bar.timestamp.astimezone(ET)
    return (local.hour * 60 + local.minute) - (9 * 60 + 30)


def _weighted_vwap(bars: list[Bar]) -> float:
    volume = sum(bar.volume for bar in bars)
    if volume <= 0:
        return bars[-1].vwap
    return sum(bar.vwap * bar.volume for bar in bars) / volume


def _path_efficiency(bars: list[Bar]) -> float:
    path = [bars[0].open, *(bar.close for bar in bars)]
    distance = sum(abs(right - left) for left, right in pairwise(path))
    return abs(path[-1] - path[0]) / distance if distance else 0.0


def _relative_volume(bars: list[Bar], prior_opening_volumes: list[list[float]]) -> float:
    current = sum(bar.volume for bar in bars)
    comparables = [sum(row[: len(bars)]) for row in prior_opening_volumes if len(row) >= len(bars)]
    baseline = statistics.median(comparables[-20:]) if comparables else 0.0
    return current / baseline if baseline > 0 else (1.0 if current > 0 else 0.0)


def generate_session_signal(
    session_bars: list[Bar],
    prior_opening_volumes: list[list[float]],
    params: StrategyParams,
) -> Signal | None:
    bars = sorted(session_bars, key=lambda item: item.timestamp)
    signal_bars = [bar for bar in bars if 0 <= _minutes_after_open(bar) < params.signal_minutes]
    entry_candidates = [bar for bar in bars if _minutes_after_open(bar) == params.signal_minutes]
    if len(signal_bars) != params.signal_minutes // 5 or not entry_candidates:
        return None
    entry_bar = entry_candidates[0]
    session_vwap = _weighted_vwap(signal_bars)
    drive = signal_bars[-1].close / signal_bars[0].open - 1.0
    efficiency = _path_efficiency(signal_bars)
    relative_volume = _relative_volume(signal_bars, prior_opening_volumes)
    if efficiency < params.efficiency_threshold or relative_volume < params.rel_volume_threshold:
        return None

    direction: str | None = None
    if params.family == "opening_drive_vwap":
        if drive >= params.drive_threshold and signal_bars[-1].close > session_vwap:
            direction = "bullish"
        elif drive <= -params.drive_threshold and signal_bars[-1].close < session_vwap:
            direction = "bearish"
    elif params.family == "opening_range_breakout":
        opening = signal_bars[:6]
        opening_high = max(bar.high for bar in opening)
        opening_low = min(bar.low for bar in opening)
        close = signal_bars[-1].close
        if (
            drive >= params.drive_threshold
            and close > opening_high * (1.0 + params.breakout_buffer)
            and close > session_vwap
        ):
            direction = "bullish"
        elif (
            drive <= -params.drive_threshold
            and close < opening_low * (1.0 - params.breakout_buffer)
            and close < session_vwap
        ):
            direction = "bearish"
    elif params.family == "vwap_pullback_reclaim":
        opening = signal_bars[:6]
        follow = signal_bars[6:]
        if len(follow) < 2:
            return None
        opening_drive = opening[-1].close / opening[0].open - 1.0
        last, previous = follow[-1], follow[-2]
        if (
            opening_drive >= params.drive_threshold
            and min(bar.low for bar in follow) <= session_vwap * (1.0 + params.breakout_buffer)
            and last.close > session_vwap
            and last.close > previous.high
        ):
            direction = "bullish"
        elif (
            opening_drive <= -params.drive_threshold
            and max(bar.high for bar in follow) >= session_vwap * (1.0 - params.breakout_buffer)
            and last.close < session_vwap
            and last.close < previous.low
        ):
            direction = "bearish"
    else:
        raise ValueError(f"unknown family: {params.family}")
    if direction is None:
        return None
    signal_at = signal_bars[-1].timestamp + timedelta(minutes=5)
    return Signal(
        session_date=signal_at.astimezone(ET).date(),
        direction=direction,
        signal_at=signal_at,
        entry_at=entry_bar.timestamp + timedelta(minutes=5),
        signal_price=signal_bars[-1].close,
        entry_price=entry_bar.close,
        signal_bar_count=len(signal_bars),
        features={
            "drive_return": drive,
            "efficiency": efficiency,
            "relative_volume": relative_volume,
            "session_vwap": session_vwap,
        },
    )


def model_option_vertical(
    *,
    signal_at: datetime,
    long_symbol: str,
    short_symbol: str,
    bars: dict[str, list[OptionBar]],
    stop_fraction: float,
    target_fraction: float,
    hold_minutes: int,
    slippage_per_leg: float,
    fee_per_contract_side: float,
) -> OptionTrade:
    long_by_time = {bar.timestamp: bar for bar in bars.get(long_symbol, [])}
    short_by_time = {bar.timestamp: bar for bar in bars.get(short_symbol, [])}
    synchronized = sorted(
        timestamp
        for timestamp in set(long_by_time).intersection(short_by_time)
        if signal_at <= timestamp <= signal_at + timedelta(minutes=hold_minutes)
    )
    if not synchronized:
        raise ValueError("NO_SYNCHRONIZED_OPTION_BARS")
    entry_timestamp = synchronized[0]
    entry_debit = (
        long_by_time[entry_timestamp].close
        - short_by_time[entry_timestamp].close
        + 2 * slippage_per_leg
    )
    if entry_debit <= 0:
        raise ValueError("NON_POSITIVE_ENTRY_DEBIT")
    exit_timestamp = entry_timestamp
    exit_credit = entry_debit
    exit_reason = "time"
    price_pnl = 0.0
    for timestamp in synchronized[1:]:
        exit_credit = (
            long_by_time[timestamp].close - short_by_time[timestamp].close - 2 * slippage_per_leg
        )
        price_pnl = exit_credit - entry_debit
        exit_timestamp = timestamp
        if price_pnl <= -entry_debit * stop_fraction:
            exit_reason = "stop"
            break
        if price_pnl >= entry_debit * target_fraction:
            exit_reason = "target"
            break
    round_trip_fees = 4 * fee_per_contract_side
    net_pnl = price_pnl * 100.0 - round_trip_fees
    risk_dollars = entry_debit * stop_fraction * 100.0 + round_trip_fees
    return OptionTrade(
        entry_at=entry_timestamp + timedelta(minutes=5),
        exit_at=exit_timestamp + timedelta(minutes=5),
        entry_debit=round(entry_debit, 8),
        exit_credit=round(exit_credit, 8),
        net_pnl_dollars=round(net_pnl, 2),
        risk_dollars=round(risk_dollars, 2),
        return_r=net_pnl / risk_dollars,
        exit_reason=exit_reason,
        synchronized_bars=len(synchronized),
    )


async def validate_option_signals(gateway: Any, signals: list[dict[str, Any]]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    for signal in signals:
        try:
            session_date = date.fromisoformat(str(signal["session_date"]))
            signal_at = datetime.fromisoformat(str(signal["signal_at"]))
            direction = str(signal["direction"])
            signal_price = float(signal["signal_price"])
            option_type = "call" if direction == "bullish" else "put"
            contracts = await gateway.option_contracts(
                "SPY",
                expiration_date_gte=(session_date + timedelta(days=2)).isoformat(),
                expiration_date_lte=(session_date + timedelta(days=7)).isoformat(),
                strike_price_gte=str(signal_price - 12.0),
                strike_price_lte=str(signal_price + 12.0),
                type=option_type,
                status="inactive",
                limit=10000,
            )
            long_contract, short_contract = select_contract_pair(
                list(contracts), signal_price=signal_price, direction=direction
            )
            long_symbol = str(long_contract["symbol"])
            short_symbol = str(short_contract["symbol"])
            raw_bars = await gateway.option_bars(
                (long_symbol, short_symbol),
                signal_at,
                signal_at + timedelta(minutes=60),
                "5Min",
            )
            grouped: dict[str, list[OptionBar]] = {long_symbol: [], short_symbol: []}
            for raw in raw_bars:
                symbol = str(raw.get("symbol", ""))
                if symbol not in grouped:
                    continue
                grouped[symbol].append(
                    OptionBar(
                        timestamp=datetime.fromisoformat(str(raw["t"])),
                        open=float(raw["o"]),
                        high=float(raw["h"]),
                        low=float(raw["l"]),
                        close=float(raw["c"]),
                    )
                )
            trade = model_option_vertical(
                signal_at=signal_at,
                long_symbol=long_symbol,
                short_symbol=short_symbol,
                bars=grouped,
                stop_fraction=0.25,
                target_fraction=0.50,
                hold_minutes=60,
                slippage_per_leg=0.02,
                fee_per_contract_side=0.65,
            )
            trade_payload = asdict(trade)
            for key in ("entry_at", "exit_at"):
                trade_payload[key] = getattr(trade, key).isoformat().replace("+00:00", "Z")
            results.append(
                {
                    "session_date": session_date.isoformat(),
                    "direction": direction,
                    "signal_at": signal_at.isoformat().replace("+00:00", "Z"),
                    "signal_price": signal_price,
                    "long_symbol": long_symbol,
                    "short_symbol": short_symbol,
                    "expiration_date": str(long_contract["expiration_date"]),
                    **trade_payload,
                }
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
            exclusions.append(
                {
                    "session_date": str(signal.get("session_date", "unknown")),
                    "reason": str(exc) or type(exc).__name__,
                }
            )
    pnls = [float(result["net_pnl_dollars"]) for result in results]
    returns = [float(result["return_r"]) for result in results]
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return {
        "source": "Alpaca historical option trade bars via official CLI",
        "pricing_basis": "next synchronized 5-minute closes; no quote reconstruction",
        "contract_limitation": "inactive contract metadata queried after expiration; not a point-in-time chain snapshot",
        "slippage_per_leg_per_fill": 0.02,
        "fee_reserve_per_contract_side": 0.65,
        "requested_signals": len(signals),
        "validated_signals": len(results),
        "excluded_signals": len(exclusions),
        "coverage_rate": round(len(results) / len(signals), 6) if signals else 0.0,
        "sample_count": len(results),
        "net_pnl_dollars": round(sum(pnls), 2),
        "expectancy_r": round(statistics.mean(returns), 6) if returns else 0.0,
        "hit_rate": round(sum(value > 0 for value in pnls) / len(pnls), 6) if pnls else 0.0,
        "max_drawdown_dollars": round(drawdown, 2),
        "wins": sum(value > 0 for value in pnls),
        "losses": sum(value < 0 for value in pnls),
        "flats": sum(value == 0 for value in pnls),
        "results": results,
        "exclusions": exclusions,
    }


def _parse_records(records: list[dict[str, Any]]) -> dict[date, list[Bar]]:
    sessions: dict[date, list[Bar]] = {}
    for record in records:
        if record.get("kind") != "bar":
            continue
        timestamp = datetime.fromisoformat(str(record["timestamp"]))
        values = record["values"]
        bar = Bar(
            timestamp=timestamp,
            open=float(values["open"]),
            high=float(values["high"]),
            low=float(values["low"]),
            close=float(values["close"]),
            volume=float(values["volume"]),
            vwap=float(values.get("vwap", values["close"])),
        )
        local = timestamp.astimezone(ET)
        if time(9, 30) <= local.time() <= time(16, 0):
            sessions.setdefault(local.date(), []).append(bar)
    return {
        key: sorted(value, key=lambda item: item.timestamp)
        for key, value in sorted(sessions.items())
    }


def _default_variants() -> list[StrategyParams]:
    variants: list[StrategyParams] = []
    for drive in (0.0025, 0.0035, 0.0045):
        for efficiency in (0.55, 0.70):
            for relative_volume in (0.8, 1.0):
                variants.append(
                    StrategyParams(
                        "opening_drive_vwap",
                        30,
                        drive,
                        efficiency,
                        relative_volume,
                        0.0,
                        0.0025,
                        0.005,
                        60,
                    )
                )
    for drive in (0.002, 0.003):
        for efficiency in (0.45, 0.60):
            for relative_volume in (0.8, 1.0):
                for buffer in (0.0, 0.0005):
                    variants.append(
                        StrategyParams(
                            "opening_range_breakout",
                            60,
                            drive,
                            efficiency,
                            relative_volume,
                            buffer,
                            0.0025,
                            0.005,
                            60,
                        )
                    )
    for drive in (0.0025, 0.0035):
        for efficiency in (0.40, 0.55):
            for relative_volume in (0.8, 1.0):
                variants.append(
                    StrategyParams(
                        "vwap_pullback_reclaim",
                        60,
                        drive,
                        efficiency,
                        relative_volume,
                        0.0005,
                        0.0025,
                        0.005,
                        60,
                    )
                )
    return variants


def variant_id(params: StrategyParams) -> str:
    encoded = json.dumps(asdict(params), sort_keys=True, separators=(",", ":"))
    return f"{params.family}-{hashlib.sha256(encoded.encode()).hexdigest()[:10]}"


def _signals(sessions: dict[date, list[Bar]], params: StrategyParams) -> list[Signal]:
    prior_volumes: list[list[float]] = []
    signals: list[Signal] = []
    for bars in sessions.values():
        signal = generate_session_signal(bars, prior_volumes, params)
        if signal is not None:
            signals.append(signal)
        prior_volumes.append([bar.volume for bar in bars])
    return signals


def _underlying_trade(signal: Signal, bars: list[Bar], params: StrategyParams) -> UnderlyingTrade:
    future = [
        bar
        for bar in bars
        if signal.entry_at
        <= bar.timestamp
        < signal.entry_at + timedelta(minutes=params.hold_minutes)
    ]
    if not future:
        return UnderlyingTrade(
            signal.session_date,
            signal.direction,
            signal.signal_at,
            signal.entry_at,
            signal.entry_at,
            signal.entry_price,
            signal.entry_price,
            "no_following_bar",
            0.0,
            0.0,
        )
    multiplier = 1.0 if signal.direction == "bullish" else -1.0
    impact = 0.0002
    exit_bar = future[-1]
    exit_reason = "time"
    directional_return = multiplier * (exit_bar.close / signal.entry_price - 1.0)
    for bar in future:
        observed = multiplier * (bar.close / signal.entry_price - 1.0)
        exit_bar = bar
        directional_return = observed
        if observed <= -params.stop_fraction:
            exit_reason = "stop"
            break
        if observed >= params.target_fraction:
            exit_reason = "target"
            break
    return_r = (directional_return - impact) / params.stop_fraction
    return UnderlyingTrade(
        session_date=signal.session_date,
        direction=signal.direction,
        signal_at=signal.signal_at,
        entry_at=signal.entry_at,
        exit_at=exit_bar.timestamp + timedelta(minutes=5),
        entry_price=signal.entry_price,
        exit_price=exit_bar.close,
        exit_reason=exit_reason,
        net_pnl_dollars=return_r * 500.0,
        return_r=return_r,
    )


def _metrics(trades: list[UnderlyingTrade]) -> dict[str, Any]:
    returns = [trade.return_r for trade in trades]
    pnls = [trade.net_pnl_dollars for trade in trades]
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return {
        "sample_count": len(trades),
        "net_pnl_dollars": round(sum(pnls), 2),
        "expectancy_r": round(statistics.mean(returns), 6) if returns else 0.0,
        "hit_rate": round(sum(value > 0 for value in returns) / len(returns), 6)
        if returns
        else 0.0,
        "max_drawdown_dollars": round(drawdown, 2),
        "median_r": round(statistics.median(returns), 6) if returns else 0.0,
        "wins": sum(value > 0 for value in returns),
        "losses": sum(value < 0 for value in returns),
        "flats": sum(value == 0 for value in returns),
    }


def _evaluate(
    sessions: dict[date, list[Bar]], params: StrategyParams, allowed_dates: set[date] | None = None
) -> tuple[dict[str, Any], list[Signal], list[UnderlyingTrade]]:
    signals = _signals(sessions, params)
    if allowed_dates is not None:
        signals = [signal for signal in signals if signal.session_date in allowed_dates]
    trades = [
        _underlying_trade(signal, sessions[signal.session_date], params) for signal in signals
    ]
    return _metrics(trades), signals, trades


def _fold_date_sets(session_dates: list[date]) -> list[set[date]]:
    size = len(session_dates)
    boundaries = [math.floor(size * ratio) for ratio in (0.40, 0.60, 0.80, 1.0)]
    folds = [set(session_dates[boundaries[index] : boundaries[index + 1]]) for index in range(3)]
    return [fold for fold in folds if fold]


def _serialize_signal(signal: Signal) -> dict[str, Any]:
    value = asdict(signal)
    value["session_date"] = signal.session_date.isoformat()
    value["signal_at"] = signal.signal_at.isoformat().replace("+00:00", "Z")
    value["entry_at"] = signal.entry_at.isoformat().replace("+00:00", "Z")
    return value


def _serialize_trade(trade: UnderlyingTrade) -> dict[str, Any]:
    value = asdict(trade)
    value["session_date"] = trade.session_date.isoformat()
    for key in ("signal_at", "entry_at", "exit_at"):
        value[key] = getattr(trade, key).isoformat().replace("+00:00", "Z")
    return value


def run_experiment(dataset: dict[str, Any]) -> dict[str, Any]:
    training = _parse_records(dataset["training"]["records"])
    holdout = _parse_records(dataset["holdout"]["records"])
    fold_dates = _fold_date_sets(list(training))
    variant_results: list[dict[str, Any]] = []
    for params in _default_variants():
        full_metrics, _, _ = _evaluate(training, params)
        folds = [_evaluate(training, params, dates)[0] for dates in fold_dates]
        nonempty = [fold["expectancy_r"] for fold in folds if fold["sample_count"] > 0]
        median_fold = statistics.median(nonempty) if nonempty else -999.0
        positive_folds = sum(value > 0 for value in nonempty)
        variant_results.append(
            {
                "variant_id": variant_id(params),
                "parameters": asdict(params),
                "training": full_metrics,
                "walk_forward_folds": folds,
                "selection_score": {
                    "nonempty_folds": len(nonempty),
                    "positive_folds": positive_folds,
                    "median_fold_expectancy_r": round(median_fold, 6),
                },
            }
        )
    selected = max(
        variant_results,
        key=lambda row: (
            row["selection_score"]["positive_folds"],
            row["selection_score"]["nonempty_folds"],
            row["selection_score"]["median_fold_expectancy_r"],
            row["training"]["expectancy_r"],
            row["training"]["sample_count"],
            row["variant_id"],
        ),
    )
    selected_params = StrategyParams(**selected["parameters"])
    training_metrics, training_signals, training_trades = _evaluate(training, selected_params)
    oos_metrics, oos_signals, oos_trades = _evaluate(holdout, selected_params)
    return {
        "schema_version": "afterimage-trend-candidate-v1",
        "selection": {
            "selection_data": "training_walk_forward_only",
            "selected_variant_id": selected["variant_id"],
            "parameters": selected["parameters"],
            "training_session_count": len(training),
            "walk_forward_fold_count": len(fold_dates),
        },
        "variants": variant_results,
        "training": {
            **training_metrics,
            "signals": [_serialize_signal(item) for item in training_signals],
            "trades": [_serialize_trade(item) for item in training_trades],
        },
        "oos": {
            **oos_metrics,
            "signals": [_serialize_signal(item) for item in oos_signals],
            "trades": [_serialize_trade(item) for item in oos_trades],
            "session_count": len(holdout),
        },
        "underlying_proxy": {
            "risk_dollars_per_trade": 500.0,
            "round_trip_impact_bps": 2.0,
            "purpose": "training-only parameter selection; option claims require real option bars",
        },
    }


def build_dry_run_order(
    *,
    direction: str,
    long_symbol: str,
    short_symbol: str,
    quantity: int,
    limit_price: float,
    client_order_id: str,
) -> dict[str, Any]:
    if direction not in {"bullish", "bearish"}:
        raise ValueError("direction must be bullish or bearish")
    if quantity < 1 or limit_price <= 0:
        raise ValueError("positive quantity and limit price required")
    return {
        "dry_run": True,
        "transport": "alpaca-mcp-local-validation",
        "client_order_id": client_order_id,
        "order_class": "mleg",
        "type": "limit",
        "time_in_force": "day",
        "qty": str(quantity),
        "limit_price": f"{limit_price:.2f}",
        "legs": [
            {
                "symbol": long_symbol,
                "ratio_qty": "1",
                "side": "buy",
                "position_intent": "buy_to_open",
            },
            {
                "symbol": short_symbol,
                "ratio_qty": "1",
                "side": "sell",
                "position_intent": "sell_to_open",
            },
        ],
    }


def candidate_decision(
    *,
    training_proxy: dict[str, Any],
    walk_forward_folds: list[dict[str, Any]],
    oos_options: dict[str, Any],
) -> dict[str, Any]:
    nonempty = [fold for fold in walk_forward_folds if int(fold.get("sample_count", 0)) > 0]
    fold_expectancies = [float(fold.get("expectancy_r", 0.0)) for fold in nonempty]
    gates = {
        "training_proxy_sample_at_least_20": int(training_proxy.get("sample_count", 0)) >= 20,
        "training_proxy_expectancy_positive": float(training_proxy.get("expectancy_r", 0.0)) > 0,
        "three_nonempty_walk_forward_folds": len(nonempty) == 3,
        "two_positive_walk_forward_folds": sum(value > 0 for value in fold_expectancies) >= 2,
        "median_walk_forward_expectancy_positive": bool(fold_expectancies)
        and statistics.median(fold_expectancies) > 0,
        "oos_option_sample_at_least_10": int(oos_options.get("sample_count", 0)) >= 10,
        "oos_option_expectancy_positive": float(oos_options.get("expectancy_r", 0.0)) > 0,
        "oos_option_coverage_at_least_80pct": float(oos_options.get("coverage_rate", 1.0)) >= 0.80,
    }
    failed = [name for name, passed in gates.items() if not passed]
    return {
        "status": "implementation_candidate" if not failed else "no_candidate",
        "gates": gates,
        "failed_gates": failed,
    }
