"""The query endpoint: who may ask, and what they get back.

The interesting test is the last one. A query surface is only as safe as its
answer to "does this return more than the asker could already reach", and the
way to know is to ask two people with different standing the same question.
"""

import json
from pathlib import Path

import pytest

from app.core.messages import QueryMessages
from app.models.platform.guild import GuildRole
from app.services.fields.spec import FieldType
from app.services.marketplace import builtin
from app.services.tenant.dashboard_definition import WIDGET_SPECS
from app.testing import create_initiative_member, create_project, create_task

pytestmark = pytest.mark.integration


async def test_a_member_can_run_a_query(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT count(*) AS n FROM projects"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == [{"name": "n", "type": "number"}]
    assert body["truncated"] is False


async def test_the_rows_come_back_positionally(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT 1 AS a, 2 AS b FROM projects LIMIT 1"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [
        {"name": "a", "type": "number"},
        {"name": "b", "type": "number"},
    ]


async def test_a_statement_the_surface_refuses_says_which_word(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT id FROM users"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.UNKNOWN_RELATION


async def test_a_write_is_refused_before_it_reaches_the_database(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "DELETE FROM tasks"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.READ_ONLY


async def test_a_statement_the_database_cannot_finish_is_a_refusal(client, acting_user):
    """It parsed and resolved; the database had the last word on it. That is
    still something the reader can correct, so it comes back as one."""
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT count(*) / 0 AS n FROM projects"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.EXECUTION_FAILED


async def test_describing_a_statement_names_its_columns_and_types(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT name, created_at, is_archived, id FROM projects"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [
        {"name": "name", "type": "text"},
        {"name": "created_at", "type": "date"},
        {"name": "is_archived", "type": "boolean"},
        {"name": "id", "type": "number"},
    ]


async def test_a_closed_vocabulary_describes_as_one(client, acting_user):
    """``priority`` is a database enum, which is the same signal the field
    registry reads — so a query's shape and a dataset's fields say it the
    same way."""
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT priority FROM tasks"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [{"name": "priority", "type": "enum"}]


async def test_a_field_that_names_a_row_describes_as_a_reference(client, acting_user):
    """``project_id`` holds an integer and means a project. A query's shape says
    that in the same word the dataset's fields do."""
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT project_id, title FROM tasks"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == [
        {"name": "project_id", "type": "reference"},
        {"name": "title", "type": "text"},
    ]


async def test_describing_runs_nothing(client, session, acting_user):
    """A statement that would fail while running still describes, because
    describing plans and does not execute."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_project(session, actor.initiative, actor.user)
    described = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT count(*) / 0 AS n FROM projects"},
        headers=actor.headers,
    )
    ran = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT count(*) / 0 AS n FROM projects"},
        headers=actor.headers,
    )
    assert described.status_code == 200
    assert described.json()["columns"] == [{"name": "n", "type": "number"}]
    assert ran.status_code == 400


async def test_a_statement_that_does_not_resolve_does_not_describe(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/describe"),
        json={"sql": "SELECT id FROM users"},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.UNKNOWN_RELATION


async def test_a_non_member_cannot_reach_the_guilds_queries(client, acting_user):
    resident = await acting_user(guild_role=GuildRole.admin, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        resident.g("/query"),
        json={"sql": "SELECT count(*) AS n FROM projects"},
        headers=outsider.headers,
    )
    assert response.status_code == 403


async def test_a_query_returns_what_its_author_reaches_and_no_more(
    client, session, acting_user
):
    """Two members of one guild, one of them not in the initiative. The same
    statement answers differently, because the policies read who is asking."""
    author = await acting_user(guild_role=GuildRole.member, initiative=True)
    await create_project(session, author.initiative, author.user)

    stranger = await acting_user(guild_role=GuildRole.member, guild=author.guild)

    statement = {"sql": "SELECT count(*) AS n FROM projects"}
    mine = await client.post(author.g("/query"), json=statement, headers=author.headers)
    theirs = await client.post(
        stranger.g("/query"), json=statement, headers=stranger.headers
    )

    assert mine.status_code == 200
    assert theirs.status_code == 200
    assert mine.json()["rows"] == [[1]]
    assert theirs.json()["rows"] == [[0]]


async def test_a_built_query_answers_with_its_sql_and_its_shape(client, acting_user):
    """The builder describes and the server writes the SQL, so what comes back
    is both halves the builder needs: the statement to store, and the columns
    its slot pickers offer."""
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/build"),
        json={
            "dataset": "tasks",
            "columns": [
                {"field": "priority"},
                {"field": "*", "aggregate": "count", "alias": "tasks"},
            ],
            "group_by": ["priority"],
            "order_by": {"field": "tasks", "descending": True},
            "limit": 10,
        },
        headers=actor.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sql"].startswith("SELECT priority, count(*) AS tasks FROM tasks")
    assert body["columns"] == [
        {"name": "priority", "type": "enum"},
        {"name": "tasks", "type": "number"},
    ]
    assert body["relations"] == ["tasks"]


async def test_a_built_query_can_be_run_as_it_came_back(client, session, acting_user):
    """The whole point of building server-side: a statement somebody clicked
    together is one this surface will run."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_project(session, actor.initiative, actor.user)
    built = await client.post(
        actor.g("/query/build"),
        json={"dataset": "projects", "columns": [{"field": "*", "aggregate": "count"}]},
        headers=actor.headers,
    )
    assert built.status_code == 200
    ran = await client.post(
        actor.g("/query"), json={"sql": built.json()["sql"]}, headers=actor.headers
    )
    assert ran.status_code == 200
    assert ran.json()["rows"] == [[1]]


async def test_a_builder_cannot_describe_a_dataset_nobody_declared(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.member, initiative=True)
    response = await client.post(
        actor.g("/query/build"),
        json={"dataset": "pg_shadow", "columns": [{"field": "usename"}]},
        headers=actor.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == QueryMessages.UNKNOWN_RELATION


class TestReadingOneInitiative:
    """A statement names datasets, not a scope.

    Which means a reader in three initiatives asking about tasks gets all
    three, and a surface that belongs to one of them has to say so. What
    follows is that saying so works, and that saying it never widens.
    """

    async def test_a_query_answers_for_the_initiative_it_names(
        self, client, session, acting_user
    ):
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        await create_project(session, actor.initiative, actor.user)

        # A second initiative in the same guild, with the same reader in it
        # and a project of theirs in it — so what the narrowing removes is
        # something this reader can otherwise see.
        other = await acting_user(
            guild_role=GuildRole.member, guild=actor.guild, initiative=True
        )
        await create_initiative_member(session, other.initiative, actor.user)
        await create_project(session, other.initiative, actor.user)

        both = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT count(*) AS n FROM projects"},
            headers=actor.headers,
        )
        assert both.status_code == 200
        assert both.json()["rows"] == [[2]]

        one = await client.post(
            actor.g("/query"),
            json={
                "sql": "SELECT count(*) AS n FROM projects",
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert one.status_code == 200
        assert one.json()["rows"] == [[1]]

    async def test_naming_an_initiative_never_widens(
        self, client, session, acting_user
    ):
        """Naming one the reader is not in returns nothing, rather than its
        rows: the scope narrows an answer, it does not authorize one."""
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        stranger = await acting_user(
            guild_role=GuildRole.member, guild=actor.guild, initiative=True
        )
        await create_project(session, stranger.initiative, stranger.user)

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": "SELECT count(*) AS n FROM projects",
                "initiative_id": stranger.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200
        assert response.json()["rows"] == [[0]]

    async def test_the_scope_reaches_a_dataset_through_its_parent(
        self, client, session, acting_user
    ):
        """Tasks resolve their initiative through their project, so narrowing
        has to follow the same path the policies do."""
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        mine = await create_project(session, actor.initiative, actor.user)
        await create_task(session, mine)

        other = await acting_user(
            guild_role=GuildRole.member, guild=actor.guild, initiative=True
        )
        await create_initiative_member(session, other.initiative, actor.user)
        theirs = await create_project(session, other.initiative, actor.user)
        await create_task(session, theirs)

        both = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT count(*) AS n FROM tasks"},
            headers=actor.headers,
        )
        assert both.json()["rows"] == [[2]]

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": "SELECT count(*) AS n FROM tasks",
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200
        assert response.json()["rows"] == [[1]]


class TestEveryShippedDashboardDrawsItsShape:
    """The statements the built-in dashboards ship with.

    A widget declares the columns it draws; a statement returns some. Nothing
    checks that they agree at save time, because a shape is decided by what the
    database says a column holds — so it is checked here, against the real
    describe path, for every dashboard the build ships.
    """

    @staticmethod
    def _widgets():
        for path in sorted(Path(builtin.CATALOG_DIR).glob("*.json")):
            listing = json.loads(path.read_text())
            if listing.get("kind") != "dashboard":
                continue
            for widget in listing["definition"]["widgets"]:
                sql = widget.get("binding", {}).get("sql")
                if sql:
                    yield listing["public_id"], widget, sql

    async def test_each_widget_gets_the_columns_it_draws(self, client, acting_user):
        actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
        checked = 0
        for public_id, widget, sql in self._widgets():
            response = await client.post(
                actor.g("/query/describe"), json={"sql": sql}, headers=actor.headers
            )
            where = f"{public_id}/{widget['id']}"
            assert response.status_code == 200, f"{where}: {response.json()}"
            columns = [
                FieldType(column["type"]) for column in response.json()["columns"]
            ]
            shape = WIDGET_SPECS[widget["type"]].shape
            unfilled = _unfilled(columns, shape)
            assert not unfilled, f"{where} cannot fill {unfilled} from {columns}"
            checked += 1
        assert checked, "no shipped dashboard widgets were checked"


def _unfilled(columns: list[FieldType], shape) -> list[str]:
    """The required slots no column can fill — the inference the client runs,
    asked of the shipped statements before anybody installs one."""
    taken: set[int] = set()
    missing = []
    for slot in shape:
        found = next(
            (
                index
                for index, column in enumerate(columns)
                if index not in taken and column in slot.types
            ),
            None,
        )
        if found is None:
            if slot.required:
                missing.append(slot.name)
        else:
            taken.add(found)
    return missing


class TestGroupingByPerson:
    """The one thing the old sources could do that a statement could not.

    Naming a person needs the account projection, and the query surface had no
    way to reach one — so the cutover turned every "by assignee" widget into a
    grouping by project. It reaches the guild's own view of its members now,
    which is what makes this a question about *these* people.
    """

    async def test_work_can_be_counted_by_the_person_doing_it(
        self, client, session, acting_user
    ):
        actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
        project = await create_project(session, actor.initiative, actor.user)
        await create_task(session, project, assignees=[actor.user])
        await create_task(session, project, assignees=[actor.user])
        await create_task(session, project)

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": (
                    "SELECT m.display_name AS person, count(*) AS tasks "
                    "FROM tasks t JOIN task_assignees a ON a.task_id = t.id "
                    "JOIN members m ON m.id = a.user_id "
                    "GROUP BY m.display_name"
                ),
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["columns"] == [
            {"name": "person", "type": "text"},
            {"name": "tasks", "type": "number"},
        ]
        # The unassigned task is not somebody's work, so it is not a row here.
        assert body["rows"] == [[body["rows"][0][0], 2]]

    async def test_the_members_it_names_are_this_guilds(
        self, client, session, acting_user
    ):
        """A person is an account platform-wide; a member is a member of this
        guild. Listing them answers the second question."""
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        stranger = await acting_user(guild_role=GuildRole.member, initiative=True)

        response = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT id FROM members"},
            headers=actor.headers,
        )
        assert response.status_code == 200
        found = {row[0] for row in response.json()["rows"]}
        assert actor.user.id in found
        assert stranger.user.id not in found

    async def test_a_name_the_guild_does_not_render_falls_back_to_the_handle(
        self, client, session, acting_user
    ):
        """``display_name`` is what a chart groups by either way, so a guild
        that shows no real names still gets one column per person."""
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        response = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT display_name FROM members"},
            headers=actor.headers,
        )
        assert response.status_code == 200
        names = [row[0] for row in response.json()["rows"]]
        assert names and all(name for name in names)


