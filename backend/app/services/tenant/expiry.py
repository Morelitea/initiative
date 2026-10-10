"""Rows a community's schema keeps for a while and then lets go.

Each record states its own rule beside its own code: how long the change log
keeps events, which delivery records go with them, which recent views a person
no longer keeps. :func:`prepare` runs every rule in order, in one visit per
community and one transaction, from the hourly pass. A rule is one statement
against an index, so a community with nothing due costs an index probe per rule.

Rules run wherever the community's schema exists, whatever its status: how long
something is kept does not wait for the community to be active again.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.request_context import Unattributed
from app.db.session import set_rls_context
from app.models.platform.user import User
from app.services.guild_sweeps import Visit


@dataclass
class Expiring:
    """What one community's rules share in a pass."""

    now: datetime
    #: Each account whose recent-tabs limit is not the default, with its limit.
    tab_limits: dict[int, int]
    #: Transactions the change log let go in this visit.
    expired_txns: set[int] = field(default_factory=set)


Rule = Callable[[AsyncSession, Expiring], Awaitable[None]]


def _rules() -> tuple[Rule, ...]:
    """Every rule, in the order they run: a record that goes with another runs
    after it."""
    from app.services.tenant import (
        change_log,
        outbox_poller,
        plugin_hooks,
        recent_views,
    )

    return (
        change_log.expire,
        outbox_poller.expire_deliveries,
        plugin_hooks.expire_deliveries,
        recent_views.expire,
    )


async def _tab_limits() -> dict[int, int]:
    """Each account whose recent-tabs limit is not the default, read once for
    the pass: a community's own session reads no accounts."""
    from app.services.tenant.recent_views import (
        DEFAULT_RECENT_VIEWS,
        clamp_recent_limit,
    )

    async with cohorts.system_session(None) as session:
        await set_rls_context(session, Unattributed())
        rows = await session.exec(
            select(col(User.id), col(User.recent_tabs_limit)).where(
                col(User.recent_tabs_limit) != DEFAULT_RECENT_VIEWS
            )
        )
        return {
            user_id: clamp_recent_limit(limit)
            for user_id, limit in rows.all()
            if user_id is not None
        }


async def prepare() -> Visit:
    """The visit that runs every rule in one community, with what the pass
    shares read once."""
    now = datetime.now(timezone.utc)
    tab_limits = await _tab_limits()
    rules = _rules()

    async def visit(session: AsyncSession, guild_id: int) -> None:
        expiring = Expiring(now=now, tab_limits=tab_limits)
        for rule in rules:
            await rule(session, expiring)

    return visit
