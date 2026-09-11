"""Archived and trashed content is read-only, and the database is what says so.

These run under the real ``app_user`` login with a routed context rather than the
superuser-backed ``session`` fixture: the RESTRICTIVE policies are half the
subject, and a superuser would show none of them. The triggers bind everyone, so
they would show either way — but the split is exactly what these pin down, and
mixing the two sessions would hide which half refused a write.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.errors import dbapi_sqlstate
from app.db.frozen import FROZEN_SQLSTATE
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_task,
    create_user,
)

pytestmark = pytest.mark.database


@pytest.fixture
async def workspace(session):
    """A member, a guild, an initiative, a project and a task inside it."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await create_guild_membership(
        session, user=user, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild=guild, creator=user)
    project = await create_project(session, initiative=initiative, owner=user)
    task = await create_task(session, project=project)
    return user, guild, initiative, project, task


@pytest.fixture
async def routed(role_session, workspace):
    """The member's own session, routed into the guild — the request path."""
    user, guild, *_ = workspace
    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.member.value
    )
    yield s
    # Every read here opens a transaction, and an open one holds locks the
    # per-test schema teardown then waits on.
    await s.rollback()


@pytest.fixture
async def admin_routed(role_session, workspace):
    """The same guild, entered as its admin.

    Hard delete is purge, and ``soft_delete_admin_purge`` already admits only a
    routed guild admin — so a member's DELETE never reaches the freeze at all.
    The delete half of the rule is only observable from here.
    """
    user, guild, *_ = workspace
    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=user.id, guild_id=guild.id, guild_role=GuildRole.admin.value
    )
    yield s
    await s.rollback()


async def _frozen(
    s: AsyncSession, kind: str, rid: int, trashed_ok: bool = False
) -> bool:
    return (
        await s.exec(
            text("SELECT public.resource_frozen(:kind, :rid, :trashed_ok)").bindparams(
                kind=kind, rid=rid, trashed_ok=trashed_ok
            )
        )
    ).scalar()


async def _archive(session, model, row_id: int) -> None:
    """Archive through the superuser fixture, so the test sets up the state
    rather than exercising the path that reaches it."""
    await session.exec(
        text(f"UPDATE {model} SET is_archived = true WHERE id = :id").bindparams(
            id=row_id
        )
    )
    await session.commit()


async def _trash(session, model, row_id: int) -> None:
    await session.exec(
        text(f"UPDATE {model} SET deleted_at = now() WHERE id = :id").bindparams(
            id=row_id
        )
    )
    await session.commit()


