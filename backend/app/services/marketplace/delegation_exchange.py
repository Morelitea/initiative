"""Re-issuing a delegate's token for the app it is addressed to.

An app knows a guild and a member by the references minted for **its own**
install. A delegate holds its own, and the two are unrelated values — that is
what a sector is for. So a delegate cannot name anybody to another app, and no
amount of care on either side fixes that: only this deployment holds both
mappings.

This is the exchange that closes it, and it is the standard shape rather than a
local invention: RFC 8693, where the party holding the mappings re-mints a
token for a named audience. The delegate presents what it holds, and what comes
back names the same guild and the same member in the target's terms, with the
delegate recorded in ``act``.

Signed with the app-platform key, so an app verifies it against the one key set
it already fetches for context tokens (``/app-platform/jwks.json``) rather than
discovering a key set per delegate.

See ``history/opaque-identity-design.md`` §12.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import DelegationExchangeMessages
from app.core.security import (
    app_platform_audience,
    resolve_app_platform_signing_material,
)
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace import registration_lookup
from app.services.marketplace.app_refs import ensure_app_guild_ref, ensure_app_ref

__all__ = [
    "DELEGATION_EXCHANGE_LIFETIME",
    "DelegationExchangeError",
    "exchange_for_app",
]

#: Short, like the context token: an exchanged token is minted for the call in
#: front of it and is not a standing credential.
DELEGATION_EXCHANGE_LIFETIME = timedelta(minutes=5)


class DelegationExchangeError(Exception):
    """The exchange cannot be performed. Carries the code to answer with."""

    def __init__(self, code: str, status_code: int = 404) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


async def _target_install(
    session: AsyncSession, *, guild_id: int, listing_uid: str
) -> Optional[GuildApp]:
    """The target's install in this guild, or None.

    Read on a session the caller has already routed into the guild.
    """
    return (
        await session.exec(select(GuildApp).where(GuildApp.listing_uid == listing_uid))
    ).first()


async def exchange_for_app(
    session: AsyncSession,
    *,
    target_public_id: str,
    delegate_public_id: str,
    guild_id: int,
    user_id: int,
) -> tuple[str, int]:
    """A token naming this member and guild the way ``target_public_id`` does.

    The caller has already been authenticated as the member through the
    delegate's own token, which is what establishes that the delegate may carry
    their name at all. What is decided here is narrower: that the target is an
    app this deployment runs, that the guild has it installed and switched on,
    and what that install calls the two.

    ``session`` must already be routed into ``guild_id`` — the install lives in
    that guild's schema.
    """
    # By registration rather than by grant: the target is being *called*, not
    # doing the delegating, so it needs no power of its own — only to be an app
    # this deployment runs and has switched on.
    registrations = await registration_lookup.load_registrations()
    target = registrations.get(target_public_id)
    if target is None or not target.enabled or not target.listing_uid:
        raise DelegationExchangeError(DelegationExchangeMessages.UNKNOWN_AUDIENCE)

    install = await _target_install(
        session, guild_id=guild_id, listing_uid=target.listing_uid
    )
    if install is None:
        raise DelegationExchangeError(DelegationExchangeMessages.NOT_INSTALLED)
    if not install.enabled:
        raise DelegationExchangeError(
            DelegationExchangeMessages.INSTALL_DISABLED, status_code=409
        )

    # The whole point of the exchange: both names are minted at the target's
    # sector, so nothing the delegate holds travels on.
    subject = await ensure_app_ref(
        guild_id=guild_id, app_install_id=install.id, user_id=user_id
    )
    guild_ref = await ensure_app_guild_ref(guild_id=guild_id, app_install_id=install.id)

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "jti": str(uuid.uuid4()),
        "iss": settings.APP_PLATFORM_ISSUER,
        "aud": app_platform_audience(target_public_id),
        "iat": int(now.timestamp()),
        "exp": int((now + DELEGATION_EXCHANGE_LIFETIME).timestamp()),
        "sub": subject,
        "guild_ref": guild_ref,
        # The target's own install, the same claim a context token carries, so
        # an app reads a delegated call and a platform call the same way.
        "app_install_id": install.id,
        # Who is acting, as RFC 8693 records it. The target decides what it
        # offers this delegate; this says only who asked.
        "act": {"public_id": delegate_public_id},
    }

    key, algorithm, kid = resolve_app_platform_signing_material()
    headers: dict[str, Any] | None = {"kid": kid} if kid else None
    token = jwt.encode(payload, key, algorithm=algorithm, headers=headers)
    return token, int(DELEGATION_EXCHANGE_LIFETIME.total_seconds())
