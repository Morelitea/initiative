"""The hourly sweep reaching the audit log.

The sweep destroys rows whose retention has run out, and nobody asked it to:
one record per guild pass, carrying what it took and no actor, because the
session it runs on has no account behind it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.db.soft_delete_filter import select_including_deleted
from app.models.tenant.initiative import Initiative
from app.services.tenant.soft_delete import soft_delete_entity
from app.services.tenant.trash_purge import _purge_all_guilds
from app.testing import recorded
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)

pytestmark = pytest.mark.integration


async def _expired_initiative(session: AsyncSession, guild, user, **overrides):
    """An initiative (with a project under it) whose retention has run out."""
    initiative = await create_initiative(session, guild, user, **overrides)
    await create_project(session, initiative, user)
    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()

    refreshed = (
        await session.exec(
            select_including_deleted(Initiative).where(Initiative.id == initiative.id)
        )
    ).one()
    refreshed.purge_at = datetime.now(timezone.utc) - timedelta(days=2)
    session.add(refreshed)
    await session.commit()
    return initiative


async def test_a_sweep_records_one_pass_per_guild_with_its_counts(
    session: AsyncSession, role_session
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await _expired_initiative(session, guild, user, name="Swept")

    admin = await role_session("app_admin")
    await _purge_all_guilds(admin, now=datetime.now(timezone.utc))

    rows = [
        row
        for row in await recorded(session, AuditEventType.TRASH_PURGED)
        if row.guild_id == guild.id
    ]
    assert len(rows) == 1
    (row,) = rows
    # Nobody signed in caused this, so there is no actor to name.
    assert row.actor_user_id is None
    assert row.target_type is None
    assert row.envelope["detail"]["via"] == "sweep"
    # The project under it went with the initiative, so the initiative is what
    # the pass walked.
    assert row.envelope["detail"]["counts"] == {"initiative": 1}


async def test_a_guild_with_nothing_due_records_nothing(
    session: AsyncSession, role_session
):
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_initiative(session, guild, user, name="Still here")

    admin = await role_session("app_admin")
    await _purge_all_guilds(admin, now=datetime.now(timezone.utc))

    assert [
        row
        for row in await recorded(session, AuditEventType.TRASH_PURGED)
        if row.guild_id == guild.id
    ] == []
