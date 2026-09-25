"""One walk over the communities, for every background sweep that visits them.

A sweep that works community by community (publishing scheduled posts, purging
trash, delivering webhooks, claiming data jobs) hands its per-community function
to :func:`each_guild`, which reads the communities once and visits each on a
system session from that community's cohort. Each visit is routed into the
community, run and committed on its own, so one that fails is rolled back and
logged and the rest carry on.

A cohort's communities are visited one after another on one session, and the
cohorts side by side, a few at a time, so a pass holds at most one connection
per cohort.

Work that is woken rather than timed goes through a :class:`Drain`: a
community said to have work waiting is added to it, and its loop visits just
those communities.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from enum import Enum
from typing import NamedTuple

from sqlalchemy import text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import metrics
from app.db import cohorts
from app.db.session import set_rls_context
from app.models.platform.guild import LIVE_STATUS_VALUES, Guild, GuildStatus

logger = logging.getLogger(__name__)

#: How many cohorts a pass visits at once. Each holds one system connection
#: while its communities are visited.
COHORTS_AT_ONCE = 4


class Scope(Enum):
    """Which communities a visit is for."""

    #: Communities taking writes.
    ACTIVE = "active"
    #: Communities their members can still read: active and read-only.
    LIVE = "live"
    #: Every community whose schema exists, whatever its status. A read-only,
    #: suspended, held or deleted-but-retained community keeps its schema, and
    #: what its jobs left behind, until it is purged.
    PROVISIONED = "provisioned"

    def admits(self, status: str, *, provisioned: bool) -> bool:
        if self is Scope.ACTIVE:
            return status == GuildStatus.active.value
        if self is Scope.LIVE:
            return status in LIVE_STATUS_VALUES
        return provisioned


#: ``(session, guild_id)``: one sweep's work in one community, on a session
#: routed into it. What it returns is ignored.
Visit = Callable[[AsyncSession, int], Awaitable[object]]


class Scan(NamedTuple):
    """A sweep in two halves: a visit to each community it admits, and what it
    does with what the visits found once the pass has been everywhere."""

    scope: Scope
    visit: Visit
    finish: Callable[[], Awaitable[None]]


async def each_guild(
    visits: Sequence[tuple[Scope, Visit]],
    *,
    name: str,
    only: Iterable[int] | None = None,
    scans: Sequence[Scan] = (),
) -> None:
    """Run every visit in every community its scope admits, then finish each
    scan.

    ``only`` restricts the pass to those communities. ``name`` labels the log
    lines and the pass-duration metric."""
    started = time.monotonic()
    every = [*visits, *((scan.scope, scan.visit) for scan in scans)]
    by_cohort: dict[int, list[tuple[int, str, bool]]] = {}
    for community in await _communities(every, only):
        by_cohort.setdefault(cohorts.cohort_of(community[0]), []).append(community)
    limit = asyncio.Semaphore(COHORTS_AT_ONCE)

    async def visit_cohort(communities: list[tuple[int, str, bool]]) -> None:
        try:
            async with limit, cohorts.system_session(communities[0][0]) as session:
                for guild_id, status, provisioned in communities:
                    # Ids repeat across schemas.
                    session.expunge_all()
                    for scope, visit in every:
                        if scope.admits(status, provisioned=provisioned):
                            await _visit(session, visit, guild_id, name=name)
        except Exception:
            logger.exception(
                "%s: cohort %s failed", name, cohorts.cohort_of(communities[0][0])
            )

    await asyncio.gather(*(visit_cohort(c) for c in by_cohort.values()))
    for scan in scans:
        try:
            await scan.finish()
        except Exception:
            logger.exception("%s: finishing a scan failed", name)
    metrics.sweep_pass_duration.labels(name).observe(time.monotonic() - started)


async def _communities(
    visits: Sequence[tuple[Scope, Visit]], only: Iterable[int] | None
) -> list[tuple[int, str, bool]]:
    """Each community in the pass, with its status and whether its schema
    exists."""
    from app.db.schema_provisioning import guild_schema_name

    statement = select(Guild.id, Guild.status).order_by(col(Guild.id).asc())
    if only is not None:
        statement = statement.where(col(Guild.id).in_(list(only)))
    async with cohorts.system_session(None) as session:
        await set_rls_context(session)
        rows = (await session.exec(statement)).all()
        schemas: set[str] = set()
        if any(scope is Scope.PROVISIONED for scope, _visit in visits):
            schemas = set(
                (await session.exec(text("SELECT nspname FROM pg_namespace"))).scalars()
            )
    return [
        (guild_id, status, guild_schema_name(guild_id) in schemas)
        for guild_id, status in rows
        if guild_id is not None
    ]


async def _visit(
    session: AsyncSession, visit: Visit, guild_id: int, *, name: str
) -> None:
    try:
        await set_rls_context(session, guild_id=guild_id)
        await visit(session, guild_id)
        await session.commit()
    except Exception:
        logger.exception("%s: visit failed guild=%s", name, guild_id)
        await session.rollback()


class Drain:
    """Communities said to have work waiting, and the loop that visits them.

    :meth:`wake` adds a community and returns at once. :meth:`run` waits for
    one, lets ``settle`` seconds of further wakes gather, and visits them all
    in one pass restricted to them.
    """

    def __init__(self, name: str, *, settle: float) -> None:
        self.name = name
        self.settle = settle
        self.pending: set[int] = set()
        self._woken = asyncio.Event()

    def wake(self, guild_id: int) -> None:
        self.pending.add(guild_id)
        self._woken.set()

    async def run(self, visits: Sequence[tuple[Scope, Visit]]) -> None:
        while True:
            await self._woken.wait()
            await asyncio.sleep(self.settle)
            self._woken.clear()
            only, self.pending = self.pending, set()
            try:
                await each_guild(visits, name=self.name, only=only)
            except Exception:
                logger.exception("%s: pass failed", self.name)
