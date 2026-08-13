"""Resolving the calling app, and turning a service refusal into an answer.

Every route on this surface starts the same way: read the raw body, establish
which registration signed it, and only then look at what the request asked for.
The body is read before it is parsed because the signature covers the exact
bytes that arrived — verifying a re-serialized copy would be verifying something
the caller never sent.

The session is the system engine throughout. Registrations and the replay guard
carry no request-path grant, and no guild is known until the route says which
one; guild content is then reached by routing that same session into one guild
at a time (see :mod:`app.services.tenant.app_channels`).
"""

from __future__ import annotations

from typing import Annotated, Type, TypeVar

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, ValidationError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import AppChannelMessages
from app.db.session import get_admin_session
from app.services.marketplace.app_channel_auth import (
    AppChannelAuthError,
    CallingApp,
    authenticate_caller,
)
from app.services.tenant.app_channels import AppChannelError

__all__ = [
    "AdminSessionDep",
    "CallerDep",
    "parse_body",
    "raw_body",
    "signed_caller",
    "to_http",
]

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]

#: The raw request body, stashed on the request state by :func:`signed_caller`
#: so a route can parse the same bytes the signature was checked over.
_BODY_STATE_KEY = "app_channel_body"

ModelT = TypeVar("ModelT", bound=BaseModel)


def to_http(exc: AppChannelAuthError | AppChannelError) -> HTTPException:
    """One mapping for both service-layer refusals: each carries the message
    code to surface and the status it belongs to."""
    return HTTPException(status_code=exc.status_code, detail=exc.code)


async def signed_caller(request: Request, session: AdminSessionDep) -> CallingApp:
    """The registration whose secret signed this request.

    Raises before any route body runs, so an unauthenticated call never reaches
    a guild lookup. The verified caller is the *only* statement of who is
    calling — no route reads an app identity out of a payload.
    """
    body = await request.body()
    setattr(request.state, _BODY_STATE_KEY, body)
    try:
        return await authenticate_caller(
            session,
            method=request.method,
            path=request.url.path,
            headers=request.headers,
            body=body,
        )
    except AppChannelAuthError as exc:
        raise to_http(exc) from exc


CallerDep = Annotated[CallingApp, Depends(signed_caller)]


def raw_body(request: Request) -> bytes:
    """The exact bytes the signature was verified over."""
    return getattr(request.state, _BODY_STATE_KEY, b"") or b""


def parse_body(request: Request, model: Type[ModelT]) -> ModelT:
    """Parse the bytes the signature covered into a request model.

    Routes take no declared body parameter — FastAPI would parse one before the
    dependency above ever sees the request — so parsing happens here, after the
    caller is established, against the bytes already read.
    """
    try:
        return model.model_validate_json(raw_body(request) or b"{}")
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=AppChannelMessages.INVALID_PAYLOAD,
        ) from exc
