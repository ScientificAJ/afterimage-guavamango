from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any, cast

from .base import StrategyPlugin
from .momentum_continuation import MomentumContinuationStrategy
from .opening_range_failure import OpeningRangeFailureStrategy
from .volatility_dislocation import VolatilityDislocationStrategy

if TYPE_CHECKING:
    from afterimage.config import RuntimeConfig


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


def _load_plugin(reference: str) -> StrategyPlugin:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise RuntimeError(f"STRATEGY_PLUGIN_REFERENCE_INVALID:{reference}")
    module = import_module(module_name)
    plugin_type: Any = getattr(module, attribute, None)
    if plugin_type is None or not callable(plugin_type):
        raise RuntimeError(f"STRATEGY_PLUGIN_NOT_CALLABLE:{reference}")
    plugin = plugin_type()
    if not hasattr(plugin, "identity"):
        raise RuntimeError(f"STRATEGY_PLUGIN_IDENTITY_MISSING:{reference}")
    return cast(StrategyPlugin, plugin)


def configured_registry(config: RuntimeConfig) -> StrategyRegistry:
    """Discover immutable plugins from config so adding one requires no registry edit."""
    registry = StrategyRegistry()
    for strategy_id in sorted(config.strategies):
        configured = config.strategies[strategy_id]
        reference = configured.payload.get("plugin")
        if not isinstance(reference, str):
            raise TypeError(f"STRATEGY_PLUGIN_MISSING:{strategy_id}")
        plugin = _load_plugin(reference)
        if (
            plugin.identity.strategy_id != configured.strategy_id
            or plugin.identity.strategy_version != configured.strategy_version
        ):
            raise RuntimeError(f"STRATEGY_PLUGIN_IDENTITY_MISMATCH:{strategy_id}")
        registry.register(plugin)
    return registry
