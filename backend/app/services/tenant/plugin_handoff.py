"""Minting a plug-in's embed handoff.

An embed is a cross-origin iframe, so the token that bootstraps it crosses a
trust boundary: the plug-in verifies it against the published public half of the
plug-in platform's own keypair. That is why it is RS256 with a dedicated key, why
the audience names one registration, and why the lifetime is a minute.

**Authorization is settled here, before a token exists.** The member's real
session decides whether the surface may be opened at all — the install must be
enabled, its plug-in service must be registered and live, the manifest must declare
that surface, and the community's own choice must admit the caller: inside an
initiative, the install is placed there and the caller holds one of the roles
the placement allows; at the community level, and for a surface marked
``admin_only``, the caller is a guild admin. A guild admin opens any surface
that is there. A plug-in never has to make that decision, and never sees a request
from somebody who failed it.

**The token carries the minimum.** Guild, install, surface, who is opening it,
whether they administer the community, and — where the surface was opened
inside an initiative — which one and whether they moderate it. Nothing about
their name or their address, and no other role. What a plug-in may do with a person is a function of what the
manifest declared and the guild accepted, not of anything it can read out of a
claim set.

The claims a plug-in receives:

* ``sub`` — the member, by the reference this install knows them by;
* ``community_ref`` — the community, by the reference this install knows it by;
* ``plugin_install_id`` and ``surface_id`` — which install and which surface;
* ``community_admin`` — ``true`` when the viewer administers the community, read
  from the same standing that decided whether they may open the surface. A
  plug-in uses it to shape its own screens, such as showing community-level
  settings; it is not a grant, and every call the plug-in makes to Initiative is
  still decided by that call's own token;
* ``initiative_id`` — present only when the surface was opened inside an
  initiative;
* ``initiative_moderator`` — present with ``initiative_id``: ``true`` when the
  viewer's role there manages it with "Full access", as a moderator's does. A
  plug-in uses it the way it uses ``community_admin``, such as to let only a
  moderator set something up that acts with a moderator's standing;
* ``jti``, ``iat``, ``exp``, ``iss`` and ``aud`` — the envelope.

**Where a surface was opened is the route's to say.** A surface declares the
scopes it renders in, and the caller names none of them: the initiative in the
token is the one whose route was taken and whose gate the caller passed, never a
value they supplied.

This generalizes the advanced tool's mint: same shape, but target, origins and
audience come from the registration row rather than from deployment settings, so
every registered plug-in gets one without a settings block of its own.
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
from app.core.messages import PluginServiceMessages, GuildPluginMessages
from app.core.security import (
    PLUGIN_HANDOFF_TOKEN_TYPE,
    PLUGIN_PLATFORM_ISSUER,
    PluginPlatformSigningNotConfiguredError,
    plugin_platform_audience,
    resolve_plugin_platform_signing_material,
)
from app.models.tenant.guild_plugin import GuildPlugin
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.marketplace import plugin_refs, registration_lookup
from app.services.marketplace.service_plugins import is_admin_only
from app.services.tenant.guild_plugins import (
    SurfaceAccess,
    declared_surfaces,
    placement_role_ids,
    surface_access,
    surface_renders_in,
)

__all__ = [
    "PLUGIN_EMBED_HANDOFF_LIFETIME",
    "EmbedHandoff",
    "embed_by_id",
    "mint_embed_handoff",
    "require_live_registration",
]

#: Single source for the handoff's lifetime, so the response advertises exactly
#: what the ``exp`` claim encodes. Short by design: the handoff is spent within a
#: minute, and the long-lived session belongs to the plug-in, not to this token.
PLUGIN_EMBED_HANDOFF_LIFETIME = timedelta(seconds=60)


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
    those is community-wide.
    """
    for embed in declared_surfaces(definition):
        if embed.get("id") != surface_id:
            continue
        return embed if surface_renders_in(embed, scope) else None
    return None


def _refusal(embed: dict[str, Any], *, initiative_id: int | None) -> str:
    """The code a refused viewer is given: which audience they missed."""
    if initiative_id is None or is_admin_only(embed):
        return GuildPluginMessages.SURFACE_ADMIN_ONLY
    return GuildPluginMessages.SURFACE_ROLE_NOT_ALLOWED


