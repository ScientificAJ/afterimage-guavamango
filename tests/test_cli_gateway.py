from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from afterimage.contracts.models import ExecutionIntent, OptionLeg
from afterimage.execution.alpaca_gateway import PreflightFailure
from afterimage.execution.cli_gateway import (
    AlpacaCLIGateway,
    CLICommandError,
    CLIResult,
    SubprocessCLIRunner,
)


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    async def run(self, *arguments: str) -> CLIResult:
        self.calls.append(arguments)
        value = self.responses.get(arguments)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise AssertionError(f"unexpected CLI call: {arguments}")
        return CLIResult(stdout=value if isinstance(value, str) else "", json=value)


def account_payload() -> dict[str, Any]:
    return {
        "id": "paper-account-id",
        "status": "ACTIVE",
        "equity": "100000",
        "last_equity": "100000",
        "cash": "100000",
        "options_buying_power": "100000",
        "options_approved_level": 3,
        "options_trading_level": 3,
        "trading_blocked": False,
    }


def read_responses() -> dict[tuple[str, ...], Any]:
    return {
        ("version",): "0.0.14\n",
        ("doctor",): "Connectivity:\n  Trading:  https://paper-api.alpaca.markets\n",
        ("account", "get", "--quiet"): account_payload(),
        ("account", "config", "get", "--quiet"): {"suspend_trade": False},
        ("order", "list", "--status", "open", "--limit", "100", "--quiet"): [],
        ("position", "list", "--quiet"): [],
        ("clock", "--quiet"): {
            "is_open": False,
            "timestamp": "2026-09-04T01:22:37-04:00",
            "next_open": "2026-09-04T09:30:00-04:00",
        },
    }


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_preflight_pins_paper_account_without_exposing_raw_id(tmp_path: Path) -> None:
    runner = FakeRunner(read_responses())
    binding = tmp_path / "account.sha256"
    gateway = AlpacaCLIGateway(runner=runner, account_binding_path=binding)

    run(gateway.connect())
    expected = run(gateway.bind_account())
    result = run(gateway.preflight(expected))

    assert expected == hashlib.sha256(b"paper-account-id").hexdigest()
    assert json.loads(binding.read_text())["account_id_hash"] == expected
    assert json.loads(binding.read_text())["trading_endpoint"] == "https://paper-api.alpaca.markets"
    assert binding.stat().st_mode & 0o777 == 0o600
    assert result.account.account_id_hash == expected
    assert result.account.options_trading_level == 3
    assert result.open_orders == ()
    assert result.positions == ()
    assert "paper-account-id" not in result.model_dump_json()


def test_preflight_rejects_a_different_account_before_any_execution(tmp_path: Path) -> None:
    runner = FakeRunner(read_responses())
    gateway = AlpacaCLIGateway(runner=runner, account_binding_path=tmp_path / "account.sha256")

    run(gateway.connect())
    with pytest.raises(PreflightFailure, match="ACCOUNT_ID_MISMATCH"):
        run(gateway.preflight("0" * 64))


def test_preflight_rejects_unknown_existing_exposure(tmp_path: Path) -> None:
    responses = read_responses()
    responses[("position", "list", "--quiet")] = [{"symbol": "SPY", "qty": "1"}]
    gateway = AlpacaCLIGateway(
        runner=FakeRunner(responses), account_binding_path=tmp_path / "account.sha256"
    )
    expected = hashlib.sha256(b"paper-account-id").hexdigest()

    run(gateway.connect())
    with pytest.raises(PreflightFailure, match="UNKNOWN_PAPER_EXPOSURE"):
        run(gateway.preflight(expected))


@pytest.mark.parametrize(
    ("command", "payload", "reason"),
    [
        (
            ("order", "list", "--status", "open", "--limit", "100", "--quiet"),
            {},
            "MALFORMED_OPEN_ORDERS",
        ),
        (("position", "list", "--quiet"), {"unexpected": []}, "MALFORMED_POSITIONS"),
    ],
)
def test_preflight_rejects_malformed_exposure_payloads(
    tmp_path: Path,
    command: tuple[str, ...],
    payload: dict[str, Any],
    reason: str,
) -> None:
    responses = read_responses()
    responses[command] = payload
    gateway = AlpacaCLIGateway(
        runner=FakeRunner(responses), account_binding_path=tmp_path / "account.sha256"
    )
    expected = hashlib.sha256(b"paper-account-id").hexdigest()

    run(gateway.connect())
    with pytest.raises(PreflightFailure, match=reason):
        run(gateway.preflight(expected))


