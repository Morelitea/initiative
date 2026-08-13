"""Minting an app's embed handoff.

An embed is a cross-origin iframe, so the token that bootstraps it crosses a
trust boundary: the app verifies it against the published public half of the
app platform's own keypair. That is why it is RS256 with a dedicated key, why
the audience names one registration, and why the lifetime is a minute.

**Authorization is settled here, before a token exists.** The member's real
session decides whether the surface may be opened at all — the install must be
enabled, its app service must be registered and live, the manifest must declare
that surface, and the surface's own ``visibility`` must admit the caller. An app
never has to make that decision, and never sees a request from somebody who
failed it.

**The token carries the minimum.** Guild, install, surface, and who is opening
it — nothing about their role, their name, or their address. What an app may do
with a person is a function of what the manifest declared and the guild
accepted, not of anything it can read out of a claim set.

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

from app.core.config import settings
from app.core.messages import AppServiceMessages, GuildAppMessages
from app.core.security import (
    AppPlatformSigningNotConfiguredError,
    app_platform_audience,
    resolve_app_platform_signing_material,
)
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import registration_lookup
from app.services.marketplace.service_apps import clears_visibility

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
    #: Where the iframe points: the registration's base URL joined to the path
    #: the manifest declared for this surface.
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
    if not isinstance(definition, dict):
        return None
    embeds = definition.get("embeds")
    if not isinstance(embeds, list):
        return None
    for embed in embeds:
        if not isinstance(embed, dict) or embed.get("id") != surface_id:
            continue
        scopes = embed.get("scopes")
        renders = scope in scopes if isinstance(scopes, list) else scope == "guild"
        return embed if renders else None
    return None


def _require_visibility(
    embed: dict[str, Any],
    *,
    is_guild_admin: bool,
    is_initiative_manager: bool = False,
) -> None:
    """A surface is opened by the audience the app declared for it.

    ``member`` is the default the manifest validator applies, so an embed that
    says nothing is open to every member of the installing guild. The ordering
    lives with the vocabulary that defines it, so this cannot drift from what a
    manifest is allowed to say.
    """
    if not clears_visibility(
        embed.get("visibility"),
        is_guild_admin=is_guild_admin,
        is_initiative_manager=is_initiative_manager,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=GuildAppMessages.SURFACE_ADMIN_ONLY,
        )


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
    app: GuildApp,
    *,
    surface_id: str,
    scope: str,
    user_id: int,
    is_guild_admin: bool,
) -> EmbedHandoff:
    """Authorize the caller for one surface, then mint its handoff.

    Resolving the surface is scoped to the route it was asked for, so the
    visibility rung — which is read against where a surface was opened — is only
    ever measured somewhere the surface agreed to appear.
    """
    if not app.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=GuildAppMessages.DISABLED
        )

    embed = embed_by_id(app.definition, surface_id, scope=scope)
    if embed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildAppMessages.SURFACE_NOT_FOUND,
        )
    _require_visibility(embed, is_guild_admin=is_guild_admin)

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

    now = datetime.now(timezone.utc)
    audience = app_platform_audience(registration.public_id)
    payload: dict[str, Any] = {
        # One-shot marker: the app blocklists a handoff once it has exchanged
        # it, so a captured token is not replayable inside its short window.
        "jti": str(uuid.uuid4()),
        "sub": str(user_id),
        "aud": audience,
        "iss": settings.APP_PLATFORM_ISSUER,
        "iat": int(now.timestamp()),
        "exp": now + APP_EMBED_HANDOFF_LIFETIME,
        "guild_id": app.guild_id,
        "app_install_id": app.id,
        "surface_id": surface_id,
    }
    headers: dict[str, Any] | None = {"kid": kid} if kid else None
    token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)

    return EmbedHandoff(
        token=token,
        expires_in_seconds=int(APP_EMBED_HANDOFF_LIFETIME.total_seconds()),
        embed_url=f"{registration.base_url}{embed.get('path') or ''}",
        allowed_origins=registration.allowed_origins,
        audience=audience,
        surface_id=surface_id,
    )
