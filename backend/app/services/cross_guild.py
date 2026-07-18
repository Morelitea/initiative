"""Helpers for endpoints that aggregate guild-scoped data across guilds.

Under schema-per-guild a routed session only sees one guild's schema, so a
"global" list (the user's items across every guild they belong to) has to visit
each guild's schema in turn and merge the results. Per-schema ids collide across
guilds, so callers must keep each item's ``guild_id`` and the identity map is
cleared between guilds.
"""

from typing import Awaitable, Callable, Optional, Sequence, TypeVar

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.role_context import (
    set_active_role,
    set_content_read_only_guild,
    set_override_sharing_initiatives,
)
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildMembership, GuildStatus

T = TypeVar("T")


async def member_guild_ids(
    session: AsyncSession,
    user_id: int,
    *,
    restrict_to: Optional[Sequence[int]] = None,
) -> list[int]:
    """Guild ids the user belongs to, sorted (optionally intersected with
    ``restrict_to``). Routes to the user-only context so the user's own rows in
    the shared ``guild_memberships`` table are visible.

    Suspended guilds are excluded for every membership role: content access is
    cut for members AND guild admins alike (admins keep only the settings
    surface), so no cross-guild aggregate may surface a suspended guild's
    content — the ``/g/{guild_id}`` choke point (``_load_guild_context``)
    refuses those guilds and this is its aggregate-path twin."""
    await set_rls_context(session, user_id=user_id)
    rows = await session.exec(
        select(GuildMembership.guild_id)
        .join(Guild, Guild.id == GuildMembership.guild_id)
        .where(
            GuildMembership.user_id == user_id,
            Guild.status != GuildStatus.suspended.value,
        )
    )
    ids = sorted(rows)
    if restrict_to is not None:
        allowed = set(restrict_to)
        ids = [gid for gid in ids if gid in allowed]
    return ids


async def gather_across_guilds(
    session: AsyncSession,
    user_id: int,
    guild_ids: Sequence[int],
    fetch: Callable[[AsyncSession, int], Awaitable[list[T]]],
    satisfied_providers: Sequence[int] | str | None = None,
) -> list[T]:
    """Route into each guild's schema, call ``fetch(session, guild_id)``, and
    concatenate the results. The identity map is expunged between guilds because
    ids are unique only within a schema, not across them.

    Each guild is routed with the user's actual membership ROLE, so a guild admin
    clears ``initiative_access``'s admin leg and gets default access to ALL of
    that guild's content — exactly like a ``/g/{guild_id}`` request. Without the
    role the admin leg never fires and these cross-guild views would hide content
    in initiatives the user isn't a *member* of (e.g. a task assigned to an admin
    who was never added to its initiative)."""
    if not guild_ids:
        return []
    # One shared-table read for every guild's role (own rows) AND lifecycle
    # status, under the user-only context, before we start routing into schemas.
    await set_rls_context(session, user_id=user_id)
    role_rows = await session.exec(
        select(GuildMembership.guild_id, GuildMembership.role, Guild.status)
        .join(Guild, Guild.id == GuildMembership.guild_id)
        .where(
            GuildMembership.user_id == user_id,
            GuildMembership.guild_id.in_(tuple(guild_ids)),
        )
    )
    roles: dict[int, tuple] = {gid: (role, status) for gid, role, status in role_rows}

    results: list[T] = []
    try:
        for guild_id in guild_ids:
            # Expunge BEFORE each guild: a cached object with this schema's id (from
            # a prior guild, or anything already on the session) would otherwise be
            # returned by the identity map instead of this guild's row.
            session.expunge_all()
            role, guild_status = roles.get(guild_id, (None, None))
            # Defense in depth for callers that assemble their own guild list
            # (member_guild_ids already filters): membership grants NO content
            # access to a suspended guild, admins included.
            if guild_status == GuildStatus.suspended.value:
                continue
            role_value = role.value if role is not None else None
            content_read_only = guild_status == GuildStatus.read_only.value
            await set_rls_context(
                session,
                user_id=user_id,
                guild_id=guild_id,
                guild_role=role_value,
                # Mirror the request path: a read_only guild is visited through
                # the SELECT-only guild_<id>_ro role, so an aggregate loop can
                # never write into a frozen guild.
                read_only=content_read_only,
                # Feeds guild_auth_satisfied(): a request caller passes its
                # session's sat, a membership-based job the system sentinel.
                # Unset means a policy-gated guild contributes nothing here.
                satisfied_providers=satisfied_providers,
            )
            # ... and the app-layer DAC engine agrees: my_permission_level and
            # write filters serialized from this guild's fetch report read.
            set_content_read_only_guild(guild_id if content_read_only else None)
            # Mirror the guild dependency: the DB GUC drives RLS (initiative_access
            # admin leg), and the request role_context drives the *app-layer*
            # guild-admin short-circuit in permissions.py (so my_permission_level /
            # require_*_access see the admin as owner when fetch() serializes here).
            set_active_role(guild_id, role_value)
            # And the per-initiative "Full access" override for this guild, so a
            # full-access PM's restricted content surfaces in cross-guild views too.
            from app.services import rls as rls_service

            override_ids = await rls_service.override_sharing_initiative_ids(
                session, user_id=user_id
            )
            set_override_sharing_initiatives(frozenset(override_ids))
            results.extend(await fetch(session, guild_id))
    finally:
        # Don't let the last guild's role/override/read-only set linger in the
        # request contextvars.
        set_active_role(None, None)
        set_override_sharing_initiatives(None)
        set_content_read_only_guild(None)
    return results
