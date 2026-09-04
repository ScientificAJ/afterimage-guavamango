from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from afterimage.agents.gateway import RecordedGateway
from afterimage.agents.roles import AgentDesk
from afterimage.agents.schemas import AgentFinding, AgentReport, AgentRole
from afterimage.contracts.hashing import canonical_sha256
from afterimage.contracts.models import AccountSnapshot, ExecutionWarrant
from afterimage.execution.alpaca_gateway import AccountPreflight
from afterimage.execution.lifecycle import ExecutionError
from afterimage.orchestration.coordinator import Coordinator
from afterimage.storage import Database

EQUITY_UNIVERSE = (
    "QQQ",
    "IWM",
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLI",
    "XLP",
    "TLT",
    "GLD",
)


@pytest.fixture(autouse=True)
def legacy_option_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep this module's older option-path cases explicit after winner promotion."""
    monkeypatch.setenv("AFTERIMAGE_ACTIVE_STRATEGY", "opening_range_failure_v1")


def report(role: AgentRole) -> AgentReport:
    return AgentReport(
        role=role,
        status="challenge" if role == AgentRole.PROSECUTOR else "support",
        thesis=f"{role.value} packet-bound report",
        findings=(
            AgentFinding(
                claim="Packet was received.",
                evidence_keys=("snapshot.snapshot_id",),
                severity="support",
            ),
        ),
        falsifiers=("A changed snapshot hash invalidates the report.",),
        reason_code="TEST_PACKET_BOUND",
        model_id="featherless-live-test",
        prompt_hash="p" * 64,
        response_hash=canonical_sha256(role.value),
        latency_ms=1,
    )


class FakeLiveGateway:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.account_hash = "a" * 64

    async def preflight(
        self, expected: str, allow_existing_exposure: bool | None = None
    ) -> AccountPreflight:
        del allow_existing_exposure
        self.calls.append("preflight")
        assert expected == self.account_hash
        return AccountPreflight(
            account=AccountSnapshot(
                account_id_hash=self.account_hash,
                paper=True,
                status="ACTIVE",
                equity=Decimal(100000),
                last_equity=Decimal(100000),
                cash=Decimal(100000),
                options_buying_power=Decimal(100000),
                options_approved_level=3,
                options_trading_level=3,
                trading_blocked=False,
                timestamp=datetime(2026, 9, 4, 14, 0, tzinfo=UTC),
            ),
            market_open=True,
            clock={
                "is_open": True,
                "timestamp": "2026-09-04T10:00:00-04:00",
                "next_close": "2026-09-04T16:00:00-04:00",
            },
            open_orders=(),
            positions=(),
            capabilities={"transport": "alpaca-cli/0.0.14", "execution": "disabled"},
        )

    async def stock_bars(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "5Min"
    ) -> list[dict[str, Any]]:
        del symbol, start, end, timeframe
        self.calls.append("stock_bars")
        return [
            {"t": "2026-09-04T13:30:00Z", "o": 650, "h": 651, "l": 649.5, "c": 650.5, "v": 1000},
            {"t": "2026-09-04T13:35:00Z", "o": 650.5, "h": 651.5, "l": 650, "c": 651, "v": 1100},
            {"t": "2026-09-04T13:40:00Z", "o": 651, "h": 652, "l": 650.8, "c": 651.6, "v": 1200},
            {
                "t": "2026-09-04T13:45:00Z",
                "o": 651.6,
                "h": 652.4,
                "l": 651.2,
                "c": 652.1,
                "v": 1300,
            },
            {
                "t": "2026-09-04T13:50:00Z",
                "o": 652.1,
                "h": 652.6,
                "l": 651.5,
                "c": 651.8,
                "v": 1400,
            },
            {
                "t": "2026-09-04T13:55:00Z",
                "o": 651.8,
                "h": 652.55,
                "l": 651.2,
                "c": 651.4,
                "v": 1500,
            },
            {"t": "2026-09-04T14:00:00Z", "o": 651.4, "h": 700, "l": 600, "c": 699, "v": 999999},
        ]

    async def option_contracts(self, symbol: str, **_: Any) -> list[dict[str, Any]]:
        del symbol
        self.calls.append("option_contracts")
        return [
            {
                "symbol": "SPY260908P00650000",
                "expiration_date": "2026-09-08",
                "strike_price": "650",
                "type": "put",
                "open_interest": "800",
                "tradable": True,
            },
            {
                "symbol": "SPY260908P00644000",
                "expiration_date": "2026-09-08",
                "strike_price": "644",
                "type": "put",
                "open_interest": "900",
                "tradable": True,
            },
        ]

    async def option_chain(self, symbol: str, **_: Any) -> dict[str, Any]:
        del symbol
        self.calls.append("option_chain")
        return {
            "snapshots": {
                "SPY260908P00650000": {
                    "latestQuote": {"bp": 0.70, "ap": 0.72, "t": "2026-09-04T14:00:00Z"},
                    "greeks": {"delta": -0.30},
                },
                "SPY260908P00644000": {
                    "latestQuote": {"bp": 0.20, "ap": 0.21, "t": "2026-09-04T14:00:00Z"},
                    "greeks": {"delta": -0.05},
                },
            }
        }

    async def dry_run_option_order(self, intent: Any, client_order_id: str) -> dict[str, Any]:
        self.calls.append("dry_run_option_order")
        return {
            "dry_run": True,
            "order_class": intent.order_class,
            "client_order_id": client_order_id,
            "legs": [leg.symbol for leg in intent.legs],
        }

    async def place_option_order(self, intent: Any, client_order_id: str) -> dict[str, Any]:
        del intent
        self.calls.append("place_option_order")
        return {"id": "paper-order-test", "client_order_id": client_order_id, "status": "accepted"}

    async def order_by_client_id(self, client_order_id: str) -> dict[str, Any]:
        del client_order_id
        self.calls.append("order_by_client_id")
        return {}

    async def positions(self) -> tuple[dict[str, Any], ...]:
        self.calls.append("positions")
        return ()