@pytest.mark.parametrize(
    ("command", "payload", "reason"),
    [
        (
            ("order", "list", "--status", "open", "--limit", "100", "--quiet"),
            {"orders": [], "items": [{"id": "hidden-order"}]},
            "MALFORMED_OPEN_ORDERS",
        ),
        (
            ("position", "list", "--quiet"),
            {"positions": [], "items": [{"symbol": "SPY", "qty": "1"}]},
            "MALFORMED_POSITIONS",
        ),
    ],
)
def test_preflight_rejects_ambiguous_exposure_envelopes(
    tmp_path: Path,
    command: tuple[str, ...],
    payload: dict[str, Any],
    reason: str,
) -> None:
    responses = read_responses()
    responses[command] = payload
    gateway = AlpacaCLIGateway(
        runner=FakeRunner(responses), account_binding_path=tmp_path / "account.sha256"
    )

    run(gateway.connect())
    with pytest.raises(PreflightFailure, match=reason):
        run(gateway.preflight(hashlib.sha256(b"paper-account-id").hexdigest()))


def test_gateway_rejects_a_non_paper_cli_profile(tmp_path: Path) -> None:
    responses = read_responses()
    responses[("doctor",)] = "Connectivity:\n  Trading: https://api.alpaca.markets\n"
    gateway = AlpacaCLIGateway(
        runner=FakeRunner(responses), account_binding_path=tmp_path / "account.sha256"
    )

    with pytest.raises(PreflightFailure, match="ALPACA_CLI_NOT_PAPER_ENDPOINT"):
        run(gateway.connect())


def test_runtime_positions_reject_malformed_payload(tmp_path: Path) -> None:
    responses = read_responses()
    responses[("position", "list", "--quiet")] = {"unexpected": []}
    gateway = AlpacaCLIGateway(
        runner=FakeRunner(responses), account_binding_path=tmp_path / "account.sha256"
    )

    with pytest.raises(PreflightFailure, match="MALFORMED_POSITIONS"):
        run(gateway.positions())


def test_live_execution_is_locked_even_when_a_valid_intent_exists(tmp_path: Path) -> None:
    runner = FakeRunner(read_responses())
    gateway = AlpacaCLIGateway(
        runner=runner,
        account_binding_path=tmp_path / "account.sha256",
        execution_enabled=False,
    )
    now = datetime(2026, 9, 4, tzinfo=UTC)
    intent = ExecutionIntent(
        account_id_hash="a" * 64,
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=uuid4(),
        legs=(
            OptionLeg(
                symbol="SPY260908P00650000",
                ratio_qty=1,
                side="buy",
                position_intent="buy_to_open",
                bid=Decimal("0.72"),
                ask=Decimal("0.75"),
                quote_at=now,
            ),
            OptionLeg(
                symbol="SPY260908P00644000",
                ratio_qty=1,
                side="sell",
                position_intent="sell_to_open",
                bid=Decimal("0.05"),
                ask=Decimal("0.07"),
                quote_at=now,
            ),
        ),
        quantity=1,
        limit_price=Decimal("0.68"),
    )

    with pytest.raises(PreflightFailure, match="EXECUTION_DISABLED"):
        run(gateway.place_option_order(intent, "aft-test"))
    assert not any(call[:2] == ("order", "submit") for call in runner.calls)


def test_enabled_mutation_reattests_paper_endpoint_and_bound_account(
    tmp_path: Path,
) -> None:
    responses = read_responses()
    now = datetime(2026, 9, 4, tzinfo=UTC)
    intent = ExecutionIntent(
        account_id_hash=hashlib.sha256(b"paper-account-id").hexdigest(),
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=uuid4(),
        legs=(
            OptionLeg(
                symbol="SPY260908P00650000",
                ratio_qty=1,
                side="buy",
                position_intent="buy_to_open",
                bid=Decimal("0.72"),
                ask=Decimal("0.75"),
                quote_at=now,
            ),
            OptionLeg(
                symbol="SPY260908P00644000",
                ratio_qty=1,
                side="sell",
                position_intent="sell_to_open",
                bid=Decimal("0.05"),
                ask=Decimal("0.07"),
                quote_at=now,
            ),
        ),
        quantity=1,
        limit_price=Decimal("0.68"),
    )
    order_command = tuple(AlpacaCLIGateway._order_arguments(intent, "aft-test"))
    responses[order_command] = {"id": "paper-order"}
    runner = FakeRunner(responses)
    binding = tmp_path / "account.sha256"
    gateway = AlpacaCLIGateway(runner=runner, account_binding_path=binding, execution_enabled=True)

    run(gateway.connect())
    run(gateway.bind_account())
    runner.calls.clear()
    assert run(gateway.place_option_order(intent, "aft-test"))["id"] == "paper-order"

    assert runner.calls[-3:] == [
        ("doctor",),
        ("account", "get", "--quiet"),
        order_command,
    ]


