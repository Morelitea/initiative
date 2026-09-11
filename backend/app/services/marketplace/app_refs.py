"""What one installed app calls one member.

An app needs a stable name for a member: to store their preferences, to
recognise them across two visits, and to act as them.

That name is a **pairwise pseudonymous identifier** (OpenID Connect Core §8.1):
a value stable for one *sector*, and unrelated to the value any other sector
holds for the same person. Here the sector is the **install**, matching
``connection_ref``'s precedent of being minted per (install, connection,
member) and matching the fact that apps are guild-pinned everywhere else.

That is the same thing ``services.platform.identity_refs`` provides for every
other sector, so this module is a thin scoping layer over it rather than a
second implementation — an install is ``(guild_id, app_install_id)``, because
install ids are per-guild-schema and not unique on their own. See
``history/opaque-identity-design.md`` §10.

Two things to keep in mind here.

``identity_refs`` is a platform-wide table, so the guild is a **predicate** on
every read rather than the schema the query runs in. ``resolve_app_ref``
therefore takes the guild and will not answer without it.

And it is reachable only on the system engine. Every function here that writes
therefore opens a session of its own; only ``resolve_app_ref`` takes one, because
its caller composes it with a guild-routed read in the same transaction.
"""

from __future__ import annotations

from app.db import session as db_session
from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
)
from app.services.platform import identity_refs
from sqlmodel.ext.asyncio.session import AsyncSession

__all__ = [
    "REF_MAX_LENGTH",
    "ensure_app_guild_ref",
    "resolve_app_guild_ref",
    "drop_guild_app_refs",
    "drop_install_refs",
    "ensure_app_ref",
    "reissue_app_ref",
    "reissue_install_refs",
    "resolve_app_ref",
]

_PURPOSE = IdentityPurpose.app


async def ensure_app_ref(*, guild_id: int, app_install_id: int, user_id: int) -> str:
    """This member's reference at this install, minting one on first use.

    Opens a system-engine session of its own, like
    ``identity_refs.billing_refs``: the table is reachable only there, and the
    caller is a request handler routed into a guild role.
    """
    async with db_session.AdminSessionLocal() as session:
        ref = await identity_refs.ensure_ref(
            session,
            entity_type=IdentityEntity.user,
            entity_id=user_id,
            purpose=_PURPOSE,
            sector_guild_id=guild_id,
            sector_id=app_install_id,
        )
        await session.commit()
    return ref


async def ensure_app_guild_ref(*, guild_id: int, app_install_id: int) -> str:
    """What this install calls the guild it is installed in.

    The guild's own reference at the same sector the member's uses, so an app
    installed in two guilds holds two unrelated values for them — the same
    property the member reference has, applied to the tenant.
    """
    async with db_session.AdminSessionLocal() as session:
        ref = await identity_refs.ensure_ref(
            session,
            entity_type=IdentityEntity.guild,
            entity_id=guild_id,
            purpose=_PURPOSE,
            sector_guild_id=guild_id,
            sector_id=app_install_id,
        )
        await session.commit()
    return ref


async def resolve_app_guild_ref(*, ref: str) -> int | None:
    """Which guild a guild reference names, or None.

    The inverse of ``ensure_app_guild_ref``, for a token that names its guild by
    reference. Opens its own session: the caller at this point holds none.
    """
    async with db_session.AdminSessionLocal() as session:
        row = await identity_refs.resolve_ref(session, ref=ref)
    if row is None:
        return None
    if row.purpose != _PURPOSE or row.entity_type != IdentityEntity.guild:
        return None
    return row.entity_id


async def resolve_app_ref(
    session: AsyncSession, *, ref: str, guild_id: int
) -> IdentityRef | None:
    """Which member a reference names inside this guild, or None.

    Returns the row rather than the member id so the caller can also check
    which install it was minted for: the guild narrows the value to this
    deployment's copy, and the install is the sector it actually belongs to.
    """
    row = await identity_refs.resolve_ref(session, ref=ref)
    if row is None:
        return None
    if (
        row.purpose != _PURPOSE
        or row.entity_type != IdentityEntity.user
        or row.sector_guild_id != guild_id
    ):
        return None
    return row


async def reissue_app_ref(
    session: AsyncSession, *, guild_id: int, app_install_id: int, user_id: int
) -> str:
    """Replace what one install calls one member, and return the new value.

    The old value keeps resolving for the grace window, so a call already in
    flight lands.
    """
    return await identity_refs.reissue_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user_id,
        purpose=_PURPOSE,
        sector_guild_id=guild_id,
        sector_id=app_install_id,
    )


async def reissue_install_refs(
    session: AsyncSession, *, guild_id: int, app_install_id: int
) -> int:
    """Replace what one install calls every member. Returns the count."""
    return await identity_refs.reissue_all_refs(
        session,
        entity_type=IdentityEntity.user,
        purpose=_PURPOSE,
        sector_guild_id=guild_id,
        sector_id=app_install_id,
    )


async def drop_install_refs(*, guild_id: int, app_install_id: int) -> int:
    """Remove every reference minted for one install. Returns the count.

    Called when the app is uninstalled, from a guild-routed request session —
    so this opens its own, like ``ensure_app_ref``. ``sector_id`` is not a
    foreign key (``guild_apps`` lives in a guild schema and ``identity_refs``
    does not), so this stands in for the cascade the column cannot carry.
    """
    async with db_session.AdminSessionLocal() as session:
        dropped = await identity_refs.drop_sector_refs(
            session, sector_guild_id=guild_id, sector_id=app_install_id
        )
        await session.commit()
    return dropped


async def drop_guild_app_refs(*, guild_id: int) -> int:
    """Remove every app reference minted in one guild. Returns the count.

    Called when the guild is deleted, for the same reason as
    ``drop_install_refs``, and like it opens its own session: guild deletion
    reaches this from three call sites holding three different sessions, one of
    them routed into the guild role being deleted.
    """
    async with db_session.AdminSessionLocal() as session:
        dropped = await identity_refs.drop_sector_refs(
            session, sector_guild_id=guild_id
        )
        await session.commit()
    return dropped