class NeverModelGateway:
    async def complete(self, *_: Any, **__: Any) -> Any:
        raise AssertionError("model must not run when deterministic strategy has no signal")


def equity_signal_bars(symbol: str) -> list[dict[str, Any]]:
    sessions: list[date] = []
    cursor = date(2026, 9, 2)
    while len(sessions) < 115:
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    rows: list[dict[str, Any]] = []
    for index, session in enumerate(reversed(sessions)):
        baseline = Decimal(100) + Decimal(index) * Decimal("0.5")
        close = baseline
        low = baseline - Decimal(1)
        if index == 114 and symbol in {"QQQ", "IWM"}:
            close = baseline - Decimal(6 if symbol == "QQQ" else 8)
            low = close - Decimal("0.5")
        rows.append(
            {
                "t": datetime.combine(session, time(20), UTC).isoformat(),
                "o": str(baseline - Decimal("0.1")),
                "h": str(baseline + Decimal(1)),
                "l": str(low),
                "c": str(close),
                "v": 1_000_000 + index,
            }
        )
    return rows


def install_fixture_research(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = Coordinator._historical_rows()
    dataset_hash = canonical_sha256([row.model_dump(mode="json") for row in rows])
    monkeypatch.setattr(
        Coordinator,
        "_live_research_evidence",
        staticmethod(
            lambda strategy_id, symbol: (
                rows,
                dataset_hash,
                {
                    "source": "test-fixture",
                    "strategy_id": strategy_id,
                    "symbol": symbol,
                    "result_type": "test-only deterministic fixture",
                },
            )
        ),
    )


@pytest.mark.asyncio
async def test_live_shadow_stops_before_options_and_models_when_no_signal(
    tmp_path: Path,
) -> None:
    gateway = FakeLiveGateway()

    async def no_signal_bars(
        symbol: str, start: datetime, end: datetime, timeframe: str = "5Min"
    ) -> list[dict[str, Any]]:
        del symbol, start, end, timeframe
        gateway.calls.append("stock_bars")
        return [
            {
                "t": f"2026-09-04T13:{minute:02d}:00Z",
                "o": 650,
                "h": 651,
                "l": 649.5,
                "c": 650.5,
                "v": 1000,
            }
            for minute in (30, 35, 40, 45, 50, 55)
        ]

    gateway.stock_bars = no_signal_bars  # type: ignore[method-assign]
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'no-signal.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )

    summary = await runtime.run_live_shadow(
        gateway,
        AgentDesk(NeverModelGateway()),  # type: ignore[arg-type]
        gateway.account_hash,
    )

    assert summary["state"] == "NO_SIGNAL"
    assert summary["agent_provenance"]["mode"] == "not-invoked-no-signal"
    assert gateway.calls == ["preflight", "stock_bars"]


@pytest.mark.asyncio
async def test_admitted_equity_winner_reaches_a_real_bracket_dry_run(
    tmp_path: Path,
) -> None:
    class EquityGateway(FakeLiveGateway):
        async def preflight(
            self, expected: str, allow_existing_exposure: bool | None = None
        ) -> AccountPreflight:
            del allow_existing_exposure
            self.calls.append("preflight")
            assert expected == self.account_hash
            observed_at = datetime(2026, 9, 3, 13, 35, tzinfo=UTC)
            return AccountPreflight(
                account=AccountSnapshot(
                    account_id_hash=self.account_hash,
                    paper=True,
                    status="ACTIVE",
                    equity=Decimal(100000),
                    last_equity=Decimal(100000),
                    cash=Decimal(100000),
                    options_buying_power=Decimal(100000),
                    options_approved_level=3,
                    options_trading_level=3,
                    trading_blocked=False,
                    timestamp=observed_at,
                ),
                market_open=True,
                clock={
                    "is_open": True,
                    "timestamp": "2026-09-03T09:35:00-04:00",
                    "next_close": "2026-09-03T16:00:00-04:00",
                },
                open_orders=(),
                positions=(),
                capabilities={"transport": "alpaca-cli/0.0.14", "execution": "disabled"},
            )

        async def stock_bars(
            self,
            symbol: str,
            start: datetime,
            end: datetime,
            timeframe: str = "5Min",
        ) -> list[dict[str, Any]]:
            del start, end
            self.calls.append(f"stock_bars:{symbol}")
            assert timeframe == "1Day"
            return equity_signal_bars(symbol)

        async def stock_snapshot(self, symbol: str) -> dict[str, Any]:
            self.calls.append("stock_snapshot")
            assert symbol == "IWM"
            return {
                "symbol": symbol,
                "latestQuote": {
                    "bp": "199.98",
                    "ap": "200.02",
                    "t": "2026-09-03T13:35:00Z",
                },
            }

        async def dry_run_order(self, intent: Any, client_order_id: str) -> dict[str, Any]:
            self.calls.append("dry_run_order")
            assert intent.asset_class == "equity"
            assert intent.order_class == "bracket"
            return {
                "dry_run": True,
                "submitted": False,
                "client_order_id": client_order_id,
                "symbol": intent.symbol,
                "quantity": intent.quantity,
                "take_profit_price": str(intent.take_profit_price),
                "stop_price": str(intent.stop_price),
            }

    gateway = EquityGateway()
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'equity-winner.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )

    summary = await runtime.run_live_shadow(
        gateway,
        desk,
        gateway.account_hash,
        strategy_id="shadow_clock_shock_reversal_v1",
    )

    assert summary["state"] == "SHADOW_READY"
    assert summary["strategy"]["display_name"] == "GuavaMango"
    assert summary["candidate"]["symbol"] == "IWM"
    assert summary["evidence"]["status"] == "PASS"
    assert summary["evidence"]["metrics"]["sample_count"] == 95
    assert Decimal(summary["evidence"]["metrics"]["profit_factor"]) > 2
    assert summary["risk"]["status"] == "PASS"
    assert Decimal(summary["payoff"]["operational_ratio"]) >= 3
    assert Decimal(summary["payoff"]["modeled_costs"]) > Decimal("0.01")
    assert summary["warrant"]["intent"]["asset_class"] == "equity"
    assert summary["warrant"]["intent"]["order_class"] == "bracket"
    assert summary["dry_run"]["submitted"] is False
    assert summary["broker"]["order_sent"] is False
    assert gateway.calls[0] == "preflight"
    assert gateway.calls.count("stock_snapshot") == 1
    assert gateway.calls.count("dry_run_order") == 1
    assert len([call for call in gateway.calls if call.startswith("stock_bars:")]) == len(
        EQUITY_UNIVERSE
    )


@pytest.mark.asyncio
async def test_live_shadow_fails_closed_when_real_research_dataset_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway = FakeLiveGateway()
    monkeypatch.setenv("AFTERIMAGE_RESEARCH_DATASET_PATH", str(tmp_path / "does-not-exist.json"))
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'missing-research.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )

    summary = await runtime.run_live_shadow(
        gateway,
        AgentDesk(NeverModelGateway()),  # type: ignore[arg-type]
        gateway.account_hash,
    )

    assert summary["state"] == "REJECTED"
    assert summary["events"][-1]["payload"]["reasons"] == ["REAL_RESEARCH_DATASET_UNAVAILABLE"]
    assert gateway.calls == ["preflight", "stock_bars"]


@pytest.mark.asyncio
async def test_live_shadow_connects_every_runtime_module_without_an_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)
    gateway = FakeLiveGateway()
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'live.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )

    summary = await runtime.run_live_shadow(gateway, desk, gateway.account_hash, symbol="SPY")

    assert summary["mode"] == "live-shadow"
    assert summary["state"] == "SHADOW_READY"
    assert summary["broker"]["connected"] is True
    assert summary["broker"]["order_sent"] is False
    assert summary["agent_provenance"]["live_inference"] is True
    assert summary["dry_run"]["dry_run"] is True
    assert summary["risk"]["status"] == "PASS"
    assert summary["risk"]["strategy_manifest_hash"] == runtime._strategy_authority_hash(
        runtime.registry.load("opening_range_failure_v1")
    )
    assert summary["warrant"]["intent"]["account_id_hash"] == gateway.account_hash
    assert summary["snapshot"]["cutoff"] == "2026-09-04T14:00:00Z"
    assert len(summary["snapshot"]["records"]) == 6
    assert gateway.calls == [
        "preflight",
        "stock_bars",
        "option_contracts",
        "option_chain",
        "dry_run_option_order",
    ]


