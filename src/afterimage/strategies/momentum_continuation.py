from __future__ import annotations

from datetime import timedelta

from afterimage.contracts.models import CandidateEvent, ExitPlan, FrozenSnapshot, StrategyIdentity

from .base import BaseStrategy, MarketFrame, numeric_feature


class MomentumContinuationStrategy(BaseStrategy):
    identity = StrategyIdentity(strategy_id="momentum_continuation_v1", strategy_version="1.0.0")

    def build_features(self, raw: MarketFrame) -> dict[str, float | int | str | bool | None]:
        bars = sorted([r for r in raw.records if r.kind == "bar"], key=lambda r: r.timestamp)
        if len(bars) < 7:
            return {"complete": False, "bar_count": len(bars)}
        window = bars[-7:]
        start = float(window[0].values["open"])
        close = float(window[-1].values["close"])
        highs = [float(r.values["high"]) for r in window[:-1]]
        lows = [float(r.values["low"]) for r in window[:-1]]
        volumes = [float(r.values.get("volume", 0)) for r in window]
        move = (close / start) - 1 if start else 0.0
        volume_ratio = (
            volumes[-1] / (sum(volumes[:-1]) / max(1, len(volumes) - 1))
            if sum(volumes[:-1])
            else 0.0
        )
        return {
            "complete": True,
            "window_return": move,
            "breaks_prior_high": close > max(highs),
            "breaks_prior_low": close < min(lows),
            "volume_ratio": volume_ratio,
            "realized_volatility": float(raw.context.get("realized_volatility", 0.0)),
        }

    def detect(self, snapshot: FrozenSnapshot) -> CandidateEvent | None:
        f = snapshot.features
        if not f.get("complete") or numeric_feature(f, "volume_ratio") < 1.25:
            return None
        bullish = bool(f.get("breaks_prior_high")) and numeric_feature(f, "window_return") >= 0.002
        bearish = bool(f.get("breaks_prior_low")) and numeric_feature(f, "window_return") <= -0.002
        if bullish == bearish:
            return None
        return CandidateEvent(
            identity=self.identity,
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.records[0].symbol if snapshot.records else "SPY",
            direction="bullish" if bullish else "bearish",
            signal_at=snapshot.cutoff,
            features=f,
            permitted_structures=("call_debit_vertical" if bullish else "put_debit_vertical",),
        )

    def exit_plan(self, candidate: CandidateEvent) -> ExitPlan:
        return ExitPlan(
            target_r="3", stop_r="-1", exit_at=candidate.signal_at + timedelta(minutes=75)
        )
