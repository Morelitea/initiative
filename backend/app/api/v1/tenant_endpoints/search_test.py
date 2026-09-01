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
from app.testing import Actor, create_comment, create_document, create_tag, create_task

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
    assert body == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
        "fuzzy": False,
    }


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


async def test_comments_are_reached_by_asking_for_them(
    client, session, acting_user: ActingUser
) -> None:
    """Comments are out of the default scope — the busiest table in a guild is
    not something every bare query should pay for — so a caller names the type,
    which is what the results page's own tab does."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project, title="stage build")
    await create_comment(
        session, a.user, task=task, content="the vendor confirmed the platform"
    )

    unasked = await client.get(
        a.g("/search/"), headers=a.headers, params={"q": "vendor confirmed"}
    )
    assert unasked.status_code == 200, unasked.text
    assert unasked.json()["items"] == []

    asked = await client.get(
        a.g("/search/"),
        headers=a.headers,
        params={"q": "vendor confirmed", "types": ["comment"]},
    )
    assert asked.status_code == 200, asked.text
    items = asked.json()["items"]
    assert [i["entity_type"] for i in items] == ["comment"]
    # It names the project, because that is where a comment on a task is read.
    assert items[0]["tool"] == "project"
    assert items[0]["tool_id"] == a.project.id


async def test_suggest_narrows_to_the_types_it_is_given(
    client, session, acting_user: ActingUser
) -> None:
    """The palette's tabs and the results page ask the same question, so the
    palette can be on one slice while the guild holds matches in another."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="riverside")
    tag = await create_tag(session, a.guild, name="riverside")

    tags_only = await client.get(
        a.g("/search/suggest"),
        headers=a.headers,
        params={"q": "riverside", "types": ["tag"]},
    )
    assert tags_only.status_code == 200, tags_only.text
    assert [r["entity_id"] for r in tags_only.json()] == [tag.id]


async def test_an_unknown_type_is_refused_rather_than_ignored(
    client, session, acting_user: ActingUser
) -> None:
    """The accepted set is declared, so a name that is not one of them is a bad
    request — not a search that quietly returns everything."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"q": "x", "types": ["invoice"]}
    )
    assert response.status_code == 422, response.text


async def test_the_last_word_matches_as_a_prefix(
    client, session, acting_user: ActingUser
) -> None:
    """A results page searches as its reader types, so the word being typed is
    usually half-finished. Whole-word matching alone reads as nothing found."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    for query in ("thro", "barricade thro"):
        response = await client.get(
            a.g("/search/"), headers=a.headers, params={"q": query}
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 1, f"{query} found nothing"


async def test_what_the_reader_asked_for_exactly_is_left_exact(
    client, session, acting_user: ActingUser
) -> None:
    """A quoted phrase and an exclusion are deliberate, so neither is widened
    into a prefix.

    Asked without the close-match fallback, so what is measured is the parsing
    and not the suggestion that would otherwise answer for it.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    for query in ('"barricade thro"', "barricade -throne"):
        response = await client.get(
            a.g("/search/"),
            headers=a.headers,
            params={"q": query, "close_matches": "false"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0, f"{query} was widened"


async def test_a_typo_is_offered_the_closest_titles(
    client, session, acting_user: ActingUser
) -> None:
    """Whole-word matching cannot answer a misspelling, so a search that finds
    nothing offers what is closest — flagged, so the reader is told which of
    the two they are reading."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"q": "thrne"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fuzzy"] is True
    assert body["items"][0]["title"] == "Barricade the Throne"


async def test_a_search_that_works_is_never_flagged_as_close(
    client, session, acting_user: ActingUser
) -> None:
    """The suggestion never blends into a search that worked."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"q": "throne"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["fuzzy"] is False


async def test_a_caller_that_only_asks_whether_anything_is_here_pays_less(
    client, session, acting_user: ActingUser
) -> None:
    """The tab strip asks each slice whether it holds anything. Offering it a
    suggestion would make it read as holding something, and would run the
    close-match scan once per tab."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    response = await client.get(
        a.g("/search/"),
        headers=a.headers,
        params={"q": "thrne", "close_matches": "false"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["fuzzy"] is False


async def test_nothing_close_stays_nothing(
    client, session, acting_user: ActingUser
) -> None:
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await create_task(session, a.project, title="Barricade the Throne")

    response = await client.get(
        a.g("/search/"), headers=a.headers, params={"q": "zzzzqqq"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["fuzzy"] is False


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
