"""Searching a guild through the API.

The gates are the index's own policies, so these assert what a *request* gets
back: that a match is found across tools, that the caller's access decides the
result set, and that the two shapes a client depends on — exact totals and a
route to the thing found — hold.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from app.models.platform.guild import GuildRole
from app.testing import Actor, create_document, create_tag, create_task

pytestmark = pytest.mark.integration

ActingUser = Callable[..., Awaitable[Actor]]


async def _search(client, actor: Actor, **params) -> dict:
    response = await client.get(
        actor.g("/search/"), headers=actor.headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_it_finds_a_task(client, session, acting_user: ActingUser) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="quarterly vendor renewal")

    body = await _search(client, a, q="vendor renewal")
    assert [h["title"] for h in body["items"]] == ["quarterly vendor renewal"]
    assert body["total"] == 1


async def test_it_finds_across_tools_in_one_query(
    client, session, acting_user: ActingUser
) -> None:
    """The point of the whole thing: one query, not one per tool."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="renewal task")
    await create_document(session, a.initiative, a.user, name="renewal doc")
    await create_tag(session, a.guild, name="renewal")

    body = await _search(client, a, q="renewal")
    assert {h["entity_type"] for h in body["items"]} == {"task", "document", "tag"}


async def test_a_hit_carries_what_it_takes_to_reach_it(
    client, session, acting_user: ActingUser
) -> None:
    """A task is opened through its project, so the hit has to name it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="routable")

    hit = (await _search(client, a, q="routable"))["items"][0]
    assert hit["entity_type"] == "task"
    assert hit["entity_id"] == task.id
    assert hit["tool"] == "project"
    assert hit["tool_id"] == a.project.id
    assert hit["initiative_id"] == a.initiative.id


async def test_a_body_match_returns_a_snippet(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_document(
        session,
        a.initiative,
        a.user,
        name="Handbook",
        content={
            "root": {
                "children": [
                    {
                        "type": "paragraph",
                        "children": [
                            {"type": "text", "text": "the vendor renewal window"}
                        ],
                    }
                ]
            }
        },
    )
    hit = (await _search(client, a, q="renewal window"))["items"][0]
    assert hit["title"] == "Handbook"
    assert "renewal" in (hit["snippet"] or "")


async def test_it_returns_only_what_the_caller_may_see(
    client, session, acting_user: ActingUser
) -> None:
    """A member of the initiative holding no grant on the project."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await create_task(session, a.project, title="restricted renewal")

    assert (await _search(client, a, q="restricted"))["total"] == 1
    assert (await _search(client, b, q="restricted"))["items"] == []


async def test_the_total_counts_what_the_caller_may_see(
    client, session, acting_user: ActingUser
) -> None:
    """The count is a predicate in the same statement, so it matches the rows —
    a pager built on it does not stop early or promise a page that is empty."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    for n in range(3):
        await create_task(session, a.project, title=f"renewal {n}")

    assert (await _search(client, b, q="renewal"))["total"] == 0
    mine = await _search(client, a, q="renewal", limit=2)
    assert mine["total"] == 3
    assert len(mine["items"]) == 2


async def test_it_can_be_narrowed_by_type_and_initiative(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="narrow me")
    await create_document(session, a.initiative, a.user, name="narrow me too")

    only_tasks = await _search(client, a, q="narrow", types=["task"])
    assert {h["entity_type"] for h in only_tasks["items"]} == {"task"}

    elsewhere = await _search(
        client, a, q="narrow", initiative_id=a.initiative.id + 999
    )
    assert elsewhere["items"] == []


async def test_an_empty_query_is_not_an_error(client, acting_user: ActingUser) -> None:
    a = await acting_user(guild_role=GuildRole.admin)
    body = await _search(client, a, q="   ")
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


async def test_suggest_returns_titles_to_jump_to(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="jump target")

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"q": "jump"}
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [r["entity_id"] for r in rows] == [task.id]
    assert rows[0]["tool_id"] == a.project.id
    assert "snippet" not in rows[0]


async def test_a_non_member_cannot_search_the_guild(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    outsider = await acting_user(guild_role=GuildRole.admin)
    await create_task(session, a.project, title="private renewal")

    response = await client.get(
        a.g("/search/"), headers=outsider.headers, params={"q": "renewal"}
    )
    assert response.status_code == 403


async def test_suggest_offers_only_titles_that_match(
    client, session, acting_user: ActingUser
) -> None:
    """The palette shows titles, so a hit whose title shows nothing of what was
    typed reads as a mistake — even when the word is genuinely in the body."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_document(
        session,
        a.initiative,
        a.user,
        name="Handbook",
        content={
            "root": {
                "children": [
                    {
                        "type": "paragraph",
                        "children": [{"type": "text", "text": "vendor renewal"}],
                    }
                ]
            }
        },
    )
    await create_document(session, a.initiative, a.user, name="Renewal calendar")

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"q": "renewal"}
    )
    assert response.status_code == 200, response.text
    assert [r["title"] for r in response.json()] == ["Renewal calendar"]

    # ...while the full search still finds the body match.
    body = await _search(client, a, q="renewal")
    assert {h["title"] for h in body["items"]} == {"Handbook", "Renewal calendar"}


async def test_suggest_matches_a_partly_typed_word(
    client, session, acting_user: ActingUser
) -> None:
    """A palette answers while you are still typing."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="vendor renewal")

    response = await client.get(
        a.g("/search/suggest"), headers=a.headers, params={"q": "ven"}
    )
    assert [r["title"] for r in response.json()] == ["vendor renewal"]


async def test_paging_does_not_repeat_or_drop_a_hit(
    client, session, acting_user: ActingUser
) -> None:
    """Rank and timestamp both tie across these, so the order has to be total
    or a row shows on two pages and another on none."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    for n in range(6):
        await create_task(session, a.project, title=f"renewal item {n}")

    seen: list[int] = []
    for offset in (0, 2, 4):
        page = await _search(client, a, q="renewal", limit=2, offset=offset)
        seen.extend(h["entity_id"] for h in page["items"])
    assert len(seen) == 6
    assert len(set(seen)) == 6
