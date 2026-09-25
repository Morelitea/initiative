"""Where a vendor returns a person during an app connection's flow.

Two addresses an operator registers with each vendor client, the same for
every app on this deployment:

* ``GET /app-connections/callback`` — the OAuth redirect: ``state`` and
  ``code`` (or ``error``).
* ``GET /app-connections/setup`` — an installation-style vendor's return from
  its install page: ``state``, ``installation_id`` and ``setup_action``.

Neither takes a session. What they act on is named by ``state`` alone, which
Initiative sealed when the flow started (:mod:`app.services.tenant.
connection_flow_state`), and the work runs on the system engine routed into the
community it names. Each answers with a redirect: onward to the vendor, or to
the landing page with how the flow ended.

Not part of the OpenAPI document: only a vendor sends a browser here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.rate_limit import limiter
from app.services.tenant import app_connection_flows as flows_service

router = APIRouter(include_in_schema=False)


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/setup")
@limiter.limit("30/minute")
async def connection_setup(
    request: Request,
    state: Optional[str] = Query(default=None, max_length=4096),
    installation_id: Optional[str] = Query(default=None, max_length=64),
    setup_action: Optional[str] = Query(default=None, max_length=32),
) -> RedirectResponse:
    """The vendor's install page is done: go on to authorize, or say the
    install is waiting on somebody's approval."""
    return _redirect(
        await flows_service.complete_setup(
            state_token=state,
            installation_id=installation_id,
            setup_action=setup_action,
        )
    )


@router.get("/callback")
@limiter.limit("30/minute")
async def connection_callback(
    request: Request,
    state: Optional[str] = Query(default=None, max_length=4096),
    code: Optional[str] = Query(default=None, max_length=2048),
    error: Optional[str] = Query(default=None, max_length=200),
) -> RedirectResponse:
    """The vendor's answer to the authorization request: exchange the code,
    store the connection, and land the person on how it went."""
    return _redirect(
        await flows_service.complete_callback(state_token=state, code=code, error=error)
    )