@pytest.mark.asyncio
async def test_live_cycle_connects_warrant_directly_to_execution_when_explicitly_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)
    gateway = FakeLiveGateway()
    gateway.execution_enabled = True
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'execution-cycle.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    monkeypatch.setenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setattr(
        runtime,
        "_require_promoted_strategy",
        lambda *_: {"status": "PROMOTED", "champion_manifest_hash": "f" * 64},
    )

    summary = await runtime.run_live_cycle(
        gateway,
        desk,
        gateway.account_hash,
        symbol="SPY",
        execute=True,
    )

    assert summary["mode"] == "live-paper"
    assert summary["state"] == "WORKING"
    assert summary["broker"]["order_sent"] is True
    assert summary["broker_order"]["broker_order_id"] == "paper-order-test"
    assert gateway.calls.count("place_option_order") == 1


@pytest.mark.asyncio
async def test_standalone_shadow_execution_enters_managed_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)
    gateway = FakeLiveGateway()
    gateway.execution_enabled = True
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'standalone-execution.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    monkeypatch.setenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setattr(
        runtime,
        "_require_promoted_strategy",
        lambda *_: {"status": "PROMOTED", "champion_manifest_hash": "f" * 64},
    )
    shadow = await runtime.run_live_shadow(gateway, desk, gateway.account_hash)

    submitted = await runtime.submit_shadow_session(
        gateway,
        gateway.account_hash,
        shadow["session_id"],
        ExecutionWarrant.model_validate(shadow["warrant"]),
    )

    assert submitted["state"] == "WORKING"
    assert submitted["broker"]["order_sent"] is True
    assert shadow["session_id"] in runtime.managed_session_ids()


