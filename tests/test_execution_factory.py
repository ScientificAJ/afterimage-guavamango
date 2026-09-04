from __future__ import annotations

import json
from pathlib import Path

import pytest

from afterimage.execution.alpaca_gateway import AlpacaGateway, PreflightFailure
from afterimage.execution.cli_gateway import AlpacaCLIGateway
from afterimage.execution.factory import build_alpaca_gateway, expected_account_id_hash


def test_factory_uses_official_cli_without_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setenv("AFTERIMAGE_ALPACA_TRANSPORT", "cli")
    monkeypatch.setenv("AFTERIMAGE_ALPACA_CLI", "/tmp/alpaca")

    gateway = build_alpaca_gateway()

    assert isinstance(gateway, AlpacaCLIGateway)
    assert gateway.execution_enabled is False


def test_expected_account_hash_reads_private_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binding = tmp_path / "account.sha256"
    binding.write_text(
        json.dumps(
            {
                "schema": "afterimage-alpaca-binding-v1",
                "account_id_hash": "a" * 64,
                "trading_endpoint": "https://paper-api.alpaca.markets",
            }
        )
    )
    binding.chmod(0o600)
    monkeypatch.setenv("AFTERIMAGE_ACCOUNT_BINDING_PATH", str(binding))

    assert expected_account_id_hash() == "a" * 64


def test_expected_account_hash_rejects_symlink_and_insecure_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    binding = tmp_path / "binding.json"
    binding.symlink_to(target)
    monkeypatch.setenv("AFTERIMAGE_ACCOUNT_BINDING_PATH", str(binding))

    with pytest.raises(PreflightFailure, match="ALPACA_ACCOUNT_BINDING_INVALID"):
        expected_account_id_hash()

    binding.unlink()
    binding.write_text(target.read_text())
    binding.chmod(0o666)
    with pytest.raises(PreflightFailure, match="ALPACA_ACCOUNT_BINDING_INVALID"):
        expected_account_id_hash()


def test_expected_account_hash_rejects_missing_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AFTERIMAGE_ACCOUNT_BINDING_PATH", str(tmp_path / "missing"))

    with pytest.raises(PreflightFailure, match="ALPACA_ACCOUNT_NOT_BOUND"):
        expected_account_id_hash()


def test_mcp_transport_inherits_the_default_deny_execution_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AFTERIMAGE_ALPACA_TRANSPORT", "mcp")
    monkeypatch.setenv("ALPACA_API_KEY", "paper-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "paper-secret")
    monkeypatch.delenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", raising=False)

    gateway = build_alpaca_gateway()

    assert isinstance(gateway, AlpacaGateway)
    assert gateway.execution_enabled is False


def test_mcp_exposure_parser_rejects_ambiguous_containers() -> None:
    with pytest.raises(PreflightFailure, match="MALFORMED_POSITIONS"):
        AlpacaGateway._items(
            {"items": [], "positions": [{"symbol": "SPY", "qty": "1"}]},
            "MALFORMED_POSITIONS",
        )
