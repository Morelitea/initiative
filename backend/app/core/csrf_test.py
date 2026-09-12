"""Origin checking for cookie-authenticated writes.

Each case is a request shape a browser can actually produce, including a
multipart form post from another origin -- which is a simple request, so no
preflight is involved and CORS is not what decides it.
"""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.csrf import CSRF_ERROR_CODE, CsrfOriginMiddleware
from app.core.security import SESSION_COOKIE_NAME

SERVED = "https://app.example.test"


async def _write(request):  # noqa: ANN001 - Starlette endpoint
    return JSONResponse({"wrote": True})


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(
        type(settings), "cors_origins", property(lambda _self: [SERVED])
    )
    app = Starlette(
        routes=[
            Route("/write", _write, methods=["POST", "PUT", "PATCH", "DELETE"]),
            Route("/read", _write, methods=["GET"]),
        ]
    )
    app.add_middleware(CsrfOriginMiddleware)
    return TestClient(app)


def _cookie(client: TestClient) -> None:
    client.cookies.set(SESSION_COOKIE_NAME, "a-session")


def test_a_cross_site_form_post_is_refused(client):
    # A form on another origin, multipart so no preflight is involved, with the
    # session cookie attached as a browser would attach it.
    _cookie(client)

    response = client.post(
        "/write",
        files={"file": ("x.png", b"data", "image/png")},
        headers={"origin": "https://attacker.test", "sec-fetch-site": "cross-site"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == CSRF_ERROR_CODE


def test_a_cross_site_post_with_no_origin_at_all_is_refused(client):
    # Browsers send Origin on an unsafe method as a matter of course, so its
    # absence is not an answer of yes.
    _cookie(client)

    response = client.post("/write", json={})

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_is_covered(client, method):
    # All four, so the rule does not depend on which verb a route happens to
    # use.
    _cookie(client)

    response = client.request(
        method, "/write", headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 403


def test_a_same_origin_write_succeeds(client):
    _cookie(client)

    response = client.post(
        "/write", json={}, headers={"origin": SERVED, "sec-fetch-site": "same-origin"}
    )

    assert response.status_code == 200


def test_a_split_origin_deployment_still_writes(client):
    # The SPA hosted somewhere other than the API. Sec-Fetch-Site says
    # cross-site and it is legitimate; the allowlist is what distinguishes it,
    # and it is the same list CORS already credentials.
    _cookie(client)

    response = client.post(
        "/write", json={}, headers={"origin": SERVED, "sec-fetch-site": "cross-site"}
    )

    assert response.status_code == 200


def test_same_site_is_not_taken_as_proof(client):
    # Same-site includes sibling subdomains, which is wider than the allowlist
    # this is meant to match.
    _cookie(client)

    response = client.post(
        "/write",
        json={},
        headers={"origin": "https://other.example.test", "sec-fetch-site": "same-site"},
    )

    assert response.status_code == 403


def test_a_header_authenticated_client_is_not_asked_for_anything(client):
    # Bearer tokens, API keys and device tokens are out of scope here; asking
    # them for an Origin would break API scripts and mobile shells for nothing.
    _cookie(client)

    response = client.post(
        "/write", json={}, headers={"authorization": "Bearer a-token"}
    )

    assert response.status_code == 200


def test_an_anonymous_request_is_not_refused_here(client):
    # No session cookie, so this has nothing to say about it. Whether the
    # request is allowed is the authentication layer's decision, and a 403 from
    # here would hide the 401 that explains it.
    response = client.post(
        "/write", json={}, headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 200


def test_a_read_is_untouched(client):
    _cookie(client)

    response = client.get("/read", headers={"origin": "https://attacker.test"})

    assert response.status_code == 200


def test_a_cookie_whose_name_merely_ends_in_the_session_name_is_not_a_session(client):
    # Whole-name comparison: `x_session_token` contains the session cookie's
    # name without being it.
    client.cookies.set(f"x_{SESSION_COOKIE_NAME}", "not-a-session")

    response = client.post(
        "/write", json={}, headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 200
