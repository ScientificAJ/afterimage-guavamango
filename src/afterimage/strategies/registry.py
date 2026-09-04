from __future__ import annotations

from .base import StrategyPlugin
from .momentum_continuation import MomentumContinuationStrategy
from .opening_range_failure import OpeningRangeFailureStrategy
from .volatility_dislocation import VolatilityDislocationStrategy


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[tuple[str, str], StrategyPlugin] = {}

    def register(self, strategy: StrategyPlugin) -> None:
        key = (strategy.identity.strategy_id, strategy.identity.strategy_version)
        if key in self._strategies:
            raise ValueError(f"duplicate strategy: {key}")
        self._strategies[key] = strategy

    def load(self, strategy_id: str, strategy_version: str = "1.0.0") -> StrategyPlugin:
        try:
            return self._strategies[(strategy_id, strategy_version)]
        except KeyError as exc:
            raise KeyError(f"unknown immutable strategy {strategy_id}@{strategy_version}") from exc

    def list(self) -> list[str]:
        return [f"{key[0]}@{key[1]}" for key in sorted(self._strategies)]


def default_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(OpeningRangeFailureStrategy())
    registry.register(MomentumContinuationStrategy())
    registry.register(VolatilityDislocationStrategy())
    return registry
