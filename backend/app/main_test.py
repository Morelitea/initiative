"""Tests for app-level exception handlers in app.main."""

from __future__ import annotations

import json

import pytest
from fastapi.exceptions import RequestValidationError
from httpx import AsyncClient

from app.main import validation_exception_handler


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