@pytest.mark.asyncio
async def test_indeterminate_shadow_submit_is_recoverable_by_manager(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)

    class RecoveringGateway(FakeLiveGateway):
        def __init__(self) -> None:
            super().__init__()
            self.lookup_count = 0

        async def place_option_order(self, intent: Any, client_order_id: str) -> dict[str, Any]:
            del intent, client_order_id
            self.calls.append("place_option_order")
            raise RuntimeError("timeout after submission")

        async def order_by_client_id(self, client_order_id: str) -> dict[str, Any]:
            self.calls.append("order_by_client_id")
            self.lookup_count += 1
            if self.lookup_count <= 4:
                return {}
            return {
                "id": "recovered-paper-entry",
                "client_order_id": client_order_id,
                "status": "accepted",
            }

    gateway = RecoveringGateway()
    gateway.execution_enabled = True
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'recovered-execution.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    monkeypatch.setenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setattr(
        runtime,
        "_require_promoted_strategy",
        lambda *_: {"status": "PROMOTED", "champion_manifest_hash": "f" * 64},
    )
    shadow = await runtime.run_live_shadow(gateway, desk, gateway.account_hash)

    ambiguous = await runtime.submit_shadow_session(
        gateway,
        gateway.account_hash,
        shadow["session_id"],
        ExecutionWarrant.model_validate(shadow["warrant"]),
    )
    recovered = await runtime.manage_live_position(
        gateway, gateway.account_hash, shadow["session_id"]
    )

    assert ambiguous["state"] == "AMBIGUOUS"
    assert ambiguous["broker_order"]["status"] == "submitting"
    assert recovered["state"] == "WORKING"
    assert runtime.repository.broker_orders(shadow["session_id"])[-1]["id"] == (
        "recovered-paper-entry"
    )


