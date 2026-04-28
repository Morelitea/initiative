"""Tests for the auto-purge background worker.

Focus: the per-row skip guard correctly identifies rows that an earlier
cascade pass already queued for deletion, so we don't double-purge them.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.soft_delete_filter import select_including_deleted
from app.models.initiative import Initiative
from app.models.project import Project
from app.services.soft_delete import soft_delete_entity
from app.services.trash_purge import _run_purge_pass
from app.testing.factories import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
)


pytestmark = pytest.mark.integration


async def test_auto_purge_does_not_double_purge_cascaded_descendants(
    session: AsyncSession,
):
    """When an Initiative purge cascades through its Projects, the next
    iteration of the per-model loop must skip those Projects (they're
    already queued for deletion) instead of feeding them to
    ``hard_purge_entity`` a second time.

    Regression: the previous ``row not in session`` guard didn't fire
    because SQLAlchemy keeps deleted-but-unflushed objects in the
    identity map. The replacement uses ``sa_inspect(row).deleted``."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)
    project = await create_project(session, initiative, user)

    # Soft-delete the initiative; the cascade stamps the project too.
    await soft_delete_entity(
        session, initiative, deleted_by_user_id=user.id, retention_days=1
    )
    await session.commit()

    # Backdate purge_at so the auto-purge picks both up.
    past = datetime.now(timezone.utc) - timedelta(days=2)
    refreshed_initiative = (
        await session.exec(
            select_including_deleted(Initiative).where(Initiative.id == initiative.id)
        )
    ).one()
    refreshed_initiative.purge_at = past
    refreshed_project = (
        await session.exec(
            select_including_deleted(Project).where(Project.id == project.id)
        )
    ).one()
    refreshed_project.purge_at = past
    session.add(refreshed_initiative)
    session.add(refreshed_project)
    await session.commit()

    initiative_id = initiative.id
    project_id = project.id

    # One pass — should sweep both rows without raising. If the skip guard
    # is broken we'd hit "Instance is not persisted" on the second
    # hard_purge_entity call against the cascaded project. Drive the inner
    # loop with the test session so the DELETEs land on the test DB
    # (process_trash_purges() opens its own AdminSessionLocal pointed at
    # the dev DB).
    await _run_purge_pass(session, now=datetime.now(timezone.utc))
    await session.commit()

    # Verify against the DB directly — process_trash_purges runs on its
    # own AdminSessionLocal, so the test session's identity map is stale
    # for these rows.
    initiative_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM initiatives WHERE id = :id"),
            {"id": initiative_id},
        )
    ).scalar_one()
    project_count = (
        await session.execute(
            text("SELECT COUNT(*) FROM projects WHERE id = :id"),
            {"id": project_id},
        )
    ).scalar_one()
    assert initiative_count == 0
    assert project_count == 0
