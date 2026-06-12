"""Helpers for endpoints that aggregate guild-scoped data across guilds.

Under schema-per-guild a routed session only sees one guild's schema, so a
"global" list (the user's items across every guild they belong to) has to visit
each guild's schema in turn and merge the results. Per-schema ids collide across
guilds, so callers must keep each item's ``guild_id`` and the identity map is
cleared between guilds.
"""

from typing import Awaitable, Callable, Optional, Sequence, TypeVar

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.exc import NoInspectionAvailable
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import set_rls_context
from app.models.guild import GuildMembership

T = TypeVar("T")


async def member_guild_ids(
    session: AsyncSession,
    user_id: int,
    *,
    restrict_to: Optional[Sequence[int]] = None,
) -> list[int]:
    """Guild ids the user belongs to, sorted (optionally intersected with
    ``restrict_to``). Routes to the user-only context so the user's own rows in
    the shared ``guild_memberships`` table are visible."""
    await set_rls_context(session, user_id=user_id)
    rows = await session.exec(
        select(GuildMembership.guild_id).where(GuildMembership.user_id == user_id)
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
) -> list[T]:
    """Route into each guild's schema, call ``fetch(session, guild_id)``, and
    concatenate the results. The identity map is expunged between guilds because
    ids are unique only within a schema, not across them."""
    results: list[T] = []
    for guild_id in guild_ids:
        # Expunge BEFORE each guild: a cached object with this schema's id (from a
        # prior guild, or anything already on the session) would otherwise be
        # returned by the identity map instead of this guild's row.
        session.expunge_all()
        await set_rls_context(session, user_id=user_id, guild_id=guild_id)
        results.extend(await fetch(session, guild_id))
    return results


async def resolve_across_guilds(
    session: AsyncSession,
    user_id: int,
    guild_ids: Sequence[int],
    fetch: Callable[[AsyncSession, int], Awaitable[Optional[T]]],
    choose: Callable[[list[tuple[int, T]]], int],
    *,
    superadmin: bool = False,
) -> Optional[tuple[int, T]]:
    """Resolve ONE entity addressed by a per-guild-ambiguous id.

    Per-schema ids collide across guilds, so an id arriving without guild
    context (iframe downloads, deep links) can match a row in several of the
    user's guild schemas at once. This helper owns the full discipline of that
    resolution so callers can't get it subtly wrong:

    - probes each provisioned schema in the given order (unprovisioned schemas
      are skipped via ``pg_namespace``), expunging the identity map before
      every probe — a cached object with a colliding id would otherwise shadow
      the next schema's row;
    - collects every ``(guild_id, hit)`` candidate and delegates selection to
      ``choose``, which returns the winning guild id and is the ONLY place
      selection policy lives — there is deliberately no default; ``choose`` may
      raise (e.g. an HTTPException for "ambiguous" or "forbidden") to refuse;
    - **re-fetches the winner inside its own routed context.** Every candidate
      collected during probing is detached by the next probe's expunge, so
      handing one back would leak a detached instance whose first lazy
      attribute access blows up (or worse, silently reads stale state).
      Attachment is enforced as a hard invariant below, not assumed from the
      caller's eager-load patterns.

    Returns ``(guild_id, entity)`` with the entity attached to ``session`` and
    the session left routed to the winner's schema (follow-up queries land in
    the right schema), or ``None`` when nothing matched (or the winner vanished
    between probe and re-fetch).

    ``superadmin=True`` routes each probe with the superadmin flag instead of
    the user's own context — for endpoints that authenticate outside the
    normal guild-header flow (e.g. token-authed downloads) and do their own
    access checks on the candidates.
    """
    from app.db.schema_provisioning import guild_schema_name

    schema_by_gid = {int(g): guild_schema_name(int(g)) for g in guild_ids}
    if not schema_by_gid:
        return None

    existing = {
        row.nspname
        for row in (
            await session.execute(
                text("SELECT nspname FROM pg_namespace WHERE nspname = ANY(:ns)"),
                {"ns": list(schema_by_gid.values())},
            )
        ).all()
    }

    async def _route(gid: int) -> None:
        if superadmin:
            await set_rls_context(session, guild_id=gid, is_superadmin=True)
        else:
            await set_rls_context(session, user_id=user_id, guild_id=gid)

    candidates: list[tuple[int, T]] = []
    for gid, schema in schema_by_gid.items():
        if schema not in existing:
            continue
        session.expunge_all()
        await _route(gid)
        hit = await fetch(session, gid)
        if hit is not None:
            candidates.append((gid, hit))

    if not candidates:
        return None

    winner_gid = choose(candidates)
    if winner_gid not in schema_by_gid:
        raise RuntimeError(
            f"resolve_across_guilds: choose() returned guild {winner_gid}, "
            f"not one of the probed guilds {sorted(schema_by_gid)}"
        )

    # The structural fix for the detached-candidate hazard: never return a
    # probe-time object. Fetch the winner fresh in its own routed context.
    session.expunge_all()
    await _route(winner_gid)
    winner = await fetch(session, winner_gid)
    if winner is None:
        return None

    # Hard invariant, not a convention: the resolved entity must be attached.
    try:
        if sa_inspect(winner).detached:
            raise RuntimeError(
                "resolve_across_guilds: re-fetched winner is detached — "
                "fetch() must return an instance loaded on the given session"
            )
    except NoInspectionAvailable:
        pass  # fetch returned a non-ORM value; nothing to enforce

    return winner_gid, winner