@pytest.mark.asyncio
async def test_unpromoted_strategy_cannot_reach_paper_submission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)
    gateway = FakeLiveGateway()
    gateway.execution_enabled = True
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'unpromoted.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    monkeypatch.setenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "true")

    def reject_unpromoted(*_: Any) -> dict[str, Any]:
        raise ExecutionError("STRATEGY_NOT_PROMOTED:NO_CHAMPION")

    monkeypatch.setattr(runtime, "_require_promoted_strategy", reject_unpromoted)

    summary = await runtime.run_live_cycle(gateway, desk, gateway.account_hash, execute=True)

    assert summary["state"] == "INSUFFICIENT_EVIDENCE"
    assert summary["promotion"]["status"] == "BLOCKED"
    assert summary["events"][-1]["payload"]["order_sent"] is False
    assert "place_option_order" not in gateway.calls


@pytest.mark.asyncio
async def test_live_shadow_deduplicates_a_frozen_snapshot_before_model_or_option_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)
    gateway = FakeLiveGateway()
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'dedupe.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))

    first = await runtime.run_live_shadow(gateway, desk, gateway.account_hash)
    call_count = len(gateway.calls)
    second = await runtime.run_live_shadow(
        gateway,
        AgentDesk(NeverModelGateway()),  # type: ignore[arg-type]
        gateway.account_hash,
    )

    assert first["state"] == "SHADOW_READY"
    assert second["state"] == "NO_SIGNAL"
    assert second["events"][-1]["payload"]["reason"] == "SNAPSHOT_ALREADY_ANALYZED"
    assert gateway.calls[call_count:] == ["preflight", "stock_bars"]


