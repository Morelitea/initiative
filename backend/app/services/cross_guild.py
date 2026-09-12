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

from app.core import auth_context
from app.core.role_context import (
    set_active_role,
    set_content_read_only_guild,
    set_guild_shows_member_names,
    set_override_sharing_initiatives,
)
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildMembership, GuildStatus
from app.models.platform.user import User, UserStatus

T = TypeVar("T")

#: Where this session remembers each (user, guild)'s "Full access" initiative
#: ids. On ``session.info``, so its lifetime is the session's — i.e. the
#: request's. Keyed by user as well as guild because this function takes the
#: user as an argument: one session may legitimately gather for more than one
#: of them, and a guild-only key would hand the second the first's overrides.
_OVERRIDES_CACHE_KEY = "cross_guild_sharing_overrides"


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
    refuses those guilds and this is its aggregate-path twin.

    A suspended *user* is excluded the same way, and for the same reason. They
    keep every membership, so the join below would otherwise walk all of them:
    the guild path answers such a caller with nothing, and being the twin of
    that path means answering the same."""
    await set_rls_context(session, user_id=user_id)
    rows = await session.exec(
        select(GuildMembership.guild_id)
        .join(Guild, Guild.id == GuildMembership.guild_id)
        .join(User, User.id == GuildMembership.user_id)
        .where(
            GuildMembership.user_id == user_id,
            Guild.status != GuildStatus.suspended.value,
            User.status != UserStatus.suspended,
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
    who was never added to its initiative).

    ``satisfied_providers`` defaults to the ambient ``auth_context`` — the
    session's ``sat`` on a request path — so a policy-gated guild contributes
    exactly when the caller's session satisfies its policy (the guild's own
    RLS enforces that via ``guild_auth_satisfied()``; unsatisfied guilds just
    yield nothing here). User-attributed system jobs pass ``SYSTEM_SATISFIED``
    explicitly."""
    if not guild_ids:
        return []
    if satisfied_providers is None:
        ambient = auth_context.satisfied_providers()
        satisfied_providers = ambient if isinstance(ambient, str) else sorted(ambient)
    # One shared-table read for every guild's role (own rows), the guild's
    # lifecycle status AND the caller's own, under the user-only context,
    # before we start routing into schemas.
    await set_rls_context(session, user_id=user_id)
    role_rows = (
        await session.exec(
            select(
                GuildMembership.guild_id,
                GuildMembership.role,
                Guild.status,
                Guild.show_member_names,
                User.status,
            )
            .join(Guild, Guild.id == GuildMembership.guild_id)
            .join(User, User.id == GuildMembership.user_id)
            .where(
                GuildMembership.user_id == user_id,
                GuildMembership.guild_id.in_(tuple(guild_ids)),
            )
        )
    ).all()

    # The caller's own state, checked here rather than only in
    # ``member_guild_ids``, because a caller may assemble its own guild list
    # and reach this directly — ``/recents`` does. A suspended account reaches
    # no guild, so there is nothing across them to gather.
    if any(caller_status == UserStatus.suspended for *_, caller_status in role_rows):
        return []

    roles: dict[int, tuple] = {
        gid: (role, status, shows_names)
        for gid, role, status, shows_names, _caller in role_rows
    }

    # Keyed by (user, guild) within this session, which is this request. A
    # second pass over the same guild reuses the answer rather than asking again.
    overrides_cache: dict[tuple[int, int], frozenset[int]] = session.info.setdefault(
        _OVERRIDES_CACHE_KEY, {}
    )

    results: list[T] = []
    try:
        for guild_id in guild_ids:
            # Expunge BEFORE each guild: a cached object with this schema's id (from
            # a prior guild, or anything already on the session) would otherwise be
            # returned by the identity map instead of this guild's row.
            session.expunge_all()
            role, guild_status, shows_names = roles.get(guild_id, (None, None, False))
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
                # Feeds guild_auth_satisfied(): the caller's session sat
                # (resolved from auth_context above when not passed) or a
                # job's system sentinel. An unsatisfied policy-gated guild
                # contributes nothing here.
                satisfied_providers=satisfied_providers,
                # What this guild calls its members. Each guild answers for its
                # own rows, so a cross-guild list names people the way each of
                # them does — the same answer as opening that guild and
                # looking. Carried with the routing so the projection this
                # guild is read through agrees with the shapes built from it.
                shows_member_names=bool(shows_names),
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
            # Remembered for the session: one request can visit the same guild
            # more than once (a list that orders across guilds and then loads
            # only the page's rows does), and the answer — this user's
            # full-access roles in this schema — cannot change in between.
            cache_key = (user_id, guild_id)
            override_ids = overrides_cache.get(cache_key)
            if override_ids is None:
                from app.services import rls as rls_service

                override_ids = frozenset(
                    await rls_service.override_sharing_initiative_ids(
                        session, user_id=user_id
                    )
                )
                overrides_cache[cache_key] = override_ids
            set_override_sharing_initiatives(override_ids)
            results.extend(await fetch(session, guild_id))
    finally:
        # Don't let the last guild's role/override/read-only set linger in the
        # request contextvars.
        set_active_role(None, None)
        set_override_sharing_initiatives(None)
        set_content_read_only_guild(None)
        set_guild_shows_member_names(False)
    return results
