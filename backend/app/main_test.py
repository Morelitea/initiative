"""Tests for app-level exception handlers in app.main."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.core.config import Settings
from app.main import SecurityHeadersMiddleware, validation_exception_handler


@pytest.mark.unit
async def test_validation_handler_strips_input_and_url() -> None:
    # FastAPI's default 422 echoes back `input` (and a pydantic docs `url`). On
    # a failed password/secret validation that would leak the submitted value
    # (pentest LOW-001). The handler must drop them while keeping loc/msg/type.
    exc = RequestValidationError(
        [
            {
                "type": "string_too_long",
                "loc": ("body", "password"),
                "msg": "String should have at most 128 characters",
                "input": "correct horse battery staple - do not echo",
                "url": "https://errors.pydantic.dev/2/v/string_too_long",
            }
        ]
    )

    response = await validation_exception_handler(None, exc)

    assert response.status_code == 422
    payload = json.loads(response.body)
    assert payload == {
        "detail": [
            {
                "type": "string_too_long",
                "loc": ["body", "password"],
                "msg": "String should have at most 128 characters",
            }
        ]
    }
    # The echoed secret and the pydantic docs URL must be gone entirely.
    assert "do not echo" not in response.body.decode()
    assert "errors.pydantic.dev" not in response.body.decode()


@pytest.mark.integration
async def test_responses_carry_content_security_policy(client: AsyncClient) -> None:
    # The CSP middleware must attach an enforced policy to served responses.
    resp = await client.get("/api/v1/config")
    csp = resp.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp


@pytest.mark.integration
async def test_register_validation_error_omits_input(client: AsyncClient) -> None:
    # End-to-end: a 422 from a real endpoint must not echo the submitted value.
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "supersecret-no-echo"},
    )
    assert resp.status_code == 422
    assert "supersecret-no-echo" not in resp.text
    for err in resp.json()["detail"]:
        assert "input" not in err


# --- HSTS (Strict-Transport-Security) (pentest SEC-16) ---


async def _hsts_for(app_url: str) -> str | None:
    """Run a request through SecurityHeadersMiddleware with the header value
    that ``app_url`` would produce, and return the emitted HSTS header (or None).

    The real ``_STRICT_TRANSPORT_SECURITY`` is computed once at import from the
    process Settings, so this drives the middleware with the value a fresh
    ``Settings(APP_URL=...)`` would have produced — covering both http and https.
    """
    hsts_value = (
        "max-age=63072000; includeSubDomains"
        if Settings(APP_URL=app_url).app_url_is_https
        else None
    )
    probe = FastAPI()
    probe.add_middleware(SecurityHeadersMiddleware)

    @probe.get("/ping")
    async def _ping() -> dict[str, str]:
        return {"ok": "true"}

    # Patch the module-level constant the middleware reads.
    original = main_module._STRICT_TRANSPORT_SECURITY
    main_module._STRICT_TRANSPORT_SECURITY = hsts_value
    try:
        async with AsyncClient(
            transport=ASGITransport(app=probe), base_url="http://test"
        ) as ac:
            resp = await ac.get("/ping")
    finally:
        main_module._STRICT_TRANSPORT_SECURITY = original
    return resp.headers.get("strict-transport-security")


@pytest.mark.unit
async def test_hsts_emitted_for_https_app_url() -> None:
    # An https APP_URL must yield a long-lived, subdomain-covering HSTS header.
    hsts = await _hsts_for("https://app.example.com")
    assert hsts == "max-age=63072000; includeSubDomains"


@pytest.mark.unit
async def test_hsts_absent_for_http_app_url() -> None:
    # Over plain http the header is meaningless and must be omitted.
    assert await _hsts_for("http://localhost:5173") is None


@pytest.mark.integration
async def test_no_hsts_in_test_env_http(client: AsyncClient) -> None:
    # The suite's APP_URL is http, so the live app must not emit HSTS.
    resp = await client.get("/api/v1/config")
    assert "strict-transport-security" not in resp.headers


# --- API docs gating (pentest SEC-16) ---


@pytest.mark.integration
async def test_docs_and_openapi_served_when_enabled(client: AsyncClient) -> None:
    # ENABLE_API_DOCS defaults True, so docs + schema are reachable in dev.
    docs = await client.get("/api/v1/docs")
    schema = await client.get("/api/v1/openapi.json")
    assert docs.status_code == 200
    assert schema.status_code == 200
    assert schema.json()["info"]["title"]


@pytest.mark.unit
def test_docs_routes_return_404_when_disabled() -> None:
    """HTTP-level check for the disabled path.

    ``app.main`` builds its app at import time, so the real app can't be
    reconstructed with ``ENABLE_API_DOCS=False`` inside the suite. Instead this
    constructs FastAPI with the exact wiring ``app.main`` uses and proves over
    HTTP that the docs/openapi routes don't exist (404), not merely that the
    attributes are ``None``. The enabled path is covered against the real app
    by ``test_docs_and_openapi_served_when_enabled``.
    """
    cfg = Settings(ENABLE_API_DOCS=False)
    disabled = FastAPI(
        docs_url=f"{cfg.API_V1_STR}/docs" if cfg.ENABLE_API_DOCS else None,
        openapi_url=(f"{cfg.API_V1_STR}/openapi.json" if cfg.ENABLE_API_DOCS else None),
        redoc_url=None,
    )
    http = TestClient(disabled)
    assert http.get("/api/v1/docs").status_code == 404
    assert http.get("/api/v1/openapi.json").status_code == 404


@pytest.mark.unit
def test_real_app_serves_docs_only_when_enabled() -> None:
    # The deployed app object reflects the (default-on) setting — guards
    # against the wiring in app.main drifting from ENABLE_API_DOCS.
    assert main_module.app.docs_url == "/api/v1/docs"
    assert main_module.app.openapi_url == "/api/v1/openapi.json"
