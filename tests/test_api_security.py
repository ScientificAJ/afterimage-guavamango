from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from afterimage.api import routes
from afterimage.api.main import app, operator_auth_failure, remote_request_allowed


def test_execution_endpoint_fails_closed_without_a_server_side_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AFTERIMAGE_ENABLE_PAPER_EXECUTION", "true")
    monkeypatch.delenv("AFTERIMAGE_EXECUTION_TOKEN", raising=False)

    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            routes.execute(
                "session",
                routes.ExecuteRequest(warrant_id="warrant"),
                x_afterimage_execution_token=None,
            )
        )

    assert failure.value.status_code == 503
    assert failure.value.detail == "paper execution API is not armed"


def test_warrant_artifacts_are_redacted_from_api_responses() -> None:
    artifacts = [
        {
            "kind": "warrant",
            "hash": "h" * 64,
            "payload": {"warrant_id": "secret-capability", "nonce": "nonce", "signature": "sig"},
            "created_at": "2026-09-04T00:00:00Z",
        },
        {"kind": "frozen_snapshot", "hash": "s" * 64, "payload": {"safe": True}},
    ]

    redacted = routes.redact_artifacts(artifacts)

    assert redacted[0] == {"kind": "warrant", "hash": "h" * 64, "redacted": True}
    assert redacted[1]["payload"] == {"safe": True}


def test_public_error_detail_never_reflects_external_secret_text() -> None:
    detail = routes.public_error_detail(
        RuntimeError("upstream failed Authorization: Bearer extremely-secret-token")
    )

    assert detail == "OPERATION_BLOCKED"
    assert "secret" not in detail.lower()


def test_public_error_detail_preserves_bounded_machine_reason() -> None:
    assert routes.public_error_detail(RuntimeError("ACCOUNT_ID_MISMATCH")) == "ACCOUNT_ID_MISMATCH"


def test_remote_operator_endpoints_fail_closed_without_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AFTERIMAGE_REQUIRE_OPERATOR_AUTH", "true")
    monkeypatch.delenv("AFTERIMAGE_OPERATOR_TOKEN", raising=False)

    with pytest.raises(HTTPException) as failure:
        routes.require_operator_token(None)

    assert failure.value.status_code == 503


def test_direct_remote_uvicorn_binding_is_denied_when_operator_auth_is_not_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AFTERIMAGE_REQUIRE_OPERATOR_AUTH", raising=False)

    assert remote_request_allowed("203.0.113.10", "localhost") is False
    assert remote_request_allowed("127.0.0.1", "localhost") is True
    assert remote_request_allowed("127.0.0.1", "public.example") is False


def test_generated_api_documentation_is_disabled() -> None:
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None


def test_operator_auth_is_enforced_by_middleware_for_every_non_health_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AFTERIMAGE_REQUIRE_OPERATOR_AUTH", "true")
    monkeypatch.setenv("AFTERIMAGE_OPERATOR_TOKEN", "operator-secret")

    assert operator_auth_failure(None) == (403, "operator authorization failed")
    assert operator_auth_failure("wrong") == (403, "operator authorization failed")
    assert operator_auth_failure("operator-secret") is None


def test_session_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "MAX_CACHED_SESSIONS", 2)
    routes.SESSION_SUMMARIES.clear()
    routes.EVENT_STREAMS.clear()

    for index in range(3):
        routes.remember_session({"session_id": f"session-{index}", "events": [{"sequence": index}]})

    assert list(routes.SESSION_SUMMARIES) == ["session-1", "session-2"]
    assert list(routes.EVENT_STREAMS) == ["session-1", "session-2"]


def test_public_summary_replaces_warrant_capabilities_with_fingerprints() -> None:
    summary = {
        "session_id": "session",
        "events": [],
        "warrant": {
            "warrant_id": "capability-id",
            "intent_hash": "i" * 64,
            "risk_vector_hash": "r" * 64,
            "expires_at": "2026-09-04T10:00:00Z",
            "nonce": "secret-nonce",
            "signature": "secret-signature",
            "public_key": "public-key",
            "intent": {"account_id_hash": "a" * 64},
        },
    }

    public = routes.public_summary(summary)

    assert public["warrant"]["redacted"] is True
    assert public["warrant"]["intent_hash"] == "i" * 64
    assert public["warrant"]["nonce"] != "secret-nonce"
    assert "warrant_id" not in public["warrant"]
    assert "intent" not in public["warrant"]


def test_shadow_request_can_select_a_configured_strategy_without_a_symbol_override() -> None:
    request = routes.ShadowRequest(strategy_id="shadow_clock_reversal_v1")

    assert request.strategy_id == "shadow_clock_reversal_v1"
    assert request.symbol is None


@pytest.mark.parametrize(
    "call",
    [
        lambda: routes.session("unknown", None),
        lambda: routes.events("unknown", None),
        lambda: routes.artifacts("unknown", None),
        lambda: routes.stream("unknown", None, None),
    ],
)
def test_remote_read_routes_require_operator_auth(
    call: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AFTERIMAGE_REQUIRE_OPERATOR_AUTH", "true")
    monkeypatch.setenv("AFTERIMAGE_OPERATOR_TOKEN", "operator-secret")

    with pytest.raises(HTTPException) as failure:
        call()  # type: ignore[operator]

    assert failure.value.status_code == 403