def test_equity_bracket_order_arguments_are_exact_and_dry_runnable(tmp_path: Path) -> None:
    intent = ExecutionIntent(
        account_id_hash="a" * 64,
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=uuid4(),
        asset_class="equity",
        symbol="QQQ",
        side="buy",
        quantity=25,
        limit_price=Decimal("100.00"),
        take_profit_price=Decimal("103.40"),
        stop_price=Decimal("99.00"),
        order_class="bracket",
    )
    command = tuple(AlpacaCLIGateway._order_arguments(intent, "aft-equity")) + ("--dry-run",)
    runner = FakeRunner({command: {"dry_run": True, "symbol": "QQQ"}})
    gateway = AlpacaCLIGateway(runner=runner, account_binding_path=tmp_path / "account.sha256")

    result = run(gateway.dry_run_order(intent, "aft-equity"))

    assert result["dry_run"] is True
    assert "--legs" not in command
    assert command[command.index("--symbol") + 1] == "QQQ"
    assert json.loads(command[command.index("--take-profit") + 1]) == {"limit_price": "103.40"}
    assert json.loads(command[command.index("--stop-loss") + 1]) == {"stop_price": "99.00"}


def test_stock_snapshot_uses_the_configured_feed(tmp_path: Path) -> None:
    command = ("data", "snapshot", "--symbol", "QQQ", "--feed", "iex", "--quiet")
    runner = FakeRunner({command: {"symbol": "QQQ", "latest_quote": {"ap": 100}}})
    gateway = AlpacaCLIGateway(runner=runner, account_binding_path=tmp_path / "account.sha256")

    assert run(gateway.stock_snapshot("qqq"))["symbol"] == "QQQ"


def test_equity_market_close_arguments_are_simple_and_reduce_only() -> None:
    intent = ExecutionIntent(
        account_id_hash="a" * 64,
        strategy_manifest_hash="b" * 64,
        evidence_commit_hash="c" * 64,
        risk_decision_id=uuid4(),
        asset_class="equity",
        symbol="QQQ",
        side="sell",
        quantity=25,
        limit_price=Decimal(0),
        order_class="simple",
        order_type="market",
        reduce_only=True,
    )

    command = AlpacaCLIGateway._order_arguments(intent, "aft-close")

    assert command == [
        "order",
        "submit",
        "--symbol",
        "QQQ",
        "--qty",
        "25",
        "--side",
        "sell",
        "--type",
        "market",
        "--time-in-force",
        "day",
        "--client-order-id",
        "aft-close",
        "--quiet",
    ]


