import ipaddress
import os
import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .routes import router


def _loopback_name(value: str | None) -> bool:
    if value in {"localhost", "testclient", "testserver"}:
        return True
    try:
        return bool(value and ipaddress.ip_address(value).is_loopback)
    except ValueError:
        return False


def remote_request_allowed(client_host: str | None, request_host: str | None) -> bool:
    if os.getenv("AFTERIMAGE_REQUIRE_OPERATOR_AUTH", "false").lower() == "true":
        return True
    return _loopback_name(client_host) and _loopback_name(request_host)


def operator_auth_failure(provided: str | None) -> tuple[int, str] | None:
    if os.getenv("AFTERIMAGE_REQUIRE_OPERATOR_AUTH", "false").lower() != "true":
        return None
    expected = os.getenv("AFTERIMAGE_OPERATOR_TOKEN", "")
    if not expected:
        return 503, "operator API is not armed"
    if provided is None or not secrets.compare_digest(provided, expected):
        return 403, "operator authorization failed"
    return None


app = FastAPI(
    title="AFTERIMAGE",
    version="0.1.0",
    description="Evidence-gated autonomous Alpaca options agent",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost):\d+$",
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=[
        "Content-Type",
        "Last-Event-ID",
        "X-AFTERIMAGE-EXECUTION-TOKEN",
        "X-AFTERIMAGE-OPERATOR-TOKEN",
    ],
)


@app.middleware("http")
async def enforce_remote_boundary(request: Request, call_next: object) -> object:
    if request.url.path == "/health":
        return await call_next(request)  # type: ignore[operator]
    client_host = request.client.host if request.client else None
    request_host = request.url.hostname
    if not remote_request_allowed(client_host, request_host):
        return JSONResponse(
            status_code=403,
            content={"detail": "REMOTE_API_REQUIRES_OPERATOR_AUTH"},
        )
    failure = operator_auth_failure(request.headers.get("X-AFTERIMAGE-OPERATOR-TOKEN"))
    if failure is not None:
        status_code, detail = failure
        return JSONResponse(status_code=status_code, content={"detail": detail})
    return await call_next(request)  # type: ignore[operator]


app.include_router(router)
