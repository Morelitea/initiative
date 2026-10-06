"""An app's schedules: Initiative calls the app on the intervals it declares.

A manifest's ``schedules`` name intervals (``{"id": "check-installation",
"every": "15m"}``). For each community that installed the app, Initiative calls
its ``schedule`` hook on that interval, with ``since``: when the call last
succeeded there. The app keeps no timer and needs no address of its own.

Each install's schedules are rows in its community's ``plugin_schedule_runs``.
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

A declarative app has no schedules and no hook to call. Its rows are its
community connections' ``health`` checks, by connection id, run the same way:
Initiative makes the check's request with the connection's token, and the
state it reads is reported where a container's verdict is shown, ``ok`` at
once and anything else once two checks in a row have read something other
than ``ok``. A check is next due one interval later whatever it read.

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
from app.models.tenant.plugin_schedule_run import PluginScheduleRun
from app.models.tenant.guild_plugin import GuildPlugin
from app.services.marketplace import declarative
from app.services.marketplace.registration_lookup import (
    RegistrationSnapshot,
    is_declarative,
    load_registrations,
)
from app.services.marketplace.service_plugins import schedule_minutes
from app.services.tenant import plugin_connection_flows as flows
from app.services.tenant import guild_plugins as guild_plugins_service
from app.services.tenant.plugin_channels import owns_install, set_connection_state
from app.services.tenant.plugin_config import without_tokens
from app.db.request_context import SystemGuild

logger = logging.getLogger(__name__)

__all__ = ["reconcile", "run_due"]

#: How long a claimed row is held while its app is called.
LEASE = timedelta(minutes=5)
#: The most a success's next call is pushed back, as a share of the interval.
JITTER = 0.1
#: The longest a failing schedule waits, in intervals.
BACKOFF_CAP = 10


def _declared(definition: Optional[Mapping[str, Any]]) -> dict[str, timedelta]:
    """Each schedule the definition declares, by id, with its interval: a
    container's ``schedules``, or the health checks of a declarative app's
    community connections, by connection id (a declarative app has no
    schedules of its own)."""
    if is_declarative(definition):
        return {
            connection_id: timedelta(minutes=schedule_minutes(health["every"]))
            for connection_id, health in _health_checks(definition).items()
        }
    return {
        schedule["id"]: timedelta(minutes=schedule_minutes(schedule["every"]))
        for schedule in (definition or {}).get("schedules") or []
    }


def _health_checks(definition: Optional[Mapping[str, Any]]) -> dict[str, dict]:
    """Each community connection's ``health``, by connection id."""
    return {
        connection["id"]: connection["health"]
        for connection in (definition or {}).get("connections") or []
        if isinstance(connection, dict)
        and connection.get("scope") == "static"
        and isinstance(connection.get("health"), dict)
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
            await set_rls_context(own, SystemGuild(guild_id))
            await reconcile(guild_id, install_id, definition, session=own)
            await own.commit()
        return
    declared = _declared(definition)
    now = datetime.now(timezone.utc)
    await session.exec(
        delete(PluginScheduleRun).where(
            col(PluginScheduleRun.install_id) == install_id,
            col(PluginScheduleRun.schedule_id).not_in(list(declared)),
        )
    )
    if declared:
        await session.exec(
            pg_insert(PluginScheduleRun)
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
        select(PluginScheduleRun.install_id, PluginScheduleRun.schedule_id)
        .join(GuildPlugin, col(GuildPlugin.id) == PluginScheduleRun.install_id)
        .where(
            col(PluginScheduleRun.next_due_at) <= now,
            or_(
                col(PluginScheduleRun.claimed_until).is_(None),
                col(PluginScheduleRun.claimed_until) <= now,
            ),
            col(GuildPlugin.enabled).is_(True),
            col(GuildPlugin.listing_uid).in_(live_listings),
        )
        .order_by(col(PluginScheduleRun.next_due_at))
        .limit(1)
        .with_for_update(of=PluginScheduleRun, skip_locked=True)
        .cte("due")
    )
    result = await session.exec(
        update(PluginScheduleRun)
        .where(
            col(PluginScheduleRun.install_id) == due.c.install_id,
            col(PluginScheduleRun.schedule_id) == due.c.schedule_id,
        )
        .values(claimed_until=now + LEASE)
        .returning(
            PluginScheduleRun.install_id,
            PluginScheduleRun.schedule_id,
            PluginScheduleRun.last_success_at,
            PluginScheduleRun.failures,
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
    checked: Optional[str] = None,
) -> None:
    """Settle a claimed row. A health check (``checked``, the state it read)
    is next due one interval later whatever it read, and counts the answers
    other than ``ok`` in a row as its failures."""
    now = datetime.now(timezone.utc)
    if checked is not None:
        values: dict[str, Any] = {
            "failures": 0 if checked == "ok" else run.failures + 1,
            "next_due_at": now + every + _jitter(every),
        }
        if checked == "ok":
            values["last_success_at"] = started
    elif succeeded:
        values = {
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
        update(PluginScheduleRun)
        .where(
            col(PluginScheduleRun.install_id) == run.install_id,
            col(PluginScheduleRun.schedule_id) == run.schedule_id,
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
        app = await session.get(GuildPlugin, run.install_id)
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
        # A declarative registration has no hook to call, whatever version
        # an install is still pinned to.
        if registration.declarative or is_declarative(app.definition):
            checked = await _check_health(
                session, app, registration, run, guild_id=guild_id
            )
            await _settle(
                session,
                run,
                every=every,
                started=started,
                succeeded=True,
                checked=checked,
            )
            continue
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


async def _check_health(
    session: AsyncSession,
    app: GuildPlugin,
    registration: RegistrationSnapshot,
    run: Row,
    *,
    guild_id: int,
) -> Optional[str]:
    """Run one community connection's health check and report what it read:
    ``ok`` at once, any other state once two checks in a row have read
    something other than ``ok``. A connection not yet made is not checked,
    and answers ``None``."""
    connection_id = run.schedule_id
    health = _health_checks(app.definition).get(connection_id)
    stored = (app.config or {}).get(connection_id)
    if health is None or not stored:
        return None
    try:
        token = await flows.community_token(
            session,
            app=app,
            public_id=registration.public_id,
            connection_id=connection_id,
            guild_id=guild_id,
        )
    except flows.ConnectionFlowError as exc:
        logger.info(
            "app health: %s has no token for %s in guild %s (%s)",
            registration.public_id,
            connection_id,
            guild_id,
            exc.code,
        )
        state = "unavailable"
    else:
        state = await declarative.health_state(
            app.definition,
            health,
            fields=without_tokens(stored),
            access_token=token.access_token,
        )
    if state == "ok" or run.failures >= 1:
        locked = await guild_plugins_service.lock_install(session, app.id)
        if locked is not None and set_connection_state(locked, connection_id, state):
            session.add(locked)
        await session.commit()
    return state
