from __future__ import annotations

from datetime import timedelta

from afterimage.contracts.models import CandidateEvent, ExitPlan, FrozenSnapshot, StrategyIdentity

from .base import BaseStrategy, MarketFrame, numeric_feature


class VolatilityDislocationStrategy(BaseStrategy):
    identity = StrategyIdentity(strategy_id="volatility_dislocation_v1", strategy_version="1.0.0")

    def build_features(self, raw: MarketFrame) -> dict[str, float | int | str | bool | None]:
        forecast = float(raw.context.get("forecast_move", 0.0))
        implied = float(raw.context.get("implied_move", 0.0))
        liquidity = float(raw.context.get("liquidity_score", 0.0))
        return {
            "complete": forecast > 0 and implied > 0,
            "forecast_move": forecast,
            "implied_move": implied,
            "move_ratio": forecast / implied if implied else 0.0,
            "liquidity_score": liquidity,
            "catalyst_fresh": bool(raw.context.get("catalyst_fresh", False)),
        }

    def detect(self, snapshot: FrozenSnapshot) -> CandidateEvent | None:
        f = snapshot.features
        if not f.get("complete") or numeric_feature(f, "move_ratio") < 1.20:
            return None
        if numeric_feature(f, "liquidity_score") < 0.70:
            return None
        return CandidateEvent(
            candidate_id=self.candidate_id(snapshot),
            identity=self.identity,
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.records[0].symbol if snapshot.records else "SPY",
            direction="long_volatility",
            signal_at=snapshot.cutoff,
            features=f,
            permitted_structures=("long_straddle",),
        )

    def exit_plan(self, candidate: CandidateEvent) -> ExitPlan:
        return ExitPlan(
            target_r="3", stop_r="-1", exit_at=candidate.signal_at + timedelta(minutes=90)
        )