async def require_live_registration(
    plugin: GuildPlugin,
) -> registration_lookup.RegistrationSnapshot:
    """The registration behind this install, or a refusal.

    Both halves of "not available" answer the same way: a plug-in service this
    deployment never wired up, and one whose registration the operator turned
    off, are equally unreachable from here.
    """
    registration = await registration_lookup.registration_for_definition(
        plugin.definition, listing_uid=plugin.listing_uid
    )
    if registration is None or not registration.live:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GuildPluginMessages.SERVICE_NOT_REGISTERED,
        )
    return registration


async def mint_embed_handoff(
    session: AsyncSession,
    plugin: GuildPlugin,
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

    Who may open it is :func:`~app.services.tenant.guild_plugins.surface_access`,
    the same decision the plug-in read reports to the client, measured on the
    viewer's standing (``context``). An initiative handoff reads the
    placement's roles in one query.
    """
    if not plugin.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=GuildPluginMessages.DISABLED
        )

    scope = "community" if initiative_id is None else "initiative"
    # Two ways there is no surface here: the plug-in never declared one for this
    # scope, or the guild placed its initiative surfaces somewhere else. Same
    # answer, because from this route both mean the same thing.
    embed = embed_by_id(plugin.definition, surface_id, scope=scope)
    if embed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildPluginMessages.SURFACE_NOT_FOUND,
        )
    access = surface_access(
        embed,
        initiative_id=initiative_id,
        placement_role_ids=(
            None
            if initiative_id is None
            else await placement_role_ids(session, plugin.id, initiative_id)
        ),
        is_guild_admin=context.is_admin,
        member_role_ids=context.member_role_ids,
    )
    if access is SurfaceAccess.not_here:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=GuildPluginMessages.SURFACE_NOT_FOUND,
        )
    if access is SurfaceAccess.refused:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_refusal(embed, initiative_id=initiative_id),
        )

    registration = await require_live_registration(plugin)

    try:
        key, algorithm, kid = resolve_plugin_platform_signing_material()
    except PluginPlatformSigningNotConfiguredError as exc:
        # The plug-in platform's keypair is required and has no fallback, so an
        # unconfigured deployment fails closed and says which setting is
        # missing rather than minting something no plug-in can verify.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=PluginServiceMessages.SIGNING_NOT_CONFIGURED,
        ) from exc

    subject = await plugin_refs.ensure_plugin_ref(
        guild_id=routed_guild_id(session),
        plugin_install_id=plugin.id,
        user_id=context.user_id,
    )
    guild_ref = await plugin_refs.ensure_plugin_guild_ref(
        guild_id=routed_guild_id(session), plugin_install_id=plugin.id
    )

    now = datetime.now(timezone.utc)
    audience = plugin_platform_audience(registration.public_id)
    payload: dict[str, Any] = {
        # One-shot marker: the plug-in blocklists a handoff once it has exchanged
        # it, so a captured token is not replayable inside its short window.
        "jti": str(uuid.uuid4()),
        # The reference this install knows the member by (OIDC Core §8.1
        # pairwise), never the row id: it is stable for this install and
        # unrelated to what any other sector holds for the same person.
        "sub": subject,
        "aud": audience,
        "iss": PLUGIN_PLATFORM_ISSUER,
        "iat": int(now.timestamp()),
        "exp": now + PLUGIN_EMBED_HANDOFF_LIFETIME,
        # The guild by reference, for the same reason as the member above: an
        # index names a row to us, not an entity to somebody else.
        "community_ref": guild_ref,
        "plugin_install_id": plugin.id,
        "surface_id": surface_id,
        # The viewer's community role, from the standing the access decision
        # above was measured on, so a plug-in need not ask for it separately.
        "community_admin": bool(context.is_admin),
    }
    # Absent guild-wide rather than null, so "which initiative is this?" has one
    # answer instead of two shapes that both mean none.
    if initiative_id is not None:
        payload["initiative_id"] = initiative_id
        payload["initiative_moderator"] = (
            initiative_id in context.manager_initiatives
            and initiative_id in context.override_initiatives
        )
    headers: dict[str, Any] = {"typ": PLUGIN_HANDOFF_TOKEN_TYPE}
    if kid:
        headers["kid"] = kid
    token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)

    return EmbedHandoff(
        token=token,
        expires_in_seconds=int(PLUGIN_EMBED_HANDOFF_LIFETIME.total_seconds()),
        embed_url=f"{registration.browser_base}{embed.get('path') or ''}",
        allowed_origins=registration.allowed_origins,
        audience=audience,
        surface_id=surface_id,
    )
