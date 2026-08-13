"""The frame policy for the document that opens an app's embed.

An embedded app runs in a cross-origin iframe, which the app-wide
``Content-Security-Policy`` forbids by default. The permission is granted for
**one** document: the response that serves the embed route names that one app's
registered origins, and every other response names none.

Scoping it this way rather than listing every registered app is deliberate. A
unioned header would grow with the size of the catalog — hundreds of origins on
every response for a capability almost no page uses — and would advertise each
app's origins to pages that have nothing to do with it. Per document, it is one
or two entries whatever the deployment installed.

Who is asking matters too. The origins are resolved only for a member of the
guild in the path, so the header describes an app to the people who already see
that app in their sidebar, and to nobody else. Anything unresolvable — a
malformed path, no session, not a member, no such install, an app service this
deployment never wired up — yields the ordinary policy, which frames nothing.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Request
from sqlmodel import select

from app.core.config import settings
from app.db import session as db_session
from app.models.platform.guild import GuildMembership
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import registration_lookup

logger = logging.getLogger(__name__)

__all__ = ["embed_document_csp", "parse_embed_path", "resolve_frame_origins"]


def parse_embed_path(path: str) -> Optional[tuple[int, int]]:
    """``g/{guild_id}/apps/{app_id}`` → the two ids, or ``None``.

    Read explicitly rather than by pattern so the only thing that can come out
    of it is a pair of positive integers — the ids then address a real row or
    nothing at all.
    """
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) != 4 or parts[0] != "g" or parts[2] != "apps":
        return None
    if not parts[1].isdigit() or not parts[3].isdigit():
        return None
    guild_id, app_id = int(parts[1]), int(parts[3])
    if guild_id <= 0 or app_id <= 0:
        return None
    return guild_id, app_id


async def resolve_frame_origins(
    *, guild_id: int, app_id: int, user_id: int
) -> tuple[str, ...]:
    """The origins the named install may be framed from, for this member.

    Reads on the system engine, routed into the guild as an admin: the install
    row lives in that guild's schema, and the caller's membership has already
    been checked against the same guild. Only non-secret registration fields
    leave this function.
    """
    async with db_session.AdminSessionLocal() as session:
        membership = (
            await session.exec(
                # Composite primary key (guild_id, user_id) — there is no id
                # column to select here.
                select(GuildMembership.user_id).where(
                    GuildMembership.guild_id == guild_id,
                    GuildMembership.user_id == user_id,
                )
            )
        ).first()
        if membership is None:
            return ()

        await db_session.set_rls_context(session, guild_id=guild_id, guild_role="admin")
        app = (
            await session.exec(
                select(GuildApp).where(
                    GuildApp.id == app_id, GuildApp.guild_id == guild_id
                )
            )
        ).first()
        if app is None or not app.enabled:
            return ()
        definition = app.definition

    registration = await registration_lookup.registration_for_definition(definition)
    if registration is None or not registration.live:
        return ()
    return registration.allowed_origins


async def embed_document_csp(request: Request, path: str) -> Optional[str]:
    """The scoped policy for this document, or ``None`` for the ordinary one.

    Deliberately fail-soft: a document is served either way, and the fallback is
    the stricter policy. Nothing here is allowed to cost a page load, so an
    unexpected failure is logged and the caller carries on.
    """
    parsed = parse_embed_path(path)
    if parsed is None:
        return None
    guild_id, app_id = parsed

    try:
        user = await _current_user(request)
        if user is None:
            return None
        origins = await resolve_frame_origins(
            guild_id=guild_id, app_id=app_id, user_id=user.id
        )
    except Exception:
        logger.warning("embed CSP: could not resolve %s", path, exc_info=True)
        return None

    if not origins:
        return None
    return settings.content_security_policy_with_frames(origins)


async def _current_user(request: Request):
    """Whoever is asking, or ``None``.

    The SPA shell is served to anonymous visitors too, so this resolves a
    session when there is one and answers ``None`` otherwise. It runs only for
    the embed route — the catch-all also serves every static asset, and opening
    a database session for those would be a per-request cost for nothing.
    """
    from app.api.deps import get_current_user_optional
    from app.core.security import SESSION_COOKIE_NAME

    header = request.headers.get("Authorization", "")
    bearer = header[7:] if header[:7].lower() == "bearer " else None
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not bearer and not cookie:
        return None

    async with db_session.AsyncSessionLocal() as session:
        return await get_current_user_optional(request, session, bearer, cookie)