class TestAskingAboutTheReader:
    """One saved statement, two people, two answers.

    A dashboard is placed once and read by everybody in the initiative, so a
    tile that is about *you* cannot hold anybody's id. ``me`` is what makes the
    same stored SQL answer from whoever opened it.
    """

    async def test_the_same_statement_answers_from_whoever_asks(
        self, client, session, acting_user
    ):
        author = await acting_user(guild_role=GuildRole.admin, initiative=True)
        # Both reach every row here, so the only thing that can separate the
        # two answers is who is asking.
        reader = await acting_user(
            guild_role=GuildRole.admin,
            guild=author.guild,
            initiative=author.initiative,
            initiative_role="member",
        )
        project = await create_project(session, author.initiative, author.user)
        await create_task(session, project, assignees=[author.user])
        await create_task(session, project, assignees=[author.user])
        await create_task(session, project, assignees=[reader.user])

        sql = (
            "SELECT count(*) AS mine FROM tasks "
            "JOIN task_assignees a ON a.task_id = tasks.id "
            "WHERE a.user_id = me"
        )
        answers = {}
        for actor in (author, reader):
            response = await client.post(
                actor.g("/query"),
                json={"sql": sql, "initiative_id": author.initiative.id},
                headers=actor.headers,
            )
            assert response.status_code == 200, response.json()
            answers[actor.user.id] = response.json()["rows"][0][0]

        assert answers == {author.user.id: 2, reader.user.id: 1}

    async def test_it_reaches_the_person_through_a_relation(
        self, client, session, acting_user
    ):
        actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
        project = await create_project(session, actor.initiative, actor.user)
        await create_task(session, project, assignees=[actor.user])
        await create_task(session, project)

        response = await client.post(
            actor.g("/query"),
            json={
                "sql": ("SELECT count(*) AS mine FROM tasks WHERE assignee.id = me"),
                "initiative_id": actor.initiative.id,
            },
            headers=actor.headers,
        )
        assert response.status_code == 200, response.json()
        assert response.json()["rows"] == [[1]]

    async def test_a_name_the_surface_keeps_is_refused_where_it_is_written(
        self, client, acting_user
    ):
        actor = await acting_user(guild_role=GuildRole.member, initiative=True)
        response = await client.post(
            actor.g("/query"),
            json={"sql": "SELECT count(*) AS me FROM projects"},
            headers=actor.headers,
        )
        assert response.status_code == 400
        assert response.json()["detail"] == QueryMessages.RESERVED_NAME
