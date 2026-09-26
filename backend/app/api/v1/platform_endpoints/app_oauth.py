"""Where an app service asks for an access token, and learns its installs.

``POST /app-platform/oauth/token`` is an OAuth 2.0 token endpoint (RFC 6749):
form-encoded in, JSON out, and its errors are the protocol's own
``{"error", "error_description"}`` bodies rather than this API's ``detail``
codes, because the reader is an OAuth client. The app authenticates with a JWT
it signs (RFC 7523 §2.2), or, for a member token, presents one as the grant
itself (RFC 7523 §2.1); see :mod:`app.services.marketplace.app_oauth`.

``GET /app-platform/installations`` takes an **app token** and lists the app's
installs, a page at a time, each named by the reference the app asks for an
installation token with.

Both run on the system engine: the caller is an app rather than a person, and
what they read is registrations, spent assertions and, for the listing, the
install index (``app_installs``).
"""

from typing import Any, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import SystemSessionDep
from app.core.app_access_token import (
    AccessTokenError,
    AppAccessToken,
    is_access_token,
    unseal_access_token,
)
from app.core.messages import AuthMessages
from app.schemas.platform.app_oauth import (
    AppAccessTokenResponse,
    AppInstallationRead,
    AppOAuthErrorResponse,
)
from app.services.marketplace import app_installs, app_oauth, registration_lookup


router = APIRouter()

#: RFC 6749 §5.1: a token response is never cached.
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}

_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

#: The parameters this endpoint reads. Each may appear once.
_PARAMETERS = (
    "grant_type",
    "client_assertion_type",
    "client_assertion",
    "client_id",
    "installation",
    "scope",
    "resource",
    "assertion",
)

_TOKEN_REQUEST_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            _FORM_CONTENT_TYPE: {
                "schema": {
                    "type": "object",
                    "required": ["grant_type"],
                    "properties": {
                        "grant_type": {
                            "type": "string",
                            "enum": [
                                app_oauth.GRANT_CLIENT_CREDENTIALS,
                                app_oauth.GRANT_JWT_BEARER,
                            ],
                        },
                        "client_assertion_type": {
                            "type": "string",
                            "enum": [app_oauth.ASSERTION_TYPE],
                        },
                        "client_assertion": {"type": "string"},
                        "client_id": {"type": "string"},
                        "installation": {"type": "string"},
                        "scope": {"type": "string"},
                        "resource": {"type": "string"},
                        "assertion": {"type": "string"},
                    },
                }
            }
        },
    }
}


def _oauth_error(exc: app_oauth.OAuthError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.description},
        headers=_NO_STORE,
    )


async def _read_form(request: Request) -> dict[str, str | None]:
    """The token request's parameters, each read once.

    Refuses anything but a form-encoded body, and a parameter sent twice
    (RFC 6749 §3.2). ``resource`` may be repeated under RFC 8707; this endpoint
    narrows to one initiative, so a second one is the target it cannot serve.
    """
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", 1)[0].strip().lower() != _FORM_CONTENT_TYPE:
        raise app_oauth.OAuthError(
            "invalid_request", f"the body must be {_FORM_CONTENT_TYPE}"
        )
    try:
        form = await request.form()
    except Exception as exc:
        raise app_oauth.OAuthError(
            "invalid_request", "the body could not be read"
        ) from exc
    values: dict[str, str | None] = {}
    for name in _PARAMETERS:
        entries = form.getlist(name)
        if len(entries) > 1:
            if name == "resource":
                raise app_oauth.OAuthError(
                    "invalid_target", "name at most one resource"
                )
            raise app_oauth.OAuthError("invalid_request", f"{name} is repeated")
        if not entries:
            values[name] = None
            continue
        value = entries[0]
        if not isinstance(value, str):
            raise app_oauth.OAuthError("invalid_request", f"{name} must be text")
        values[name] = value
    return values


@router.post(
    "/oauth/token",
    response_model=AppAccessTokenResponse,
    responses={
        400: {"model": AppOAuthErrorResponse},
        401: {"model": AppOAuthErrorResponse},
    },
    openapi_extra=_TOKEN_REQUEST_BODY,
)
async def issue_app_access_token(
    request: Request, session: SystemSessionDep
) -> JSONResponse:
    """Issue an app token, an installation token for one of the app's
    installs, or a member token for a member who consented. See the module
    docstring for the parameters."""
    try:
        params = await _read_form(request)
        issued = await app_oauth.issue_token(
            session,
            grant_type=params["grant_type"],
            client_assertion_type=params["client_assertion_type"],
            client_assertion=params["client_assertion"],
            client_id=params["client_id"],
            installation=params["installation"],
            scope=params["scope"],
            resource=params["resource"],
            assertion=params["assertion"],
        )
    except app_oauth.OAuthError as exc:
        return _oauth_error(exc)
    body = AppAccessTokenResponse(
        access_token=issued.access_token,
        token_type="Bearer",
        expires_in=issued.expires_in,
        scope=issued.scope,
    )
    return JSONResponse(content=body.model_dump(), headers=_NO_STORE)


def _refuse() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _app_token(request: Request) -> AppAccessToken:
    """The app token this request carries, or 401. Reads nothing from the
    database."""
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    token = value.strip()
    if scheme.lower() != "bearer" or not is_access_token(token):
        raise _refuse()
    try:
        unsealed = unseal_access_token(token)
    except AccessTokenError as exc:
        raise _refuse() from exc
    if not isinstance(unsealed, AppAccessToken):
        raise _refuse()
    return unsealed


@router.get("/installations", response_model=List[AppInstallationRead])
async def list_app_installations(
    request: Request,
    response: Response,
    limit: int = Query(
        default=app_installs.PAGE_LIMIT, ge=1, le=app_installs.PAGE_LIMIT
    ),
    cursor: Optional[str] = Query(default=None, max_length=512),
) -> List[AppInstallationRead]:
    """The calling app's installs, a page at a time. Takes an app token.

    The next page, when there is one, is named in a ``Link`` header
    (RFC 8288, ``rel="next"``) carrying the ``cursor`` to ask with.
    """
    token = _app_token(request)
    client = (await registration_lookup.load_registrations()).get(token.client_id)
    if client is None or not client.live:
        raise _refuse()
    listings, next_cursor = await app_oauth.list_installations(
        client, cursor=cursor, limit=limit
    )
    if next_cursor is not None:
        query = urlencode({"cursor": next_cursor, "limit": limit})
        response.headers["Link"] = f'<?{query}>; rel="next"'
    return [
        AppInstallationRead(installation=listing.installation, active=listing.active)
        for listing in listings
    ]
