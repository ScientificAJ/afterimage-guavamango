from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from afterimage.contracts.models import CandidateEvent, ExitPlan, FrozenSnapshot, StrategyIdentity

from .base import BaseStrategy, MarketFrame

ET = ZoneInfo("America/New_York")
CENT = Decimal("0.01")
UNIVERSE = ("QQQ", "IWM", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "TLT", "GLD")
ALLOWED_WEEKDAYS = (0, 1, 2)
WARMUP_INDEX = 110
ATR_SESSIONS = 14
FAST_SMA_SESSIONS = 50
SLOW_SMA_SESSIONS = 100
SHOCK_LOOKBACK_SESSIONS = 2
MINIMUM_SHOCK_ATR = Decimal("0.6")
MAXIMUM_CLOSE_LOCATION = Decimal("0.25")
MINIMUM_STOP_FRACTION = Decimal("0.001")
MAXIMUM_STOP_FRACTION = Decimal("0.03")
MAXIMUM_HOLDING_SESSIONS = 5
NOTIONAL = Decimal(10000)
SLIPPAGE_FRACTION = Decimal("0.0001")
FEE_PER_SHARE_PER_SIDE = Decimal("0.005")


@dataclass(frozen=True)
class _DailyBar:
    symbol: str
    session: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class _DailyFeature:
    symbol: str
    session: date
    trend: int
    atr: Decimal
    atr_fraction: Decimal
    two_day_atr_return: Decimal
    close_location: Decimal
    sma50: Decimal
    sma100: Decimal

    @property
    def countertrend_shock_atr(self) -> Decimal:
        return -Decimal(self.trend) * self.two_day_atr_return


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def _completed_session(timestamp: datetime, cutoff: datetime) -> bool:
    session = timestamp.astimezone(ET).date()
    local_cutoff = cutoff.astimezone(ET)
    return session < local_cutoff.date() or (
        session == local_cutoff.date() and local_cutoff.time() >= time(16)
    )


def _daily_bars(raw: MarketFrame) -> dict[str, tuple[_DailyBar, ...]]:
    grouped: dict[tuple[str, date], list[tuple[datetime, Mapping[str, object]]]] = defaultdict(list)
    for record in raw.records:
        if (
            record.kind != "bar"
            or record.symbol not in UNIVERSE
            or not _completed_session(record.timestamp, raw.cutoff)
        ):
            continue
        grouped[(record.symbol, record.timestamp.astimezone(ET).date())].append(
            (record.timestamp, record.values)
        )
    result: dict[str, list[_DailyBar]] = defaultdict(list)
    for (symbol, session), records in sorted(grouped.items()):
        ordered = sorted(records, key=lambda item: item[0])
        values = [item[1] for item in ordered]
        result[symbol].append(
            _DailyBar(
                symbol=symbol,
                session=session,
                open=Decimal(str(values[0]["open"])),
                high=max(Decimal(str(item["high"])) for item in values),
                low=min(Decimal(str(item["low"])) for item in values),
                close=Decimal(str(values[-1]["close"])),
                volume=sum(int(str(item.get("volume", 0))) for item in values),
            )
        )
    return {symbol: tuple(rows) for symbol, rows in result.items()}


def _feature(rows: Sequence[_DailyBar], index: int) -> _DailyFeature:
    current = rows[index]
    true_ranges = []
    for cursor in range(index - ATR_SESSIONS + 1, index + 1):
        previous_close = rows[cursor - 1].close
        item = rows[cursor]
        true_ranges.append(
            max(
                item.high - item.low,
                abs(item.high - previous_close),
                abs(item.low - previous_close),
            )
        )
    atr = _mean(true_ranges)
    sma50 = _mean(tuple(item.close for item in rows[index - FAST_SMA_SESSIONS + 1 : index + 1]))
    sma100 = _mean(tuple(item.close for item in rows[index - SLOW_SMA_SESSIONS + 1 : index + 1]))
    trend = (
        1
        if current.close > sma100 and sma50 > sma100
        else -1
        if current.close < sma100 and sma50 < sma100
        else 0
    )
    close_location = (
        (current.close - current.low) / (current.high - current.low)
        if current.high > current.low
        else Decimal("0.5")
    )
    two_day_atr_return = (
        current.close / rows[index - SHOCK_LOOKBACK_SESSIONS].close - Decimal(1)
    ) / (atr / current.close)
    return _DailyFeature(
        symbol=current.symbol,
        session=current.session,
        trend=trend,
        atr=atr,
        atr_fraction=atr / current.close,
        two_day_atr_return=two_day_atr_return,
        close_location=close_location,
        sma50=sma50,
        sma100=sma100,
    )


