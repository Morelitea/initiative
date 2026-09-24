"""The route class for routes an installed app may call.

``ActorRoute`` serves a person exactly as ``APIRoute`` does. For an installed
app it carries the request through the three phases of
:mod:`app.core.identity_boundary`:

1. It opens the request's boundary slot before anything else runs. The route's
   scope dependency (``app.api.deps.app_scope``) fills it once the install's
   standing is in, which is before FastAPI validates the path, query and body,
   so :data:`PersonId` and :data:`GuildId` fields there read references.
2. It wraps the endpoint, so the boundary is in its handler phase while the
   route's own code runs and in its response phase once it returns, which is
   when FastAPI serializes the return value.
3. After FastAPI has rendered the response, it resolves the markers the
   serialization left: from this process's cache, and what the cache does not
   hold in one statement on the request's own session
   (``app_refs.install_refs``), which mints what the install has never been
   told. The references are written into the body in place of the markers.

A route that admits an installed app returns its payload for FastAPI to
serialize. One that hands back a JSON response of its own is refused for an
install, since the translation has already run by then.
"""

from __future__ import annotations

import functools
import inspect
import re
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi.routing import APIRoute
from starlette.requests import Request
from starlette.responses import Response

from app.core.identity_boundary import (
    BoundaryPhase,
    InstallBoundary,
    boundary_scope,
    current_install_boundary,
)
from app.models.platform.identity_ref import IdentityEntity
from app.services.marketplace import app_refs

__all__ = ["ActorRoute"]

_ENTITY_BY_CODE = {entity.code: entity for entity in IdentityEntity}


def _enter(phase: BoundaryPhase) -> InstallBoundary | None:
    boundary = current_install_boundary()
    if boundary is not None:
        boundary.phase = phase
    return boundary


def _check_returned(boundary: InstallBoundary | None, result: Any) -> Any:
    """Refuse a JSON response the endpoint built itself, for an install."""
    if (
        boundary is not None
        and isinstance(result, Response)
        and getattr(result, "body", b"")
        and "json" in (result.media_type or result.headers.get("content-type", ""))
    ):
        raise RuntimeError(
            "a route serving an installed app returns its payload for the "
            "route to serialize, not a JSON response of its own"
        )
    return result


#: Set on an endpoint :func:`_phased` has wrapped. A router included into
#: another is rebuilt route by route with the endpoint it already holds, which
#: must not be wrapped a second time.
_PHASED = "__actor_route_phased__"


def _phased(endpoint: Callable[..., Any]) -> Callable[..., Any]:
    """``endpoint``, marking the boundary's handler and response phases."""
    if getattr(endpoint, _PHASED, False):
        return endpoint
    if inspect.iscoroutinefunction(endpoint):

        @functools.wraps(endpoint)
        async def run_async(*args: Any, **kwargs: Any) -> Any:
            _enter(BoundaryPhase.handler)
            result = await endpoint(*args, **kwargs)
            return _check_returned(_enter(BoundaryPhase.response), result)

        setattr(run_async, _PHASED, True)
        return run_async

    @functools.wraps(endpoint)
    def run(*args: Any, **kwargs: Any) -> Any:
        _enter(BoundaryPhase.handler)
        result = endpoint(*args, **kwargs)
        return _check_returned(_enter(BoundaryPhase.response), result)

    setattr(run, _PHASED, True)
    return run


async def _translate(boundary: InstallBoundary, response: Response) -> Response:
    """Write the install's references into ``response`` in place of markers."""
    if not boundary.wanted:
        return response
    body = getattr(response, "body", None)
    if not isinstance(body, (bytes, bytearray)):
        raise RuntimeError("a response naming people to an install has a body")

    refs, minted = await app_refs.install_refs(
        boundary.session,
        guild_id=boundary.guild_id,
        install_id=boundary.install_id,
        wanted=boundary.wanted,
    )
    if minted:
        await boundary.session.commit()

    def substitute(match: re.Match[bytes]) -> bytes:
        entity = _ENTITY_BY_CODE[match.group(1).decode()]
        ref = refs.get((entity, int(match.group(2))))
        if ref is None:
            raise RuntimeError("a reference the response names was not resolved")
        return b'"' + ref.encode() + b'"'

    marker = re.compile(b'"' + re.escape(boundary.nonce.encode()) + rb':([a-z]):(\d+)"')
    translated = marker.sub(substitute, bytes(body))
    response.body = translated
    response.headers["content-length"] = str(len(translated))
    return response


class ActorRoute(APIRoute):
    """``APIRoute`` for the tenant routers: unchanged for a person; for an
    installed app, translates person and community ids at the boundary."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs: Any):
        super().__init__(path, _phased(endpoint), **kwargs)

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def serve(request: Request) -> Response:
            with boundary_scope() as slot:
                try:
                    response = await handler(request)
                    if slot.boundary is None:
                        return response
                    return await _translate(slot.boundary, response)
                finally:
                    # Anything the request started that runs on after it sees
                    # no boundary, so it works in row ids.
                    slot.boundary = None

        return serve
