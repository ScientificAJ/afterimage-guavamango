from __future__ import annotations

import os

import pytest

from afterimage.execution.mcp_client import MCPClient, MCPProcess


def test_mcp_child_environment_does_not_inherit_unrelated_parent_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEATHERLESS_API_KEY", "must-not-cross-boundary")
    monkeypatch.setenv("AFTERIMAGE_EXECUTION_TOKEN", "must-not-cross-boundary")
    process = MCPProcess(env={"ALPACA_API_KEY": "paper-key", "ALPACA_SECRET_KEY": "paper-secret"})

    environment = MCPClient(process)._child_environment()

    assert environment["ALPACA_API_KEY"] == "paper-key"
    assert environment["ALPACA_PAPER_TRADE"] == "true"
    assert "FEATHERLESS_API_KEY" not in environment
    assert "AFTERIMAGE_EXECUTION_TOKEN" not in environment
    if "PATH" in os.environ:
        assert environment["PATH"] == os.environ["PATH"]
