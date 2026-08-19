"""Name resolution for the shared functions is a property of the route.

``public.initiative_access`` and ``public.capture_change`` name guild tables
unqualified — that is exactly what lets one definition in ``public`` serve every
``guild_<id>`` schema, rather than one copy per guild. The routed
``search_path`` is therefore what binds those names, so it names every schema
they may resolve in, in priority order, ending at ``pg_temp``
(``app.db.session._search_path``).

These run under the real ``app_user`` login with a routed context rather than
the superuser-backed ``session`` fixture, because the binding under test is a
property of the routed session.
"""

import pytest
from sqlalchemy import text

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_task,
    create_user,
)

pytestmark = pytest.mark.database


@pytest.fixture
async def workspace(session):
    """One guild, two initiatives, and a task in the first."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    first = await create_initiative(session, guild=guild, creator=owner, name="First")
    second = await create_initiative(session, guild=guild, creator=owner, name="Second")
    project = await create_project(session, initiative=first, owner=owner)
    task = await create_task(session, project=project, title="a task")
    return owner, guild, first, second, project, task


@pytest.fixture
async def routed(role_session, workspace):
    """An ``app_user`` session routed into the guild as a member.

    Rolled back on teardown: these tests create session-local tables, and the
    open transaction would hold locks against the schema cleanup that follows.
    """
    owner, guild, *_ = workspace
    s = await role_session("app_user")
    await set_rls_context(
        s, user_id=owner.id, guild_id=guild.id, guild_role=GuildRole.member.value
    )
    yield s
    await s.rollback()


class TestRoutedPath:
    async def test_it_names_the_guild_schema_public_and_pg_temp(
        self, routed, workspace
    ):
        _, guild, *_ = workspace
        path = (
            await routed.exec(text("SELECT current_setting('search_path')"))
        ).scalar()
        assert path.split(", ") == [f"guild_{guild.id}", "public", "pg_temp"]


class TestInitiativeAccessBindsTheRoutedSchema:
    async def test_membership_resolves_in_the_guild_schema(self, routed, workspace):
        """``initiative_members`` is the guild's table, whatever else the
        session holds under that name."""
        owner, guild, first, *_ = workspace
        await routed.exec(
            text(
                "CREATE TEMP TABLE initiative_members (initiative_id int, user_id int)"
            )
        )
        bound = (
            await routed.exec(
                text(
                    "SELECT n.nspname FROM pg_class c"
                    " JOIN pg_namespace n ON n.oid = c.relnamespace"
                    " WHERE c.oid = 'initiative_members'::regclass"
                )
            )
        ).scalar()
        assert bound == f"guild_{guild.id}"

        granted = (
            await routed.exec(
                text("SELECT public.initiative_access(:i, :u, false)").bindparams(
                    i=first.id, u=owner.id
                )
            )
        ).scalar()
        assert granted is True

    async def test_a_non_member_stays_a_non_member(
        self, session, role_session, workspace
    ):
        """The gate answers from the guild's own membership rows."""
        _, guild, first, *_ = workspace
        outsider = await create_user(session)
        s = await role_session("app_user")
        await set_rls_context(
            s, user_id=outsider.id, guild_id=guild.id, guild_role=GuildRole.member.value
        )
        await s.exec(
            text(
                "CREATE TEMP TABLE initiative_members (initiative_id int, user_id int)"
            )
        )
        await s.exec(
            text("INSERT INTO pg_temp.initiative_members VALUES (:i, :u)").bindparams(
                i=first.id, u=outsider.id
            )
        )
        granted = (
            await s.exec(
                text("SELECT public.initiative_access(:i, :u, false)").bindparams(
                    i=first.id, u=outsider.id
                )
            )
        ).scalar()
        assert granted is False
        assert (await s.exec(text("SELECT count(*) FROM tasks"))).scalar() == 0
        await s.rollback()


class TestCaptureChangeBindsTheRoutedSchema:
    async def test_an_event_carries_the_initiative_the_row_belongs_to(
        self, routed, workspace
    ):
        """``capture_change`` resolves a task's initiative through the guild's
        own ``projects``, so the event is scoped like the row it describes."""
        _, guild, first, second, project, task = workspace
        await routed.exec(
            text(
                f"CREATE TEMP TABLE projects AS "  # noqa: S608
                f"SELECT {project.id}::int AS id, {second.id}::int AS initiative_id"
            )
        )
        await routed.exec(
            text("UPDATE tasks SET title = 'renamed' WHERE id = :t").bindparams(
                t=task.id
            )
        )
        row = (
            await routed.exec(
                text(
                    "SELECT initiative_id, resource_type, action FROM event_outbox"
                    " ORDER BY id DESC LIMIT 1"
                )
            )
        ).first()
        assert tuple(row) == (first.id, "tasks", "updated")