class TestResourceFrozen:
    """The one walk both halves defer to."""

    async def test_live_content_is_not_frozen(self, routed, workspace):
        _u, _g, initiative, project, task = workspace
        assert await _frozen(routed, "initiatives", initiative.id) is False
        assert await _frozen(routed, "projects", project.id) is False
        assert await _frozen(routed, "tasks", task.id) is False

    async def test_an_archived_project_freezes_its_tasks(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, task = workspace
        await _archive(session, "projects", project.id)
        assert await _frozen(routed, "projects", project.id) is True
        assert await _frozen(routed, "tasks", task.id) is True

    async def test_an_archived_initiative_freezes_everything_under_it(
        self, session, routed, workspace
    ):
        _u, _g, initiative, project, task = workspace
        await _archive(session, "initiatives", initiative.id)
        assert await _frozen(routed, "projects", project.id) is True
        assert await _frozen(routed, "tasks", task.id) is True

    async def test_a_trashed_parent_ends_the_walk_for_a_delete(
        self, session, routed, workspace
    ):
        """What is under a trashed row is being purged, not edited."""
        _u, _g, _i, project, task = workspace
        await _trash(session, "projects", project.id)
        assert await _frozen(routed, "tasks", task.id) is True
        assert await _frozen(routed, "tasks", task.id, trashed_ok=True) is False

    async def test_an_archived_parent_does_not_end_it(self, session, routed, workspace):
        """Archived is not on the way anywhere: a delete under it is refused."""
        _u, _g, _i, project, task = workspace
        await _archive(session, "projects", project.id)
        assert await _frozen(routed, "tasks", task.id, trashed_ok=True) is True

    async def test_an_unknown_kind_and_a_null_id_are_not_frozen(self, routed):
        assert await _frozen(routed, "nothing_like_this", 1) is False
        assert (
            await routed.exec(
                text("SELECT public.resource_frozen('tasks', NULL::bigint)")
            )
        ).scalar() is False


class TestAncestorFreeze:
    """A row whose parent is frozen takes no writes."""

    async def test_a_task_in_an_archived_project_cannot_be_updated(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, task = workspace
        await _archive(session, "projects", project.id)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE tasks SET title = 'edited' WHERE id = :id").bindparams(
                    id=task.id
                )
            )
        assert "frozen_ancestor_update" in str(excinfo.value)

    async def test_a_task_cannot_be_added_to_an_archived_project(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, task = workspace
        await _archive(session, "projects", project.id)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text(
                    "INSERT INTO tasks (project_id, title, task_status_id, position) "
                    "SELECT :pid, 'new', task_status_id, 1 FROM tasks WHERE id = :id"
                ).bindparams(pid=project.id, id=task.id)
            )
        assert "frozen_ancestor_insert" in str(excinfo.value)

    async def test_a_refused_delete_says_so_rather_than_removing_nothing(
        self, session, admin_routed, workspace
    ):
        """DELETE has no WITH CHECK, so this half is a trigger — and the point
        of the trigger is that the caller hears about it."""
        _u, _g, _i, project, task = workspace
        await _archive(session, "projects", project.id)
        with pytest.raises(DBAPIError) as excinfo:
            await admin_routed.exec(
                text("DELETE FROM tasks WHERE id = :id").bindparams(id=task.id)
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_a_purge_under_a_trashed_project_still_runs(
        self, session, admin_routed, workspace
    ):
        _u, _g, _i, project, task = workspace
        await _trash(session, "projects", project.id)
        result = await admin_routed.exec(
            text("DELETE FROM tasks WHERE id = :id").bindparams(id=task.id)
        )
        assert result.rowcount == 1
        await admin_routed.commit()

    async def test_live_content_is_untouched(self, routed, workspace):
        _u, _g, _i, _p, task = workspace
        await routed.exec(
            text("UPDATE tasks SET title = 'fine' WHERE id = :id").bindparams(
                id=task.id
            )
        )
        await routed.commit()

    async def test_reading_frozen_content_is_the_point_of_keeping_it(
        self, session, routed, workspace
    ):
        _u, _g, initiative, project, task = workspace
        await _archive(session, "initiatives", initiative.id)
        rows = (
            await routed.exec(
                text("SELECT id FROM tasks WHERE id = :id").bindparams(id=task.id)
            )
        ).all()
        assert len(rows) == 1


class TestRowFreeze:
    """A frozen row may change only the columns that describe the freeze."""

    async def test_an_archived_project_cannot_be_renamed(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, _t = workspace
        await _archive(session, "projects", project.id)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE projects SET name = 'renamed' WHERE id = :id").bindparams(
                    id=project.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_an_archived_project_can_be_unarchived(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, _t = workspace
        await _archive(session, "projects", project.id)
        await routed.exec(
            text(
                "UPDATE projects SET is_archived = false, updated_at = now() "
                "WHERE id = :id"
            ).bindparams(id=project.id)
        )
        await routed.commit()

    async def test_a_trashed_project_can_be_restored(self, session, routed, workspace):
        _u, _g, _i, project, _t = workspace
        await _trash(session, "projects", project.id)
        await routed.exec(
            text(
                "UPDATE projects SET deleted_at = NULL, deleted_by = NULL, "
                "purge_at = NULL WHERE id = :id"
            ).bindparams(id=project.id)
        )
        await routed.commit()

    async def test_unarchiving_cannot_smuggle_an_edit_along(
        self, session, routed, workspace
    ):
        _u, _g, _i, project, _t = workspace
        await _archive(session, "projects", project.id)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text(
                    "UPDATE projects SET is_archived = false, name = 'renamed' "
                    "WHERE id = :id"
                ).bindparams(id=project.id)
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE

    async def test_an_archived_task_is_read_only(self, session, routed, workspace):
        _u, _g, _i, _p, task = workspace
        await _archive(session, "tasks", task.id)
        with pytest.raises(DBAPIError) as excinfo:
            await routed.exec(
                text("UPDATE tasks SET title = 'edited' WHERE id = :id").bindparams(
                    id=task.id
                )
            )
        assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE


class TestWhatTheFreezeLeavesAlone:
    async def test_a_reader_still_records_where_they_were(
        self, session, routed, workspace
    ):
        """Reading frozen content writes rows. If the freeze reached them,
        opening an archived project would be an error."""
        user, _g, _i, project, _t = workspace
        await _archive(session, "projects", project.id)
        await routed.exec(
            text(
                "INSERT INTO recent_views"
                " (user_id, entity_type, entity_id, last_viewed_at)"
                " VALUES (:uid, 'project', :pid, now())"
            ).bindparams(uid=user.id, pid=project.id)
        )
        await routed.commit()
