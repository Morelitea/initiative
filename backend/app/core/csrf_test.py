"""The second layer under SameSite=Lax, for cookie-authenticated writes.

Each case is a shape a browser can actually produce. The one that matters is
the cross-site multipart form: it is a simple request, so CORS never sees a
preflight, and before this existed the only thing between it and a write was
one cookie attribute.
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
    # The exposure, in the shape it actually takes: a form on another origin,
    # multipart so no preflight is triggered, with the browser attaching the
    # session cookie because it is a top-level POST.
    _cookie(client)

    response = client.post(
        "/write",
        files={"file": ("x.png", b"data", "image/png")},
        headers={"origin": "https://attacker.test", "sec-fetch-site": "cross-site"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == CSRF_ERROR_CODE


def test_a_cross_site_post_with_no_origin_at_all_is_refused(client):
    # Every browser sends Origin on an unsafe method. Something presenting a
    # session cookie without one is not a browser doing what browsers do, and
    # absence must not read as permission.
    _cookie(client)

    response = client.post("/write", json={})

    assert response.status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_is_covered(client, method):
    # A control with a gap in it is not a control, and the gap would be in
    # whichever method nobody thought of.
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
    # Same-site includes sibling subdomains. Trusting it would reintroduce the
    # failure this threat was described by: one carelessly added subdomain.
    _cookie(client)

    response = client.post(
        "/write",
        json={},
        headers={"origin": "https://other.example.test", "sec-fetch-site": "same-site"},
    )

    assert response.status_code == 403


def test_a_header_authenticated_client_is_not_asked_for_anything(client):
    # Bearer tokens, API keys and device tokens were never exposed: a browser
    # does not attach an Authorization header cross-site. Asking them for an
    # Origin would break every API script and mobile shell for no gain.
    _cookie(client)

    response = client.post(
        "/write", json={}, headers={"authorization": "Bearer a-token"}
    )

    assert response.status_code == 200


def test_an_anonymous_request_is_not_refused_here(client):
    # No session cookie, so there is no credential to ride along. Whether it is
    # allowed is the authentication layer's decision, not this one's -- and a
    # 403 from here would hide a 401 that says something more useful.
    response = client.post(
        "/write", json={}, headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 200


def test_a_read_is_untouched(client):
    _cookie(client)

    response = client.get("/read", headers={"origin": "https://attacker.test"})

    assert response.status_code == 200


def test_a_cookie_whose_name_merely_ends_in_the_session_name_is_not_a_session(client):
    # Substring matching on the Cookie header would treat `x_session_token` as
    # a session and refuse a request that carries no session at all.
    client.cookies.set(f"x_{SESSION_COOKIE_NAME}", "not-a-session")

    response = client.post(
        "/write", json={}, headers={"origin": "https://attacker.test"}
    )

    assert response.status_code == 200
