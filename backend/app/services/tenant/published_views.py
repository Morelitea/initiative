"""A dashboard that shows everyone the same rows.

A tile ordinarily resolves against whoever is looking at it: the same widget
answers differently for two people, because each reaches different things. That
is right almost always, and wrong for the one case a dashboard is often built
for — a figure that has to be common ground. A status board where half the room
sees a smaller number is not a status board.

A **published view** is how a dashboard says "these rows, for everybody who can
open me". It is a grant rather than an impersonation: a ``resource_grants`` row
whose grantee is the dashboard says the resource is readable *through* it, and
``public.resource_access`` answers on that row only while
``app.via_dashboard_id`` names that dashboard — which the fetch path sets after
the dashboard's own four gates have admitted the reader.

Three rules live here, and the module exists because each of them is a question
about somebody who is not the person asking:

* **Publishing reaches no further than the author.** A grant is written only
  over a resource its author can read as they publish it.
* **It fails closed on the author.** That reach is re-derived on every fetch,
  as them — not read back from when the row was written.
* **Editing is locked to the same reach.** The statement decides which of the
  published rows a reader sees, so changing one is the act of writing it.

Two gates are never waived. A published view crosses no guild and no
initiative: it relaxes the discretionary layer *inside* one initiative, and a
reader still has to be in it.

**Standing in somebody else's shoes.** Deciding what the *author* reaches, in
the middle of a request belonging to a *reader*, means neither of two things
may leak into the answer: the reader's own request-scoped state, and the
system engine's authority. :func:`_as_author` handles the first — the author's
role and their own "Full access" initiatives, and no grant of anybody's. The
second is why the row is loaded on a session of its own: it is routed into the
guild, so the guild's policies decide, and the answer is then taken from the
same DAC function every endpoint asks.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Sequence

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.pam_context import active_grant, set_active_grant
from app.core.role_context import (
    override_sharing_initiatives,
    set_override_sharing_initiatives,
)
from app.core.tools import Tool
from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.platform.user import User, UserStatus
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant


async def published_by(session: Any, dashboard_id: int) -> list[ResourceGrant]:
    """What this dashboard publishes over, oldest first.

    The grants *are* the list — "what does this show that a reader could not
    otherwise see" is a query rather than an inference.
    """
    rows = await session.exec(
        select(ResourceGrant)
        .where(ResourceGrant.dashboard_id == dashboard_id)
        .order_by(ResourceGrant.id)
    )
    return list(rows)


def target(grant: ResourceGrant) -> tuple[Tool, int]:
    """What one published-over row is about."""
    return Tool(grant.resource_type), grant.resource_id


def read_grant(
    dashboard_id: int, kind: Tool, resource_id: int, **carried: Any
) -> ResourceGrant:
    """One published-over row. Read, always — a dashboard never writes."""
    return ResourceGrant(
        resource_type=kind,
        resource_id=resource_id,
        dashboard_id=dashboard_id,
        level=ResourceAccessLevel.read,
        **carried,
    )


@asynccontextmanager
async def _as_author(
    author_id: int, guild_id: int, override_ids: frozenset[int]
) -> AsyncIterator[None]:
    """Decide as *author* rather than as whoever is asking.

    The two pieces of request-scoped standing that a sync DAC check reads
    without being handed them: the "Full access" initiatives, which become the
    author's, and any live PAM grant, which becomes none — a published view
    rests on standing access, and a time-bound grant is not that.

    The role is not here because it travels explicitly, as an argument.
    """
    held_override = override_sharing_initiatives()
    held_grant = active_grant()
    set_override_sharing_initiatives(override_ids)
    set_active_grant(None, None)
    try:
        yield
    finally:
        set_override_sharing_initiatives(held_override or None)
        set_active_grant(*(held_grant or (None, None)))


async def _standing(
    session: AsyncSession, author_id: int, guild_id: int
) -> Optional[tuple[User, str]]:
    """The author, and the role they hold in this guild. ``None`` where they
    have no standing at all.

    A suspended account and one that has left the guild are the same answer
    here: nothing they published still stands.

    Read before the session is routed into the guild. Identity lives in
    ``public``, and inside a guild schema a person is read through that guild's
    own projection — which is not what this needs.
    """
    await set_rls_context(session)
    author = await session.get(User, author_id)
    # Suspension takes every guild away, which is exactly what a published view
    # rests on. Anything but an active account publishes nothing.
    if author is None or author.status != UserStatus.active:
        return None
    membership = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.user_id == author_id,
                GuildMembership.guild_id == guild_id,
            )
        )
    ).first()
    if membership is None:
        return None
    role = membership.role
    return author, (role.value if isinstance(role, GuildRole) else str(role))


async def author_still_reaches(grants: Sequence[ResourceGrant], guild_id: int) -> bool:
    """Whether every grant's author can still read what they published.

    Re-derived here rather than trusted from when the row was written: a
    published view serves on somebody's standing say-so, and an author who has
    lost the access, left, or been suspended is no longer saying it.

    Read on a session of its own, routed into the guild, so the request's own
    session keeps the context it was serving with.
    """
    if not grants:
        return False
    from app.api import resource_access
    from app.services import rls as rls_service

    # Looked up on the module rather than bound at import: which database the
    # system engine points at is decided after this module is read.
    async with db_session.AdminSessionLocal() as session:
        for grant in grants:
            author_id = grant.created_by
            if author_id is None:
                return False
            standing = await _standing(session, author_id, guild_id)
            if standing is None:
                return False
            author, role = standing
            # Now into the guild, where the resource lives and its own policies
            # decide what is there to be read.
            session.expunge_all()
            await set_rls_context(session, guild_id=guild_id, guild_role="admin")
            kind, resource_id = target(grant)
            cfg = resource_access.RESOURCE_ACCESS[kind]
            if cfg.loader is None:
                return False
            row = await cfg.loader(session, resource_id)
            if row is None:
                return False
            override_ids = frozenset(
                await rls_service.override_sharing_initiative_ids(
                    session, user_id=author_id
                )
            )
            async with _as_author(author_id, guild_id, override_ids):
                try:
                    resource_access.authorize(
                        kind, row, author, access="read", guild_role=role
                    )
                except HTTPException:
                    return False
    return True


def statements_in(
    definition: dict[str, Any] | None, config: dict[str, Any] | None = None
) -> list[str]:
    """Every statement this dashboard would run, in widget order.

    Read the way the fetch path reads it: the instance config layers over the
    definition, so a statement a config override supplies is one of these. The
    two have to be looked at together or a check on the definition alone is a
    check on something that never runs.
    """
    widgets = (definition or {}).get("widgets")
    if not isinstance(widgets, list):
        return []
    overrides = (config or {}).get("widgets") or {}
    found: list[str] = []
    for widget in widgets:
        if not isinstance(widget, dict):
            continue
        binding = widget.get("binding")
        if not isinstance(binding, dict):
            continue
        override = overrides.get(str(widget.get("id")))
        effective = {**binding, **(override if isinstance(override, dict) else {})}
        if effective.get("source") != "query":
            continue
        sql = effective.get("sql")
        if isinstance(sql, str) and sql.strip():
            found.append(sql)
    return found


def names_the_reader(
    definition: dict[str, Any] | None, config: dict[str, Any] | None = None
) -> bool:
    """Whether anything here asks about whoever is looking at it.

    A published view is one set of numbers for everybody, and ``me`` is what
    makes a statement answer differently per person — so the two cannot be true
    of the same dashboard. A statement this cannot read is not one that names
    the reader; whatever is wrong with it is refused where statements are
    checked.
    """
    from app.services.query import QueryError, resolve

    for sql in statements_in(definition, config):
        try:
            if resolve(sql).names_the_reader:
                return True
        except QueryError:
            continue
    return False


async def editor_reaches_what_is_published(
    session: Any,
    dashboard_id: int,
    user: User,
    guild_context: Any,
) -> bool:
    """Whether *user* could have written what this dashboard publishes.

    The statement decides which of the published rows a reader sees, so editing
    one is the act of writing it — and somebody who does not reach those
    resources themselves may not do it through a dashboard that does.

    Asked as the editor, on their own session, through the ordinary path: this
    is the same answer the resource's own endpoint would give them.
    """
    from app.api import resource_access

    for grant in await published_by(session, dashboard_id):
        kind, resource_id = target(grant)
        try:
            await resource_access.load_authorized(
                session, kind, resource_id, user, guild_context
            )
        except HTTPException:
            return False
    return True


async def serves_through(
    session: Any, dashboard_id: int, guild_id: int
) -> Optional[int]:
    """The dashboard to read through, or ``None`` to read as the viewer.

    ``None`` covers both "nothing is published" and "what was published no
    longer stands". They are the same thing to a fetch — the tile answers from
    the reader's own access — and the caller says which of the two it was.
    """
    grants = await published_by(session, dashboard_id)
    if not grants:
        return None
    return dashboard_id if await author_still_reaches(grants, guild_id) else None