@pytest.mark.asyncio
async def test_durable_manager_reconciles_fill_and_submits_signed_risk_reducing_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)

    class ManagedGateway(FakeLiveGateway):
        def __init__(self) -> None:
            super().__init__()
            self.entry_submitted = False
            self.position_quantity = 0

        async def preflight(
            self, expected: str, allow_existing_exposure: bool | None = None
        ) -> AccountPreflight:
            checked = await super().preflight(expected, allow_existing_exposure)
            if self.entry_submitted:
                return checked.model_copy(
                    update={
                        "positions": (
                            {
                                "symbol": "SPY260908P00650000",
                                "qty": str(self.position_quantity),
                                "unrealized_pl": "116",
                            },
                            {
                                "symbol": "SPY260908P00644000",
                                "qty": str(-self.position_quantity),
                                "unrealized_pl": "0",
                            },
                        )
                    }
                )
            return checked

        async def positions(self) -> tuple[dict[str, Any], ...]:
            return (
                {"symbol": "SPY260908P00650000", "qty": str(self.position_quantity)},
                {"symbol": "SPY260908P00644000", "qty": str(-self.position_quantity)},
            )

        async def option_quotes(self, **_: Any) -> dict[str, Any]:
            return {
                "quotes": {
                    "SPY260908P00650000": {"bp": "1.80", "ap": "1.82", "t": "2026-09-04T14:00:00Z"},
                    "SPY260908P00644000": {"bp": "0.10", "ap": "0.12", "t": "2026-09-04T14:00:00Z"},
                }
            }

        async def place_option_order(self, intent: Any, client_order_id: str) -> dict[str, Any]:
            self.calls.append("place_option_order")
            if not self.entry_submitted:
                self.entry_submitted = True
                self.position_quantity = int(intent.quantity)
                return {
                    "id": "paper-entry",
                    "client_order_id": client_order_id,
                    "status": "accepted",
                }
            return {
                "id": "paper-exit",
                "client_order_id": client_order_id,
                "status": "filled",
                "filled_avg_price": "1.68",
            }

        async def order_by_client_id(self, client_order_id: str) -> dict[str, Any]:
            self.calls.append("order_by_client_id")
            return {
                "id": "paper-entry",
                "client_order_id": client_order_id,
                "status": "filled",
                "filled_avg_price": "0.51",
            }

    gateway = ManagedGateway()
    gateway.execution_enabled = True
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'managed.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    monkeypatch.setenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setattr(
        runtime,
        "_require_promoted_strategy",
        lambda *_: {"status": "PROMOTED", "champion_manifest_hash": "f" * 64},
    )

    working = await runtime.run_live_cycle(gateway, desk, gateway.account_hash, execute=True)
    completed = await runtime.manage_live_position(
        gateway, gateway.account_hash, working["session_id"]
    )

    assert working["state"] == "WORKING"
    assert completed["state"] == "AUTOPSY"
    assert completed["watchdog_assessment"]["action"] == "EXIT_TARGET"
    assert completed["broker_autopsy"]["pnl_status"] == "broker_fill_gross_only"
    expected_gross = (
        (Decimal("1.68") - Decimal("0.51"))
        * Decimal(100)
        * working["warrant"]["intent"]["quantity"]
    )
    assert Decimal(completed["broker_autopsy"]["gross_pnl"]) == expected_gross
    assert gateway.calls.count("place_option_order") == 2


@pytest.mark.asyncio
async def test_durable_manager_cancels_an_unfilled_entry_after_cutoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fixture_research(monkeypatch)

    class CutoffGateway(FakeLiveGateway):
        def __init__(self) -> None:
            super().__init__()
            self.after_cutoff = False
            self.cancelled = False

        async def preflight(
            self, expected: str, allow_existing_exposure: bool | None = None
        ) -> AccountPreflight:
            checked = await super().preflight(expected, allow_existing_exposure)
            if self.after_cutoff:
                return checked.model_copy(
                    update={
                        "clock": {
                            **checked.clock,
                            "timestamp": "2026-09-04T10:06:00-04:00",
                        }
                    }
                )
            return checked

        async def order_by_client_id(self, client_order_id: str) -> dict[str, Any]:
            self.calls.append("order_by_client_id")
            return {
                "id": "paper-order-test",
                "client_order_id": client_order_id,
                "status": "canceled" if self.cancelled else "accepted",
            }

        async def cancel_order(self, order_id: str) -> dict[str, Any]:
            self.calls.append("cancel_order")
            assert order_id == "paper-order-test"
            self.cancelled = True
            return {}

    gateway = CutoffGateway()
    gateway.execution_enabled = True
    runtime = Coordinator(
        Database(f"sqlite:///{tmp_path / 'cutoff.db'}"),
        signing_key_path=tmp_path / "warrant.pem",
    )
    desk = AgentDesk(RecordedGateway({role: report(role) for role in AgentRole}))
    monkeypatch.setenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.setattr(
        runtime,
        "_require_promoted_strategy",
        lambda *_: {"status": "PROMOTED", "champion_manifest_hash": "f" * 64},
    )

    working = await runtime.run_live_cycle(gateway, desk, gateway.account_hash, execute=True)
    gateway.after_cutoff = True
    cancelled = await runtime.manage_live_position(
        gateway, gateway.account_hash, working["session_id"]
    )

    assert working["state"] == "WORKING"
    assert cancelled["state"] == "REJECTED"
    assert cancelled["entry_order_management"]["cancel_requested"] is True
    assert cancelled["events"][-1]["payload"]["reason"] == "ENTRY_CUTOFF_CANCELLED"
    assert gateway.calls.count("cancel_order") == 1
