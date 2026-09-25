"""The dispatcher imports and exports share.

A data job is a row in its community's own schema (an ``ImportJob`` or an
``ExportJob``) that a background pass claims and runs. Every API process runs
the pass, so the claim is decided in the database: under a transaction-scoped
advisory lock on the community, so two passes never claim in the same
community at once, a community with a job already active gets no second one,
and the oldest queued job goes first.

Each job needs a slot of some kind (an import fetches or applies; an export
renders), and a process runs at most so many of each kind at once. A claimed
job runs as a task of its own, on a system session of its own, and tells its
creator how it ended.

Each pass first sweeps the community for jobs whose row has gone quiet, which
nobody is running any more. What happens to one depends on the job type, so
the sweep is the worker's. Jobs this process is running are left out of it:
they are known to be alive.

Bookkeeping runs on the system engine, routed into the community with
``guild_id`` alone; the policies' system leg names that login. Notifications
are written from the unrouted system context, since the shared notifications
table is in no community's schema.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, Protocol, TypeVar

from sqlalchemy import func, text
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.guild import Guild, GuildStatus
from app.models.platform.notification import NotificationType
from app.services.platform import user_notifications

logger = logging.getLogger(__name__)

#: Who to tell, what to tell them, and the notification's data.
JobOutcome = tuple[int, NotificationType, dict[str, Any]]

JobT = TypeVar("JobT", bound=SQLModel)
JobT_contra = TypeVar("JobT_contra", bound=SQLModel, contravariant=True)

Heartbeat = Callable[[], Awaitable[None]]


class Sweep(Protocol):
    """Deal with one community's quiet rows. ``own`` is the ids of the jobs
    this process is running there, which the sweep leaves alone. Returns the
    notifications to send."""

    async def __call__(
        self,
        session: AsyncSession,
        *,
        guild_id: int,
        now: datetime,
        own: list[int],
    ) -> list[JobOutcome]: ...


class Runner(Protocol[JobT_contra]):
    """Run one claimed job to the end and record how it ended. Returns the
    notification to send, if there is one."""

    async def __call__(
        self,
        session: AsyncSession,
        job: JobT_contra,
        *,
        guild_id: int,
        kind: str,
    ) -> JobOutcome | None: ...


#: Every dispatcher, for :func:`cancel_running_jobs`.
_dispatchers: weakref.WeakSet[Dispatcher[Any]] = weakref.WeakSet()


@dataclass(eq=False)
class Dispatcher(Generic[JobT]):
    """Claims and runs one type of data job.

    ``kind_of`` says which kind of slot a queued job needs, ``start_status``
    what a claimed job of that kind moves to, and ``slots`` how many jobs of a
    kind this process runs at once (read on every claim, so a changed limit
    applies to the next one). ``active`` is every status a job holds while it
    runs; a community with a job in one of them is not claimed from.
    """

    #: Names the job type in task names and log lines.
    name: str
    model: type[JobT]
    #: The advisory-lock namespace this job type claims under.
    lock_namespace: int
    queued: str
    active: tuple[str, ...]
    kinds: tuple[str, ...]
    kind_of: Callable[[JobT], str]
    start_status: Callable[[str], str]
    slots: Callable[[str], int]
    sweep: Sweep
    run: Runner[JobT]
    #: The jobs this process is running, by ``(guild_id, job_id)``, with the
    #: kind of slot each holds.
    running: dict[tuple[int, int], tuple[str, asyncio.Task[None]]] = field(
        default_factory=dict
    )
    #: The community the last claim was made in; the next pass starts after
    #: it, so no community is always served first.
    last_guild_id: int = 0

    def __post_init__(self) -> None:
        _dispatchers.add(self)

    def free_slot(self, kind: str) -> bool:
        held = sum(1 for slot, _task in self.running.values() if slot == kind)
        return held < self.slots(kind)

    def own_job_ids(self, guild_id: int) -> list[int]:
        return [job_id for (guild, job_id) in self.running if guild == guild_id]

    async def process(self) -> None:
        """Run passes until one starts nothing, waiting for each pass's jobs.

        Everything queued is dealt with by the time this returns. The
        background loop calls :meth:`dispatch` instead, which does not wait.
        """
        while True:
            started = await self.dispatch()
            if not started:
                return
            await asyncio.gather(*started)

    async def dispatch(self) -> list[asyncio.Task[None]]:
        """One pass: sweep every active community, then start what the free
        slots can take, at most one job per community. Returns the tasks it
        started; each runs, records its outcome and notifies on its own."""
        now = datetime.now(timezone.utc)
        started: list[asyncio.Task[None]] = []
        async with db_session.SystemSessionLocal() as session:
            await set_rls_context(session)
            guild_ids = list(
                await session.exec(
                    select(Guild.id)
                    .where(Guild.status == GuildStatus.active.value)
                    .order_by(Guild.id.asc())
                )
            )
            last = self.last_guild_id
            guild_ids = [g for g in guild_ids if g > last] + [
                g for g in guild_ids if g <= last
            ]
            for guild_id in guild_ids:
                session.expunge_all()
                await set_rls_context(session, guild_id=guild_id)
                outcomes = await self.sweep(
                    session,
                    guild_id=guild_id,
                    now=now,
                    own=self.own_job_ids(guild_id),
                )
                await session.commit()
                await notify(session, outcomes)
                if not any(self.free_slot(kind) for kind in self.kinds):
                    continue
                await set_rls_context(session, guild_id=guild_id)
                claimed = await self._claim(session, guild_id=guild_id, now=now)
                if claimed is None:
                    continue
                job_id, kind = claimed
                key = (guild_id, job_id)
                task = asyncio.create_task(
                    self._run(guild_id, job_id, kind),
                    name=f"{self.name}-{guild_id}-{job_id}",
                )
                self.running[key] = (kind, task)
                task.add_done_callback(
                    lambda _task, key=key: self.running.pop(key, None)
                )
                self.last_guild_id = guild_id
                started.append(task)
        return started

    async def cancel_running(self) -> None:
        """Stop every job this process is running, for shutdown. What becomes
        of a stopped job is the sweep's decision, once its row goes quiet."""
        tasks = [task for _kind, task in list(self.running.values())]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def _claim(
        self, session: AsyncSession, *, guild_id: int, now: datetime
    ) -> tuple[int, str] | None:
        """Claim the community's oldest queued job, when it has no job active
        and a slot of the right kind is free.

        Decided under a lock on the community, so two passes, on two
        processes, cannot each claim one. The claim is committed before the
        job starts, so a crash leaves a quiet row for the sweep rather than a
        queued one that looks untouched.
        """
        model: Any = self.model
        await session.exec(
            text("SELECT pg_advisory_xact_lock(:ns, :guild)"),
            params={"ns": self.lock_namespace, "guild": guild_id},
        )
        active = (
            await session.exec(
                select(func.count())
                .select_from(model)
                .where(model.status.in_(self.active))
            )
        ).one()
        job: Any = (
            None
            if active
            else (
                await session.exec(
                    select(model)
                    .where(model.status == self.queued)
                    .order_by(model.created_at.asc())
                    .limit(1)
                    .with_for_update()
                )
            ).first()
        )
        if job is None:
            await session.commit()
            return None
        kind = self.kind_of(job)
        if not self.free_slot(kind):
            await session.commit()
            return None
        job.status = self.start_status(kind)
        job.updated_at = now
        session.add(job)
        await session.commit()
        assert job.id is not None
        return job.id, kind

    async def _run(self, guild_id: int, job_id: int, kind: str) -> None:
        """One claimed job, start to finish, on a session of its own."""
        model: Any = self.model
        try:
            async with db_session.SystemSessionLocal() as session:
                await set_rls_context(session, guild_id=guild_id)
                job = (
                    await session.exec(select(model).where(model.id == job_id))
                ).one_or_none()
                if job is None:
                    return
                # End the read here rather than holding it open for as long as
                # the job runs.
                await session.commit()
                outcome = await self.run(session, job, guild_id=guild_id, kind=kind)
                if outcome is not None:
                    await notify(session, [outcome])
        except Exception:
            logger.exception(
                "%s job task failed id=%s guild=%s", self.name, job_id, guild_id
            )


