from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

from afterimage.contracts.models import CandidateEvent, ExitPlan, FrozenSnapshot, StrategyIdentity

from .base import BaseStrategy, MarketFrame

ET = ZoneInfo("America/New_York")


class OpeningRangeFailureStrategy(BaseStrategy):
    identity = StrategyIdentity(strategy_id="opening_range_failure_v1", strategy_version="1.0.0")

    def build_features(self, raw: MarketFrame) -> dict[str, float | int | str | bool | None]:
        bars = sorted(
            [(r.timestamp.astimezone(ET), r.values) for r in raw.records if r.kind == "bar"],
            key=lambda item: item[0],
        )
        opening = [
            values for ts, values in bars if ts.time() in {time(9, 30), time(9, 35), time(9, 40)}
        ]
        probe = [(ts, values) for ts, values in bars if time(9, 45) <= ts.time() <= time(9, 55)]
        if len(opening) != 3 or not probe:
            return {"complete": False, "bar_count": len(opening) + len(probe)}
        high = max(float(bar["high"]) for bar in opening)
        low = min(float(bar["low"]) for bar in opening)
        width = high - low
        close_0955 = next(
            (float(values["close"]) for ts, values in probe if ts.time() == time(9, 55)), None
        )
        upper_peak = max(float(values["high"]) for _, values in probe)
        lower_trough = min(float(values["low"]) for _, values in probe)
        upper = width > 0 and upper_peak >= high + 0.10 * width
        lower = width > 0 and lower_trough <= low - 0.10 * width
        reentered = close_0955 is not None and low <= close_0955 <= high
        return {
            "complete": True,
            "range_high": high,
            "range_low": low,
            "range_width": width,
            "upper_penetration": upper,
            "lower_penetration": lower,
            "close_0955": close_0955,
            "reentered": reentered,
            "relative_volume": float(raw.context.get("relative_volume", 1.0)),
            "realized_volatility": float(raw.context.get("realized_volatility", 0.0)),
        }

    def detect(self, snapshot: FrozenSnapshot) -> CandidateEvent | None:
        features = snapshot.features
        if not features.get("complete") or not features.get("reentered"):
            return None
        upper = bool(features.get("upper_penetration"))
        lower = bool(features.get("lower_penetration"))
        if upper == lower:
            return None
        direction = "bearish" if upper else "bullish"
        structure = "put_debit_vertical" if upper else "call_debit_vertical"
        return CandidateEvent(
            identity=self.identity,
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.records[0].symbol if snapshot.records else "SPY",
            direction=direction,
            signal_at=snapshot.cutoff,
            features=features,
            permitted_structures=(structure,),
        )

    def exit_plan(self, candidate: CandidateEvent) -> ExitPlan:
        local = candidate.signal_at.astimezone(ET).replace(
            hour=10, minute=45, second=0, microsecond=0
        )
        return ExitPlan(
            target_r="3", stop_r="-1", exit_at=local.astimezone(candidate.signal_at.tzinfo)
        )
