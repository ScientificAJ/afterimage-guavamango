from __future__ import annotations

from typing import Any

import pytest

from afterimage import cli


class FakeGateway:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.closed = True


class FakeCoordinator:
    def __init__(self) -> None:
        self.call: tuple[Any, Any, str, str, str | None] | None = None

    async def run_live_shadow(
        self,
        gateway: Any,
        desk: Any,
        account_hash: str,
        symbol: str,
        strategy_id: str | None = None,
    ) -> dict[str, Any]:
        self.call = (gateway, desk, account_hash, symbol, strategy_id)
        return {
            "mode": "live-shadow",
            "state": "NO_SIGNAL",
            "broker": {"connected": True, "order_sent": False},
        }


@pytest.mark.asyncio
async def test_shadow_cli_wires_live_gateway_and_agent_desk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = FakeGateway()
    coordinator = FakeCoordinator()
    model_gateway = object()
    monkeypatch.setattr(cli, "build_alpaca_gateway", lambda: gateway)
    monkeypatch.setattr(cli, "runtime", lambda: coordinator)
    monkeypatch.setattr(cli, "expected_account_id_hash", lambda: "a" * 64)
    monkeypatch.setattr(cli, "load_featherless_gateway", lambda: model_gateway)

    result = await cli._shadow("SPY", "momentum_continuation_v1")

    assert result["mode"] == "live-shadow"
    assert result["broker"]["order_sent"] is False
    assert coordinator.call is not None
    assert coordinator.call[0] is gateway
    assert coordinator.call[1].gateway is model_gateway
    assert coordinator.call[2:] == (
        "a" * 64,
        "SPY",
        "momentum_continuation_v1",
    )
    assert gateway.connected is True
    assert gateway.closed is True


@pytest.mark.asyncio
async def test_shadow_cli_closes_gateway_when_runtime_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = FakeGateway()

    class FailingCoordinator(FakeCoordinator):
        async def run_live_shadow(
            self,
            gateway: Any,
            desk: Any,
            account_hash: str,
            symbol: str,
            strategy_id: str | None = None,
        ) -> dict[str, Any]:
            del gateway, desk, account_hash, symbol, strategy_id
            raise RuntimeError("STOP")

    monkeypatch.setattr(cli, "build_alpaca_gateway", lambda: gateway)
    monkeypatch.setattr(cli, "runtime", lambda: FailingCoordinator())
    monkeypatch.setattr(cli, "expected_account_id_hash", lambda: "a" * 64)
    monkeypatch.setattr(cli, "load_featherless_gateway", lambda: object())

    with pytest.raises(RuntimeError, match="STOP"):
        await cli._shadow("SPY", None)

    assert gateway.closed is True


@pytest.mark.asyncio
async def test_autopilot_defaults_to_non_executing_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = FakeGateway()
    observed: dict[str, Any] = {}

    class CycleCoordinator:
        def managed_session_ids(self) -> list[str]:
            return []

        async def run_live_cycle(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            observed["args"] = args
            observed["kwargs"] = kwargs
            return {"mode": "live-shadow", "state": "NO_SIGNAL"}

    monkeypatch.setattr(cli, "build_alpaca_gateway", lambda: gateway)
    monkeypatch.setattr(cli, "runtime", lambda: CycleCoordinator())
    monkeypatch.setattr(cli, "expected_account_id_hash", lambda: "a" * 64)
    monkeypatch.setattr(cli, "load_featherless_gateway", lambda: object())

    result = await cli._autopilot(
        "spy",
        strategy_id="momentum_continuation_v1",
        execute=False,
        cycles=1,
        interval_seconds=5,
    )

    assert result[0]["mode"] == "live-shadow"
    assert observed["kwargs"] == {
        "symbol": "SPY",
        "strategy_id": "momentum_continuation_v1",
        "execute": False,
    }
    assert gateway.closed is True


def test_serve_refuses_remote_binding_without_operator_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AFTERIMAGE_OPERATOR_TOKEN", raising=False)

    with pytest.raises(Exception, match="AFTERIMAGE_OPERATOR_TOKEN"):
        cli.serve(host="0.0.0.0", port=8000)
