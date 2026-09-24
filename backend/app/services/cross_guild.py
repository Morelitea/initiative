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
from app.db.guild_standing import GuildContext
from app.db.session import set_rls_context
from app.models.platform.guild import (
    LIVE_STATUS_VALUES,
    Guild,
    GuildMembership,
)
from app.models.platform.user import User, UserStatus

T = TypeVar("T")

#: Where this session remembers each (user, guild)'s standing. On
#: ``session.info``, so its lifetime is the session's — i.e. the request's.
#: Keyed by user as well as guild because this function takes the user as an
#: argument: one session may legitimately gather for more than one of them, and
#: a guild-only key would hand the second the first's standing. The surface
#: (content or settings) is part of the key, since each establishes its own. A cached
#: context is never written on its own — it is re-applied through the same
#: routing-and-standing pair a first visit goes through, which is what keeps
#: the session and its standing naming one community.
_CONTEXT_CACHE_KEY = "cross_guild_contexts"


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
    that path means answering the same.

    A guild that declines personal API keys is excluded when the request is
    carrying one, which is the same twinning: ``/g/{guild_id}`` refuses that
    caller, so an aggregate cannot be the way its content is read instead."""
    await set_rls_context(session, user_id=user_id)
    conditions = [
        GuildMembership.user_id == user_id,
        Guild.status.in_(LIVE_STATUS_VALUES),
        User.status != UserStatus.suspended,
    ]
    if auth_context.api_key_credential():
        conditions.append(Guild.allow_api_keys.is_(True))
    rows = await session.exec(
        select(GuildMembership.guild_id)
        .join(Guild, Guild.id == GuildMembership.guild_id)
        .join(User, User.id == GuildMembership.user_id)
        .where(*conditions)
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
    *,
    for_settings: bool = False,
) -> list[T]:
    """Route into each guild's schema, call ``fetch(session, guild_id)``, and
    concatenate the results. The identity map is expunged between guilds because
    ids are unique only within a schema, not across them.

    Each community is entered through the **same seam** a ``/g/{guild_id}``
    request goes through, so what these views show is what that request would
    show: the same lookup, the same refusals, and the same standing computed in
    the community's own schema. A community this caller cannot reach right now
    contributes nothing rather than raising.

    ``satisfied_providers`` defaults to the ambient ``auth_context`` — the
    session's ``sat`` on a request path — so a policy-gated guild contributes
    exactly when the caller's session satisfies its policy. User-attributed
    system jobs pass ``SYSTEM_SATISFIED`` explicitly.

    ``for_settings`` enters each community on its configuration surface, as
    ``/g/{guild_id}`` settings routes do (``establish_guild_access``'s
    ``for_settings``), for a read of what its administrator configures."""
    if not guild_ids:
        return []
    from app.api.deps import (
        GuildAccessError,
        apply_guild_session_context,
        establish_guild_access,
    )

    if satisfied_providers is None:
        ambient = auth_context.satisfied_providers()
        satisfied_providers = ambient if isinstance(ambient, str) else sorted(ambient)
    # One shared-table read for the caller's own account, under the user-only
    # context, before we start routing into schemas.
    await set_rls_context(session, user_id=user_id)
    user = (await session.exec(select(User).where(User.id == user_id))).one_or_none()
    # A suspended account reaches no community, so there is nothing across them
    # to gather. Checked here rather than only in ``member_guild_ids`` because a
    # caller may assemble its own guild list and reach this directly.
    if user is None or user.status == UserStatus.suspended:
        return []

    contexts: dict[tuple[int, int, bool], GuildContext] = session.info.setdefault(
        _CONTEXT_CACHE_KEY, {}
    )

    results: list[T] = []
    for guild_id in guild_ids:
        # Expunge BEFORE each guild: a cached object with this schema's id (from
        # a prior guild, or anything already on the session) would otherwise be
        # returned by the identity map instead of this guild's row.
        session.expunge_all()
        # The caller's own account is a ``public`` row and collides with
        # nothing per schema, so it goes straight back — every step below
        # reads it.
        session.add(user)
        key = (user_id, guild_id, for_settings)
        cached = contexts.get(key)
        try:
            if cached is None:
                context = await establish_guild_access(
                    session,
                    user,
                    guild_id,
                    satisfied_providers=satisfied_providers,
                    for_settings=for_settings,
                )
                contexts[key] = context
            else:
                # The lookup's answer is the same one it gave a moment ago in
                # this request; what has to happen again is the routing and the
                # standing, which is the pair this applies.
                await apply_guild_session_context(
                    session,
                    user,
                    cached,
                    satisfied=(
                        satisfied_providers
                        if isinstance(satisfied_providers, str)
                        else frozenset(satisfied_providers or ())
                    ),
                )
        except GuildAccessError:
            # A community this caller cannot reach right now contributes
            # nothing, exactly as its own ``/g/{guild_id}`` requests would.
            continue
        results.extend(await fetch(session, guild_id))
    return results
