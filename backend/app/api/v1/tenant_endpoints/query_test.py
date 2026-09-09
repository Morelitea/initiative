"""The query endpoint: who may ask, and what they get back.

The interesting test is the last one. A query surface is only as safe as its
answer to "does this return more than the asker could already reach", and the
way to know is to ask two people with different standing the same question.
"""

import pytest

from app.core.messages import QueryMessages
from app.models.platform.guild import GuildRole
from app.testing import create_project

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