def _feature_streams(
    daily: Mapping[str, Sequence[_DailyBar]],
) -> dict[date, tuple[_DailyFeature, ...]]:
    grouped: dict[date, list[_DailyFeature]] = defaultdict(list)
    for symbol in UNIVERSE:
        rows = daily.get(symbol, ())
        for index in range(WARMUP_INDEX, len(rows)):
            item = _feature(rows, index)
            grouped[item.session].append(item)
    return {session: tuple(items) for session, items in sorted(grouped.items())}


def _select(items: Sequence[_DailyFeature]) -> _DailyFeature | None:
    eligible = [
        item
        for item in items
        if item.trend == 1
        and item.countertrend_shock_atr >= MINIMUM_SHOCK_ATR
        and item.close_location <= MAXIMUM_CLOSE_LOCATION
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda item: (item.countertrend_shock_atr, item.symbol))


def _stop_fraction(feature: _DailyFeature) -> Decimal:
    return max(MINIMUM_STOP_FRACTION, min(MAXIMUM_STOP_FRACTION, feature.atr_fraction))


def _shadow_levels(feature: _DailyFeature, entry: Decimal) -> tuple[Decimal, Decimal]:
    entry_fill = entry * (Decimal(1) + SLIPPAGE_FRACTION)
    shares = int(NOTIONAL // entry_fill)
    stop = (entry * (Decimal(1) - _stop_fraction(feature))).quantize(CENT, rounding=ROUND_HALF_UP)
    fees = FEE_PER_SHARE_PER_SIDE * Decimal(shares) * Decimal(2)
    stop_fill = stop * (Decimal(1) - SLIPPAGE_FRACTION)
    risk = -(stop_fill - entry_fill) * Decimal(shares) + fees
    raw_target = (entry_fill + (Decimal(3) * risk + fees) / Decimal(shares)) / (
        Decimal(1) - SLIPPAGE_FRACTION
    )
    return stop, raw_target.quantize(CENT, rounding=ROUND_CEILING)


def _shadow_exit_session(
    feature: _DailyFeature,
    daily: Mapping[str, Sequence[_DailyBar]],
    latest_session: date,
) -> date:
    future = tuple(item for item in daily[feature.symbol] if item.session > feature.session)
    if not future:
        return latest_session
    horizon = future[:MAXIMUM_HOLDING_SESSIONS]
    stop, target = _shadow_levels(feature, future[0].open)
    for bar in horizon:
        # Frozen research contract: stop wins when both levels occur in one OHLC bar.
        if bar.low <= stop:
            return bar.session
        if bar.high >= target:
            return bar.session
    if len(horizon) < MAXIMUM_HOLDING_SESSIONS:
        return latest_session
    return horizon[-1].session


def _business_session_exit(signal_at: datetime, sessions: int) -> datetime:
    local = signal_at.astimezone(ET)
    session = local.date()
    remaining = sessions
    while remaining:
        session += timedelta(days=1)
        if session.weekday() < 5:
            remaining -= 1
    return datetime.combine(session, time(16), ET).astimezone(signal_at.tzinfo)


class ShadowClockShockReversalStrategy(BaseStrategy):
    identity = StrategyIdentity(
        strategy_id="shadow_clock_shock_reversal_v1",
        strategy_version="1.0.0",
    )

    def build_features(self, raw: MarketFrame) -> dict[str, float | int | str | bool | None]:
        daily = _daily_bars(raw)
        missing_symbols = tuple(symbol for symbol in UNIVERSE if symbol not in daily)
        if missing_symbols:
            return {
                "complete": False,
                "universe_complete": False,
                "missing_symbols": ",".join(missing_symbols),
                "symbol_count": len(UNIVERSE) - len(missing_symbols),
            }
        latest_session = max(rows[-1].session for rows in daily.values())
        stale_symbols = tuple(
            symbol for symbol in UNIVERSE if daily[symbol][-1].session != latest_session
        )
        short_history = tuple(symbol for symbol in UNIVERSE if len(daily[symbol]) <= WARMUP_INDEX)
        incomplete = tuple(sorted(set(stale_symbols + short_history)))
        if incomplete:
            return {
                "complete": False,
                "universe_complete": False,
                "missing_symbols": ",".join(incomplete),
                "symbol_count": len(UNIVERSE),
                "latest_session": latest_session.isoformat(),
            }

        streams = _feature_streams(daily)
        unavailable_through: date | None = None
        blocking_signal: _DailyFeature | None = None
        current: _DailyFeature | None = None
        current_blocked = False
        current_started = False
        for session, items in streams.items():
            selected = _select(items)
            if selected is None:
                continue
            if unavailable_through is not None and session <= unavailable_through:
                if session == latest_session:
                    current = selected
                    current_blocked = True
                continue
            if session == latest_session:
                current = selected
                current_started = True
                continue
            unavailable_through = _shadow_exit_session(selected, daily, latest_session)
            blocking_signal = selected

        calendar_allowed = latest_session.weekday() in ALLOWED_WEEKDAYS
        base: dict[str, float | int | str | bool | None] = {
            "complete": True,
            "universe_complete": True,
            "missing_symbols": "",
            "symbol_count": len(UNIVERSE),
            "latest_session": latest_session.isoformat(),
            "calendar_allowed": calendar_allowed,
            "shadow_blocked": current_blocked,
            "shadow_signal_started": current_started,
            "blocking_signal_weekday": (
                blocking_signal.session.strftime("%A")
                if current_blocked and blocking_signal is not None
                else ""
            ),
            "long_only": True,
            "next_bar_execution": True,
            "maximum_holding_sessions": MAXIMUM_HOLDING_SESSIONS,
            "target_r": 3.0,
            "stop_r": -1.0,
            "modeled_slippage_bps": 1.0,
            "fee_per_share_per_side": float(FEE_PER_SHARE_PER_SIDE),
        }
        if current is None:
            return {
                **base,
                "selected_symbol": None,
                "equity_side": None,
            }
        stop_fraction = _stop_fraction(current)
        signal_close = next(
            item.close for item in daily[current.symbol] if item.session == current.session
        )
        return {
            **base,
            "selected_symbol": current.symbol,
            "equity_side": "buy",
            "trend": current.trend,
            "atr": float(current.atr),
            "atr_fraction": float(current.atr_fraction),
            "sma50": float(current.sma50),
            "sma100": float(current.sma100),
            "two_day_atr_return": float(current.two_day_atr_return),
            "countertrend_shock_atr": float(current.countertrend_shock_atr),
            "close_location": float(current.close_location),
            "stop_distance_fraction": float(stop_fraction),
            "stop_distance": float(signal_close * stop_fraction),
            "stop_distance_basis": "signal_close_reference",
        }

    def detect(self, snapshot: FrozenSnapshot) -> CandidateEvent | None:
        features = snapshot.features
        symbol = features.get("selected_symbol")
        if (
            not features.get("complete")
            or not features.get("calendar_allowed")
            or features.get("shadow_blocked")
            or not isinstance(symbol, str)
        ):
            return None
        return CandidateEvent(
            candidate_id=self.candidate_id(snapshot),
            identity=self.identity,
            snapshot_id=snapshot.snapshot_id,
            symbol=symbol,
            direction="bullish",
            signal_at=snapshot.cutoff,
            features=features,
            permitted_structures=("equity_bracket",),
        )

    def exit_plan(self, candidate: CandidateEvent) -> ExitPlan:
        return ExitPlan(
            target_r="3",
            stop_r="-1",
            exit_at=_business_session_exit(candidate.signal_at, MAXIMUM_HOLDING_SESSIONS),
        )
