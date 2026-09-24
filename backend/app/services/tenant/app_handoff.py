"""Minting an app's embed handoff.

An embed is a cross-origin iframe, so the token that bootstraps it crosses a
trust boundary: the app verifies it against the published public half of the
app platform's own keypair. That is why it is RS256 with a dedicated key, why
the audience names one registration, and why the lifetime is a minute.

**Authorization is settled here, before a token exists.** The member's real
session decides whether the surface may be opened at all — the install must be
enabled, its app service must be registered and live, the manifest must declare
that surface, and the community's own choice must admit the caller: inside an
initiative, the install is placed there and the caller holds one of the roles
the placement allows; at the community level, and for a surface marked
``admin_only``, the caller is a guild admin. A guild admin opens any surface
that is there. An app never has to make that decision, and never sees a request
from somebody who failed it.

**The token carries the minimum.** Guild, install, surface, who is opening it,
and — where the surface was opened inside an initiative — which one. Nothing
about their role, their name, or their address. What an app may do with a person
is a function of what the manifest declared and the guild accepted, not of
anything it can read out of a claim set.

**Where a surface was opened is the route's to say.** A surface declares the
scopes it renders in, and the caller names none of them: the initiative in the
token is the one whose route was taken and whose gate the caller passed, never a
value they supplied.

This generalizes the advanced tool's mint: same shape, but target, origins and
audience come from the registration row rather than from deployment settings, so
every registered app gets one without a settings block of its own.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from fastapi import HTTPException, status

from app.db.guild_standing import GuildContext
from app.db.session import routed_guild_id
from app.core.messages import AppServiceMessages, GuildAppMessages
from app.core.security import (
    APP_PLATFORM_ISSUER,
    AppPlatformSigningNotConfiguredError,
    app_platform_audience,
    resolve_app_platform_signing_material,
)
from app.models.tenant.guild_app import GuildApp
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.marketplace import app_refs, registration_lookup
from app.services.marketplace.service_apps import is_admin_only
from app.services.tenant.guild_apps import (
    SurfaceAccess,
    declared_surfaces,
    placement_role_ids,
    surface_access,
    surface_renders_in,
)

__all__ = [
    "APP_EMBED_HANDOFF_LIFETIME",
    "EmbedHandoff",
    "embed_by_id",
    "mint_embed_handoff",
    "require_live_registration",
]

#: Single source for the handoff's lifetime, so the response advertises exactly
#: what the ``exp`` claim encodes. Short by design: a leaked handoff is worth a
#: minute, and the long-lived session belongs to the app, not to this token.
APP_EMBED_HANDOFF_LIFETIME = timedelta(seconds=60)


@dataclass(frozen=True)
class EmbedHandoff:
    """A minted handoff plus everything the browser needs to use it."""

    token: str
    expires_in_seconds: int
    #: Where the iframe points: the registration's browser base joined to the
    #: path the manifest declared for this surface.
    embed_url: str
    #: The origins the SPA accepts messages from, and posts the token to.
    allowed_origins: tuple[str, ...]
    audience: str
    surface_id: str


def embed_by_id(
    definition: dict[str, Any] | None, surface_id: str, *, scope: str
) -> Optional[dict[str, Any]]:
    """One declared embed surface from a pinned definition, if it renders here.

    ``scope`` is where the surface is being opened from — the route's to state,
    never the caller's. A surface that never asked to render there is not a
    surface of that route, so it is simply not found. Definitions pinned before
    a surface could say where it belongs carry no ``scopes``, and every one of
    those is guild-wide.
    """
    for embed in declared_surfaces(definition):
        if embed.get("id") != surface_id:
            continue
        return embed if surface_renders_in(embed, scope) else None
    return None


def _refusal(embed: dict[str, Any], *, initiative_id: int | None) -> str:
    """The code a refused viewer is given: which audience they missed."""
    if initiative_id is None or is_admin_only(embed):
        return GuildAppMessages.SURFACE_ADMIN_ONLY
    return GuildAppMessages.SURFACE_ROLE_NOT_ALLOWED


async def require_live_registration(
    app: GuildApp,
) -> registration_lookup.RegistrationSnapshot:
    """The registration behind this install, or a refusal.

    Both halves of "not available" answer the same way: an app service this
    deployment never wired up, and one whose registration the operator turned
    off, are equally unreachable from here.
    """
    registration = await registration_lookup.registration_for_definition(app.definition)
    if registration is None or not registration.live:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildAppMessages.SERVICE_NOT_REGISTERED,
        )
    return registration


async def mint_embed_handoff(
    session: AsyncSession,
    app: GuildApp,
    *,
    surface_id: str,
    context: GuildContext,
    initiative_id: int | None,
) -> EmbedHandoff:
    """Authorize the caller for one surface, then mint its handoff.

    ``initiative_id`` is where the surface was opened, and it is the only thing
    that says so — the scope is derived from it rather than passed alongside,
    because two arguments could disagree and there is nothing sensible for a
    mint to do when they do. It comes from a route whose gate the caller already
    passed, so by the time it is a claim it is a fact.

    Who may open it is :func:`~app.services.tenant.guild_apps.surface_access`,
    the same decision the app read reports to the client, measured on the
    viewer's standing (``context``). An initiative handoff reads the
    placement's roles in one query.
    """
    if not app.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=GuildAppMessages.DISABLED
        )

    scope = "guild" if initiative_id is None else "initiative"
    # Two ways there is no surface here: the app never declared one for this
    # scope, or the guild placed its initiative surfaces somewhere else. Same
    # answer, because from this route both mean the same thing.
    embed = embed_by_id(app.definition, surface_id, scope=scope)
    if embed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildAppMessages.SURFACE_NOT_FOUND,
        )
    access = surface_access(
        embed,
        initiative_id=initiative_id,
        placement_role_ids=(
            None
            if initiative_id is None
            else await placement_role_ids(session, app.id, initiative_id)
        ),
        is_guild_admin=context.is_admin,
        member_role_ids=context.member_role_ids,
    )
    if access is SurfaceAccess.not_here:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildAppMessages.SURFACE_NOT_FOUND,
        )
    if access is SurfaceAccess.refused:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_refusal(embed, initiative_id=initiative_id),
        )

    registration = await require_live_registration(app)

    try:
        key, algorithm, kid = resolve_app_platform_signing_material()
    except AppPlatformSigningNotConfiguredError as exc:
        # The app platform's keypair is required and has no fallback, so an
        # unconfigured deployment fails closed and says which setting is
        # missing rather than minting something no app can verify.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=AppServiceMessages.SIGNING_NOT_CONFIGURED,
        ) from exc

    subject = await app_refs.ensure_app_ref(
        guild_id=routed_guild_id(session),
        app_install_id=app.id,
        user_id=context.user_id,
    )
    guild_ref = await app_refs.ensure_app_guild_ref(
        guild_id=routed_guild_id(session), app_install_id=app.id
    )

    now = datetime.now(timezone.utc)
    audience = app_platform_audience(registration.public_id)
    payload: dict[str, Any] = {
        # One-shot marker: the app blocklists a handoff once it has exchanged
        # it, so a captured token is not replayable inside its short window.
        "jti": str(uuid.uuid4()),
        # The reference this install knows the member by (OIDC Core §8.1
        # pairwise), never the row id: it is stable for this install and
        # unrelated to what any other sector holds for the same person.
        "sub": subject,
        "aud": audience,
        "iss": APP_PLATFORM_ISSUER,
        "iat": int(now.timestamp()),
        "exp": now + APP_EMBED_HANDOFF_LIFETIME,
        # The guild by reference, for the same reason as the member above: an
        # index names a row to us, not an entity to somebody else.
        "guild_ref": guild_ref,
        "app_install_id": app.id,
        "surface_id": surface_id,
    }
    # Absent guild-wide rather than null, so "which initiative is this?" has one
    # answer instead of two shapes that both mean none.
    if initiative_id is not None:
        payload["initiative_id"] = initiative_id
    headers: dict[str, Any] | None = {"kid": kid} if kid else None
    token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)

    return EmbedHandoff(
        token=token,
        expires_in_seconds=int(APP_EMBED_HANDOFF_LIFETIME.total_seconds()),
        embed_url=f"{registration.browser_base}{embed.get('path') or ''}",
        allowed_origins=registration.allowed_origins,
        audience=audience,
        surface_id=surface_id,
    )
