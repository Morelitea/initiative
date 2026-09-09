"""What a dashboard shows that is not the reader's own.

The assertions worth having here are all about somebody who is *not* the person
asking. A published view hands one person's reach to everybody who can open a
dashboard, so what has to hold is that it hands over exactly that, only through
that dashboard, only for reads, and only while the person it came from still
has it.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.messages import DashboardMessages
from app.core.tools import Tool
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserStatus
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import create_project, create_task

pytestmark = pytest.mark.integration


COUNT_TASKS = "SELECT count(*) AS n FROM tasks"


def dashboard_body(*statements: str) -> dict:
    """A canvas of one stat per statement, w1, w2, … in order."""
    return {
        "version": 1,
        "widgets": [
            {
                "id": f"w{index + 1}",
                "type": "stat",
                "grid": {"x": 0, "y": index * 2, "w": 4, "h": 2},
                "binding": {"source": "query", "sql": sql},
            }
            for index, sql in enumerate(statements or (COUNT_TASKS,))
        ],
    }


async def dashboards_on(session, initiative) -> None:
    """The tool switch. A role permission gates creating one, and the switch
    gates the tool existing at all."""
    initiative.dashboards_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def make_dashboard(client, actor, sql: str = COUNT_TASKS) -> int:
    response = await client.post(
        actor.g("/dashboards/"),
        json={
            "name": "Status",
            "initiative_id": actor.initiative.id,
            "definition": dashboard_body(sql),
        },
        headers=actor.headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def widget_rows(client, actor, dashboard_id: int, widget_id: str = "w1"):
    response = await client.get(
        actor.g(f"/dashboards/{dashboard_id}/widgets/{widget_id}/query"),
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["rows"]


class TestWhatAReaderSees:
    """The point of the feature, and the shape of every test below: two people,
    one dashboard, and a project only one of them is shared into."""

    async def test_a_reader_sees_the_publishers_rows_through_the_dashboard(
        self, client, session, acting_user
    ):
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        # Owned by the author and shared with nobody: the reader cannot see it.
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project)
        await create_task(session, project)

        dashboard_id = await make_dashboard(client, author)
        # Before publishing, each answers from their own access.
        assert await widget_rows(client, author, dashboard_id) == [[2]]
        assert await widget_rows(client, reader, dashboard_id) == [[0]]

        published = await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert published.status_code == 200, published.text

        # After: the same numbers for both, which is what a published view is.
        assert await widget_rows(client, author, dashboard_id) == [[2]]
        assert await widget_rows(client, reader, dashboard_id) == [[2]]

    async def test_it_answers_nowhere_but_that_dashboard(
        self, client, session, acting_user
    ):
        """The grant is read *through* one dashboard. Everywhere else — the
        project's own endpoint, a query the reader writes, another dashboard —
        it says nothing."""
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project)

        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert await widget_rows(client, reader, dashboard_id) == [[1]]

        # The same statement, asked directly.
        direct = await client.post(
            reader.g("/query"),
            json={"sql": COUNT_TASKS, "initiative_id": author.initiative.id},
            headers=reader.headers,
        )
        assert direct.status_code == 200
        assert direct.json()["rows"] == [[0]]

        # And the project itself.
        seen = await client.get(
            reader.g(f"/projects/{project.id}"), headers=reader.headers
        )
        assert seen.status_code in (403, 404)

        # And a second dashboard asking the same thing.
        other = await make_dashboard(client, author)
        assert await widget_rows(client, reader, other) == [[0]]

    async def test_the_reader_cannot_ask_a_different_question_of_it(
        self, client, session, acting_user
    ):
        """What runs is the statement stored on the widget. A reader supplies
        no SQL to this path at all, so the published rows are only ever reached
        through the question somebody published."""
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project, title="Secret")

        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        # The count is published; the titles are not asked for by any widget.
        titles = await client.post(
            reader.g("/query"),
            json={
                "sql": "SELECT title FROM tasks",
                "initiative_id": author.initiative.id,
            },
            headers=reader.headers,
        )
        assert titles.status_code == 200
        assert titles.json()["rows"] == []


class TestWhatItWillNotDo:
    async def test_publishing_reaches_no_further_than_the_author(
        self, client, session, acting_user
    ):
        """Somebody who may author the canvas, over a project they cannot read.

        Authoring a dashboard is not a way to hand on access nobody gave you:
        what is published is the publisher's own reach.
        """
        owner = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, owner.initiative)
        author = await acting_user(
            guild_role=GuildRole.member,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="member",
        )
        project = await create_project(session, owner.initiative, owner.user)
        dashboard_id = await make_dashboard(client, owner)
        shared = await client.put(
            owner.g(f"/dashboards/{dashboard_id}/grants"),
            json=[{"user_id": author.user.id, "level": "write"}],
            headers=owner.headers,
        )
        assert shared.status_code in (200, 204), shared.text

        refused = await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert refused.status_code == 403
        assert refused.json()["detail"] == DashboardMessages.PUBLISH_BEYOND_YOUR_REACH

    async def test_a_published_view_has_no_reader_to_be_about(
        self, client, session, acting_user
    ):
        """One set of numbers for everybody, and ``me`` is what makes a
        statement answer differently per person. The two cannot both hold."""
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(
            client, author, "SELECT count(*) AS n FROM tasks WHERE created_by = me"
        )
        refused = await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert refused.status_code == 422
        assert refused.json()["detail"] == (
            DashboardMessages.PUBLISHED_VIEW_HAS_NO_READER
        )

    async def test_editing_takes_the_access_it_publishes(
        self, client, session, acting_user
    ):
        """The statement decides which published rows a reader sees, so
        changing one is the act of writing it."""
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        editor = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        # Shared with the editor so they may author the canvas, but they still
        # do not reach the project it publishes.
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/grants"),
            json=[{"user_id": editor.user.id, "level": "write"}],
            headers=author.headers,
        )

        refused = await client.patch(
            editor.g(f"/dashboards/{dashboard_id}"),
            json={"definition": dashboard_body("SELECT count(*) AS n FROM projects")},
            headers=editor.headers,
        )
        assert refused.status_code == 403
        assert refused.json()["detail"] == (
            DashboardMessages.EDIT_NEEDS_THE_PUBLISHED_ACCESS
        )

    async def test_the_author_may_still_edit_it(self, client, session, acting_user):
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        allowed = await client.patch(
            author.g(f"/dashboards/{dashboard_id}"),
            json={"definition": dashboard_body("SELECT count(*) AS n FROM projects")},
            headers=author.headers,
        )
        assert allowed.status_code == 200, allowed.text

    async def test_a_dashboard_grant_never_satisfies_a_write(
        self, client, session, acting_user
    ):
        """A dashboard reads and never writes. The grant is stored at read and
        the access function refuses it for a write whatever else is true."""
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        refused = await client.patch(
            reader.g(f"/projects/{project.id}"),
            json={"name": "Mine now"},
            headers=reader.headers,
        )
        assert refused.status_code in (403, 404)


class TestTheReaderCannotBeSmuggledIn:
    """``me`` is what makes a statement answer per person, so it and a
    published view cannot both hold. The refusals are where a statement is
    written; this is the same rule where one is run, so it holds however the
    statement got there."""

    async def test_a_config_override_does_not_publish_the_reader(
        self, client, session, acting_user
    ):
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project, assignees=[author.user])

        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert await widget_rows(client, reader, dashboard_id) == [[1]]

        # The definition stays clean; the override is where the reader arrives.
        overridden = await client.patch(
            author.g(f"/dashboards/{dashboard_id}"),
            json={
                "config": {
                    "widgets": {
                        "w1": {
                            "source": "query",
                            "sql": "SELECT count(*) AS n FROM tasks WHERE created_by = me",
                        }
                    }
                }
            },
            headers=author.headers,
        )
        # Either the save is refused, or the statement runs without the grant.
        # Both are the same rule; what must not happen is a published figure
        # that answers differently per person.
        if overridden.status_code == 200:
            assert await widget_rows(client, reader, dashboard_id) == [[0]]
        else:
            assert overridden.status_code == 422
            assert overridden.json()["detail"] == (
                DashboardMessages.PUBLISHED_VIEW_HAS_NO_READER
            )

    async def test_the_notice_does_not_outlive_what_it_describes(
        self, client, session, acting_user
    ):
        """If a statement names the reader, the tile under the notice is
        answering from that reader's own access — so the notice has to stop
        saying the figures are shared, whatever route the statement took."""
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        first = await client.get(
            author.g(f"/dashboards/{dashboard_id}"), headers=author.headers
        )
        assert first.json()["published_active"] is True

        # Written straight onto the row, standing in for any path that rewrites
        # a canvas without going through the checks above.
        from app.db.session import set_rls_context
        from app.models.tenant.dashboard import Dashboard

        await set_rls_context(session, guild_id=author.guild.id, guild_role="admin")
        row = await session.get(Dashboard, dashboard_id)
        assert row is not None
        row.definition = dashboard_body(
            "SELECT count(*) AS n FROM tasks WHERE created_by = me"
        )
        session.add(row)
        await session.commit()

        after = await client.get(
            author.g(f"/dashboards/{dashboard_id}"), headers=author.headers
        )
        assert after.json()["published_active"] is False
        # Still listed: its author manages it whether or not it is serving.
        assert after.json()["published_over"] != []

    async def test_one_reader_question_stops_the_whole_canvas_publishing(
        self, client, session, acting_user
    ):
        """The notice is about the dashboard, so publishing has to be too.

        Leaving ordinary widgets publishing while one names the reader would
        take the notice away — a reader would keep seeing rows beyond their own
        access with nothing on the page saying so.
        """
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project, assignees=[author.user])

        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert await widget_rows(client, reader, dashboard_id) == [[1]]

        # A second widget arrives naming the reader, by a route that skips the
        # checks — the canvas now holds one of each.
        from app.db.session import set_rls_context
        from app.models.tenant.dashboard import Dashboard

        await set_rls_context(session, guild_id=author.guild.id, guild_role="admin")
        row = await session.get(Dashboard, dashboard_id)
        assert row is not None
        row.definition = dashboard_body(
            COUNT_TASKS, "SELECT count(*) AS n FROM tasks WHERE created_by = me"
        )
        session.add(row)
        await session.commit()

        # The ordinary widget stops publishing too, so nothing is shown beyond
        # this reader's own access without the notice that says so.
        assert await widget_rows(client, reader, dashboard_id) == [[0]]
        detail = await client.get(
            reader.g(f"/dashboards/{dashboard_id}"), headers=reader.headers
        )
        assert detail.json()["published_active"] is False


class TestItFailsClosedOnTheAuthor:
    """A published view serves on somebody's standing say-so, and is re-asked
    at every fetch rather than trusted from when the row was written. An author
    who is no longer saying it publishes nothing."""

    async def test_a_suspended_author_publishes_nothing(
        self, client, session, acting_user
    ):
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project)

        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert await widget_rows(client, reader, dashboard_id) == [[1]]

        author.user.status = UserStatus.suspended
        session.add(author.user)
        await session.commit()

        # Back to the reader's own access, which is none of it.
        assert await widget_rows(client, reader, dashboard_id) == [[0]]

        # And the dashboard stops saying the figures are shared, because they
        # are not any more.
        detail = await client.get(
            reader.g(f"/dashboards/{dashboard_id}"), headers=reader.headers
        )
        assert detail.status_code == 200
        assert detail.json()["published_active"] is False
        assert detail.json()["published_over"] != []

    async def test_an_author_who_left_the_guild_publishes_nothing(
        self, client, session, acting_user
    ):
        owner = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, owner.initiative)
        author = await acting_user(
            guild_role=GuildRole.admin,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="member",
        )
        reader = await acting_user(
            guild_role=GuildRole.member,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="member",
        )
        project = await create_project(session, owner.initiative, owner.user)
        await create_task(session, project)

        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        assert await widget_rows(client, reader, dashboard_id) == [[1]]

        await session.delete(author.membership)
        await session.commit()

        assert await widget_rows(client, reader, dashboard_id) == [[0]]


class TestTheGrantItself:
    async def test_it_is_stored_as_a_read_by_the_person_publishing(
        self, client, session, acting_user
    ):
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        from app.db.session import set_rls_context

        await set_rls_context(session, guild_id=author.guild.id, guild_role="admin")
        grant = (
            await session.exec(
                select(ResourceGrant).where(ResourceGrant.dashboard_id == dashboard_id)
            )
        ).first()
        assert grant is not None
        assert grant.level == ResourceAccessLevel.read
        assert grant.created_by == author.user.id
        assert grant.resource_type == Tool.project

    async def test_the_resources_own_panel_does_not_delete_it(
        self, client, session, acting_user
    ):
        """A client that predates published views saves the sharing panel and
        must not take one away by doing so."""
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        other = await acting_user(
            guild_role=GuildRole.member,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        saved = await client.put(
            author.g(f"/projects/{project.id}/grants"),
            json=[{"user_id": other.user.id, "level": "read"}],
            headers=author.headers,
        )
        assert saved.status_code in (200, 204), saved.text

        detail = await client.get(
            author.g(f"/dashboards/{dashboard_id}"), headers=author.headers
        )
        assert detail.status_code == 200
        assert detail.json()["published_over"] == [
            {"resource_type": "project", "resource_id": project.id, "name": None}
        ]

    async def test_the_resource_owner_can_take_it_back(
        self, client, session, acting_user
    ):
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await dashboards_on(session, author.initiative)
        project = await create_project(session, author.initiative, author.user)
        dashboard_id = await make_dashboard(client, author)
        await client.put(
            author.g(f"/dashboards/{dashboard_id}/published"),
            json={
                "resources": [{"resource_type": "project", "resource_id": project.id}]
            },
            headers=author.headers,
        )
        revoked = await client.delete(
            author.g(f"/dashboards/{dashboard_id}/published/project/{project.id}"),
            headers=author.headers,
        )
        assert revoked.status_code == 204

        detail = await client.get(
            author.g(f"/dashboards/{dashboard_id}"), headers=author.headers
        )
        assert detail.json()["published_over"] == []

    async def test_it_says_which_widget_has_no_statement(self, client, acting_user):
        actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
        dashboard_id = await make_dashboard(client, actor)
        missing = await client.get(
            actor.g(f"/dashboards/{dashboard_id}/widgets/nope/query"),
            headers=actor.headers,
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == DashboardMessages.WIDGET_HAS_NO_QUERY
