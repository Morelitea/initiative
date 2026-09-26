"""An app's schedules: Initiative calls the app on the intervals it declares.

A manifest's ``schedules`` name intervals (``{"id": "check-installation",
"every": "15m"}``). For each community that installed the app, Initiative calls
its ``schedule`` hook on that interval, with ``since``: when the call last
succeeded there. The app keeps no timer and needs no address of its own.

Each install's schedules are rows in its community's ``app_schedule_runs``.
:func:`reconcile` keeps them in step with the pinned definition: it runs when
an app is installed and when an install moves to a new version, and the rows
go with the install when it is removed.

:func:`run_due` is the minute pass's visit to one active community. It claims
one due row at a time, with ``FOR UPDATE SKIP LOCKED`` and a lease, so two
workers never run the same row; calls the hook with a ``lifecycle`` token
naming the install; and settles the row. A success is next due one interval
later, plus up to a tenth of it; a failure waits ``every × 2^failures``, at
most ten intervals. An install that is switched off, or whose registration is
not live, is not claimed, and runs when it is back.

Every read and write here is the system engine's.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import Row, delete, or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import cohorts
from app.db.session import set_rls_context
from app.models.tenant.app_schedule_run import AppScheduleRun
from app.models.tenant.guild_app import GuildApp
from app.services.marketplace.registration_lookup import load_registrations
from app.services.marketplace.service_apps import schedule_minutes
from app.services.tenant import app_connection_flows as flows
from app.services.tenant.app_channels import owns_install

logger = logging.getLogger(__name__)

__all__ = ["reconcile", "run_due"]

#: How long a claimed row is held while its app is called.
LEASE = timedelta(minutes=5)
#: The most a success's next call is pushed back, as a share of the interval.
JITTER = 0.1
#: The longest a failing schedule waits, in intervals.
BACKOFF_CAP = 10


def _declared(definition: Optional[Mapping[str, Any]]) -> dict[str, timedelta]:
    """Each schedule the definition declares, by id, with its interval."""
    return {
        schedule["id"]: timedelta(minutes=schedule_minutes(schedule["every"]))
        for schedule in (definition or {}).get("schedules") or []
    }


def _jitter(every: timedelta) -> timedelta:
    return every * random.uniform(0, JITTER)


async def reconcile(
    guild_id: int,
    install_id: int,
    definition: Optional[Mapping[str, Any]],
    *,
    session: Optional[AsyncSession] = None,
) -> None:
    """Give the install a row for each schedule ``definition`` declares, and
    none for any other. A new schedule is due at once, give or take its
    jitter.

    ``session`` is the community's system session, routed, whose caller
    commits; without one the rows are written and committed on a system
    session of their own."""
    if session is None:
        async with cohorts.system_session(guild_id) as own:
            await set_rls_context(own, guild_id=guild_id)
            await reconcile(guild_id, install_id, definition, session=own)
            await own.commit()
        return
    declared = _declared(definition)
    now = datetime.now(timezone.utc)
    await session.exec(
        delete(AppScheduleRun).where(
            col(AppScheduleRun.install_id) == install_id,
            col(AppScheduleRun.schedule_id).not_in(list(declared)),
        )
    )
    if declared:
        await session.exec(
            pg_insert(AppScheduleRun)
            .values(
                [
                    {
                        "install_id": install_id,
                        "schedule_id": schedule_id,
                        "next_due_at": now + _jitter(every),
                    }
                    for schedule_id, every in declared.items()
                ]
            )
            .on_conflict_do_nothing()
        )


async def _claim(session: AsyncSession, live_listings: list[str]) -> Optional[Row]:
    """Lease the community's next due row whose install is switched on and
    whose registration is live, or return ``None``."""
    now = datetime.now(timezone.utc)
    due = (
        select(AppScheduleRun.install_id, AppScheduleRun.schedule_id)
        .join(GuildApp, col(GuildApp.id) == AppScheduleRun.install_id)
        .where(
            col(AppScheduleRun.next_due_at) <= now,
            or_(
                col(AppScheduleRun.claimed_until).is_(None),
                col(AppScheduleRun.claimed_until) <= now,
            ),
            col(GuildApp.enabled).is_(True),
            col(GuildApp.listing_uid).in_(live_listings),
        )
        .order_by(col(AppScheduleRun.next_due_at))
        .limit(1)
        .with_for_update(of=AppScheduleRun, skip_locked=True)
        .cte("due")
    )
    result = await session.exec(
        update(AppScheduleRun)
        .where(
            col(AppScheduleRun.install_id) == due.c.install_id,
            col(AppScheduleRun.schedule_id) == due.c.schedule_id,
        )
        .values(claimed_until=now + LEASE)
        .returning(
            AppScheduleRun.install_id,
            AppScheduleRun.schedule_id,
            AppScheduleRun.last_success_at,
            AppScheduleRun.failures,
        )
    )
    claimed = result.first()
    await session.commit()
    return claimed


async def _settle(
    session: AsyncSession,
    run: Row,
    *,
    every: timedelta,
    started: datetime,
    succeeded: bool,
) -> None:
    now = datetime.now(timezone.utc)
    if succeeded:
        values: dict[str, Any] = {
            "last_success_at": started,
            "failures": 0,
            "next_due_at": now + every + _jitter(every),
        }
    else:
        failures = run.failures + 1
        values = {
            "failures": failures,
            "next_due_at": now + every * min(2**failures, BACKOFF_CAP),
        }
    await session.exec(
        update(AppScheduleRun)
        .where(
            col(AppScheduleRun.install_id) == run.install_id,
            col(AppScheduleRun.schedule_id) == run.schedule_id,
        )
        .values(claimed_until=None, **values)
    )
    await session.commit()


async def run_due(session: AsyncSession, guild_id: int) -> None:
    """Call the ``schedule`` hook for each of the community's due schedules,
    on a session routed into it."""
    live = {
        registration.listing_uid: registration
        for registration in (await load_registrations()).values()
        if registration.live and registration.listing_uid
    }
    while (run := await _claim(session, sorted(live))) is not None:
        app = await session.get(GuildApp, run.install_id)
        registration = live.get(app.listing_uid or "") if app else None
        every = _declared(app.definition).get(run.schedule_id) if app else None
        if (
            app is None
            or registration is None
            or every is None
            or not owns_install(app, registration)
        ):
            # Left to its lease: the install changed since the row was written.
            continue
        started = datetime.now(timezone.utc)
        try:
            await flows.call_hook(
                "schedule",
                public_id=registration.public_id,
                base_url=registration.base_url,
                guild_id=guild_id,
                install_id=run.install_id,
                body={
                    "schedule": run.schedule_id,
                    "since": run.last_success_at.isoformat()
                    if run.last_success_at
                    else None,
                },
            )
            succeeded = True
        except flows.HookError as exc:
            logger.warning(
                "app schedules: %s did not run %s for guild %s (%s)",
                registration.public_id,
                run.schedule_id,
                guild_id,
                exc,
            )
            succeeded = False
        await _settle(session, run, every=every, started=started, succeeded=succeeded)
