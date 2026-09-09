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
    assert body["columns"] == ["n"]
    assert body["truncated"] is False


async def test_the_rows_come_back_positionally(client, acting_user):
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.post(
        actor.g("/query"),
        json={"sql": "SELECT 1 AS a, 2 AS b FROM projects LIMIT 1"},
        headers=actor.headers,
    )
    assert response.status_code == 200
    assert response.json()["columns"] == ["a", "b"]


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
