"""The dispatcher imports and exports share.

A data job is a row in its community's own schema (an ``ImportJob`` or an
``ExportJob``) that a background visit claims and runs. The claim is visited
when a wake says a job was queued or ended in the community (:data:`drain`),
and in every active community by the minute pass. Every API process does
this, so the claim is decided in the database: under a transaction-scoped
advisory lock on the community, so two processes never claim in the same
community at once, a community with a job already active gets no second one,
and the oldest queued job goes first.

Each job needs a slot of some kind (an import fetches or applies; an export
renders), and a process runs at most so many of each kind at once. A claimed
job runs as a task of its own, on a system session of its own, and tells its
creator how it ended.

The slow pass sweeps each community for jobs whose row has gone quiet, which
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
from typing import Any, Generic, TypeVar

from sqlalchemy import func, text
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.session import set_rls_context
from app.models.platform.notification import NotificationType
from app.services import guild_work
from app.services.guild_sweeps import Drain, Scope, each_guild
from app.services.platform import user_notifications

logger = logging.getLogger(__name__)

#: Who to tell, what to tell them, and the notification's data.
JobOutcome = tuple[int, NotificationType, dict[str, Any]]

JobT = TypeVar("JobT", bound=SQLModel)
Heartbeat = Callable[[], Awaitable[None]]

#: ``(session, *, guild_id, now, own)``: deal with one community's quiet rows,
#: leaving alone ``own``, the ids of the jobs this process is running there.
#: Returns the notifications to send.
Sweep = Callable[..., Awaitable[list[JobOutcome]]]

#: ``(session, job, *, guild_id, kind)``: run one claimed job to the end and
#: record how it ended. Returns the notification to send, if there is one.
Runner = Callable[..., Awaitable[JobOutcome | None]]


#: Every dispatcher, for :func:`cancel_running_jobs`.
_dispatchers: weakref.WeakSet[Dispatcher[Any]] = weakref.WeakSet()

#: Communities a wake says have a job queued or ended, for the claim.
drain = Drain("data-jobs", settle=0.0)


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
    run: Runner
    #: The jobs this process is running, by ``(guild_id, job_id)``, with the
    #: kind of slot each holds. A job being claimed holds its slot with no
    #: task yet.
    running: dict[tuple[int, int], tuple[str, asyncio.Task[None] | None]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        _dispatchers.add(self)

    def free_slot(self, kind: str) -> bool:
        held = sum(1 for slot, _task in self.running.values() if slot == kind)
        return held < self.slots(kind)

    def own_job_ids(self, guild_id: int) -> list[int]:
        return [job_id for (guild, job_id) in self.running if guild == guild_id]

    async def process(self) -> None:
        """Run passes until one starts nothing, waiting for each pass's jobs.
        Everything queued is dealt with by the time this returns."""
        while True:
            started = await self.dispatch()
            if not started:
                return
            await asyncio.gather(*started)

    async def dispatch(self) -> list[asyncio.Task[None]]:
        """One pass over every active community: sweep, then claim. Returns
        the tasks it started; each runs, records its outcome and notifies on
        its own."""
        started: list[asyncio.Task[None]] = []

        async def start(session: AsyncSession, guild_id: int) -> None:
            task = await self.claim(session, guild_id)
            if task is not None:
                started.append(task)

        await each_guild(
            [(Scope.ACTIVE, self.sweep_stale), (Scope.ACTIVE, start)], name=self.name
        )
        return started

    async def sweep_stale(self, session: AsyncSession, guild_id: int) -> None:
        """Deal with the community's quiet rows, and tell their creators."""
        outcomes = await self.sweep(
            session,
            guild_id=guild_id,
            now=datetime.now(timezone.utc),
            own=self.own_job_ids(guild_id),
        )
        await session.commit()
        await notify(session, outcomes)

    async def claim(
        self, session: AsyncSession, guild_id: int
    ) -> asyncio.Task[None] | None:
        """Start the community's next queued job, when a slot can take it.
        Returns the task it started."""
        if not any(self.free_slot(kind) for kind in self.kinds):
            return None
        claimed = await self._claim(
            session, guild_id=guild_id, now=datetime.now(timezone.utc)
        )
        if claimed is None:
            return None
        job_id, kind = claimed
        key = (guild_id, job_id)
        task = asyncio.create_task(
            self._run(guild_id, job_id, kind),
            name=f"{self.name}-{guild_id}-{job_id}",
        )
        self.running[key] = (kind, task)
        task.add_done_callback(lambda _task, key=key: self.running.pop(key, None))
        return task

    async def cancel_running(self) -> None:
        """Stop every job this process is running, for shutdown. What becomes
        of a stopped job is the sweep's decision, once its row goes quiet."""
        tasks = [task for _kind, task in list(self.running.values()) if task]
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
        # The slot is held from here, so a claim in another cohort's visit
        # running alongside this one finds it taken.
        key = (guild_id, job.id)
        self.running[key] = (kind, None)
        try:
            job.status = self.start_status(kind)
            job.updated_at = now
            session.add(job)
            await session.commit()
        except BaseException:
            self.running.pop(key, None)
            raise
        return job.id, kind

    async def _run(self, guild_id: int, job_id: int, kind: str) -> None:
        """One claimed job, start to finish, on a session of its own. Once it
        ends, the community's next queued job may start."""
        model: Any = self.model
        try:
            async with cohorts.system_session(guild_id) as session:
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
        finally:
            # Out of the slot before the wake, so this process can claim again.
            self.running.pop((guild_id, job_id), None)
        await guild_work.send(guild_work.DATA_JOBS, guild_id)


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