def test_binding_reader_rejects_symlink_and_insecure_mode(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text(
        json.dumps(
            {
                "schema": "afterimage-alpaca-binding-v1",
                "account_id_hash": "a" * 64,
                "trading_endpoint": "https://paper-api.alpaca.markets",
            }
        )
    )
    target.chmod(0o600)
    link = tmp_path / "binding.json"
    link.symlink_to(target)
    gateway = AlpacaCLIGateway(runner=FakeRunner({}), account_binding_path=link)

    with pytest.raises(PreflightFailure, match="ALPACA_ACCOUNT_BINDING_INVALID"):
        gateway.bound_account_hash()

    link.unlink()
    link.write_text(target.read_text())
    link.chmod(0o666)
    with pytest.raises(PreflightFailure, match="ALPACA_ACCOUNT_BINDING_INVALID"):
        gateway.bound_account_hash()


def test_cli_transport_error_never_echoes_sensitive_output() -> None:
    error = CLICommandError(
        command=("account", "get"),
        returncode=1,
        stderr="Authorization: Bearer secret-token",
    )

    assert "secret-token" not in str(error)
    assert "CLI_COMMAND_FAILED" in str(error)


def test_cli_child_environment_does_not_inherit_unrelated_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATHERLESS_API_KEY", "must-not-cross-boundary")
    monkeypatch.setenv("AFTERIMAGE_EXECUTION_TOKEN", "must-not-cross-boundary")
    runner = SubprocessCLIRunner("/tmp/alpaca")

    environment = runner._child_environment()

    assert environment["ALPACA_PAPER_TRADE"] == "true"
    assert "FEATHERLESS_API_KEY" not in environment
    assert "AFTERIMAGE_EXECUTION_TOKEN" not in environment


def test_cli_profile_is_snapshotted_into_a_private_process_local_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "alpaca-source"
    profiles = source / "profiles"
    profiles.mkdir(parents=True)
    config = source / "config.yaml"
    profile = profiles / "afterimage-paper.yaml"
    config.write_text("active_profile: afterimage-paper\n")
    profile.write_text("paper: true\nmarker: original\n")
    config.chmod(0o600)
    profile.chmod(0o600)
    monkeypatch.setenv("ALPACA_CONFIG_DIR", str(source))
    runner = SubprocessCLIRunner("/tmp/alpaca")

    runner.freeze_configuration()
    locked = Path(runner._child_environment()["ALPACA_CONFIG_DIR"])
    profile.write_text("paper: false\nmarker: switched\n")

    assert locked != source
    assert locked.stat().st_mode & 0o777 == 0o700
    assert (locked / "profiles" / "afterimage-paper.yaml").read_text() == (
        "paper: true\nmarker: original\n"
    )
    assert (locked / "profiles" / "afterimage-paper.yaml").stat().st_mode & 0o777 == 0o600
    runner.close()
    assert not locked.exists()


def test_cli_binary_checksum_mismatch_fails_before_execution(tmp_path: Path) -> None:
    executable = tmp_path / "alpaca"
    executable.write_bytes(b"not-the-pinned-binary")
    executable.chmod(0o755)
    runner = SubprocessCLIRunner(executable, expected_sha256="0" * 64)

    with pytest.raises(CLICommandError, match="binary-integrity"):
        run(runner.run("version"))


def test_stock_bars_collects_every_page_without_dropping_provenance() -> None:
    first = (
        "data",
        "bars",
        "--symbol",
        "SPY",
        "--start",
        "2026-07-01T13:30:00+00:00",
        "--end",
        "2026-09-01T15:00:00+00:00",
        "--timeframe",
        "5Min",
        "--feed",
        "iex",
        "--limit",
        "10000",
        "--quiet",
    )
    second = (*first[:-1], "--page-token", "next-2", "--quiet")
    runner = FakeRunner(
        {
            first: {"bars": [{"t": "2026-07-01T13:30:00Z", "c": 1}], "next_page_token": "next-2"},
            second: {"bars": [{"t": "2026-09-01T13:30:00Z", "c": 2}], "next_page_token": ""},
        }
    )
    gateway = AlpacaCLIGateway(runner=runner)

    bars = run(
        gateway.stock_bars(
            "SPY",
            datetime(2026, 7, 1, 13, 30, tzinfo=UTC),
            datetime(2026, 9, 1, 15, 0, tzinfo=UTC),
        )
    )

    assert bars == [
        {"t": "2026-07-01T13:30:00Z", "c": 1},
        {"t": "2026-09-01T13:30:00Z", "c": 2},
    ]
    assert runner.calls == [first, second]


def test_option_contracts_support_inactive_history_and_fail_closed_pagination() -> None:
    first = (
        "option",
        "contracts",
        "--underlying-symbols",
        "SPY",
        "--status",
        "inactive",
        "--limit",
        "10000",
        "--quiet",
    )
    second = (*first[:-1], "--page-token", "contracts-2", "--quiet")
    runner = FakeRunner(
        {
            first: {
                "option_contracts": [{"symbol": "SPY260702P00700000"}],
                "next_page_token": "contracts-2",
            },
            second: {
                "option_contracts": [{"symbol": "SPY260702P00699000"}],
                "next_page_token": None,
            },
        }
    )
    gateway = AlpacaCLIGateway(runner=runner)

    contracts = run(gateway.option_contracts("SPY", status="inactive", limit=10000))

    assert [contract["symbol"] for contract in contracts] == [
        "SPY260702P00700000",
        "SPY260702P00699000",
    ]
    assert runner.calls == [first, second]


def test_option_bars_collect_every_symbol_and_page() -> None:
    first = (
        "data",
        "option",
        "bars",
        "--symbols",
        "SPY260702P00700000,SPY260702P00699000",
        "--start",
        "2026-07-01T13:55:00+00:00",
        "--end",
        "2026-07-01T14:45:00+00:00",
        "--timeframe",
        "5Min",
        "--limit",
        "10000",
        "--quiet",
    )
    second = (*first[:-1], "--page-token", "bars-2", "--quiet")
    runner = FakeRunner(
        {
            first: {
                "bars": {"SPY260702P00700000": [{"t": "2026-07-01T13:55:00Z", "c": 1.2}]},
                "next_page_token": "bars-2",
            },
            second: {
                "bars": {"SPY260702P00699000": [{"t": "2026-07-01T14:00:00Z", "c": 0.4}]},
                "next_page_token": "",
            },
        }
    )
    gateway = AlpacaCLIGateway(runner=runner)

    bars = run(
        gateway.option_bars(
            ("SPY260702P00700000", "SPY260702P00699000"),
            datetime(2026, 7, 1, 13, 55, tzinfo=UTC),
            datetime(2026, 7, 1, 14, 45, tzinfo=UTC),
        )
    )

    assert bars == [
        {"symbol": "SPY260702P00700000", "t": "2026-07-01T13:55:00Z", "c": 1.2},
        {"symbol": "SPY260702P00699000", "t": "2026-07-01T14:00:00Z", "c": 0.4},
    ]
    assert runner.calls == [first, second]