async def cancel_running_jobs() -> None:
    """Stop every data job this process is running, for shutdown."""
    for dispatcher in list(_dispatchers):
        await dispatcher.cancel_running()


async def notify(session: AsyncSession, outcomes: list[JobOutcome]) -> None:
    """Tell each job's creator how it ended."""
    if not outcomes:
        return
    # From the UNROUTED system context: the guild routing carries no user
    # GUC, so the shared notifications table's own-row policies would refuse
    # the insert there.
    await set_rls_context(session)
    for user_id, notification_type, data in outcomes:
        await user_notifications.create_notification(
            session,
            user_id=user_id,
            notification_type=notification_type,
            data=data,
        )
    await session.commit()


async def provisioned_guild_ids(session: AsyncSession) -> list[int]:
    """Every community whose schema exists, whatever its status.

    Expiry has to reach a community that is read-only, suspended, held or
    deleted-but-retained as well as an active one: each keeps its schema, and
    the files its jobs left behind, until it is purged.
    """
    from app.db.schema_provisioning import guild_schema_name

    guild_ids = list(await session.exec(select(Guild.id).order_by(Guild.id.asc())))
    schemas = set(
        (await session.exec(text("SELECT nspname FROM pg_namespace"))).scalars()
    )
    return [g for g in guild_ids if guild_schema_name(g) in schemas]
