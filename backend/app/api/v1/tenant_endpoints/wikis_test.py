"""Tests for the wiki endpoints — CRUD, the page list, moves, drafts, and the
links both ways.

The wiki-specific concerns beyond the usual tool contract are the two things a
body of linked pages owns: the **spine** (a page's place in the list, and who
is shown it) and the **web** (what a page's body names, and what names it
back).
"""

from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import (
    create_document,
    create_wiki,
    create_wiki_page,
    strip_non_owner_grants,
)


async def _wikis_enabled(session: AsyncSession, initiative) -> None:
    initiative.wikis_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def test_create_wiki(client: AsyncClient, acting_user, session):
    """Creating seeds the creator's owner grant plus the default all-members
    read grant."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)

    response = await client.post(
        a.g("/wikis/"),
        headers=a.headers,
        json={
            "name": "Club handbook",
            "description": "How the bar float works, and the rest.",
            "initiative_id": a.initiative.id,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Club handbook"
    assert body["can"]["delete"] is True
    assert body["page_count"] == 0
    assert body["home_page_id"] is None
    levels = {(g.get("all_initiative_members"), g["level"]) for g in body["grants"]}
    assert (True, "read") in levels


async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.wikis_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/wikis/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "WIKIS_NOT_ENABLED"


async def test_a_member_outside_the_initiative_cannot_see_it(
    client: AsyncClient, acting_user, session
):
    """Gate 2: not being in the initiative reads as 404, not 403 — the row is
    hidden rather than refused."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    response = await client.get(a.g(f"/wikis/{wiki.id}"), headers=b.headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Pages — the spine
# ---------------------------------------------------------------------------


async def test_create_page_records_its_author_and_slug(
    client: AsyncClient, acting_user, session
):
    """The regression this file exists for: a page is written with the caller
    as its author, and its title becomes the slug that addresses it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=a.headers,
        json={"title": "The bar float"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created_by"] == a.user.id
    assert body["slug"] == "the-bar-float"


async def test_a_page_starts_as_a_draft(client: AsyncClient, acting_user, session):
    """Nobody writes a page in one keystroke, and the people who only read this
    wiki have no use for an empty one — so it is published when it is ready."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    created = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=a.headers,
        json={"title": "The bar float"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_draft"] is True

    published = await client.patch(
        a.g(f"/wikis/{wiki.id}/pages/{created.json()['id']}"),
        headers=a.headers,
        json={"is_draft": False},
    )

    assert published.status_code == 200, published.text
    assert published.json()["is_draft"] is False


async def test_a_page_starts_with_no_name(client: AsyncClient, acting_user, session):
    """A page is made before it is about anything, so nothing names it for you."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == ""
    # It still has an address, which is what a page needs to be linkable at all.
    assert body["slug"]


async def test_two_pages_with_one_title_get_distinct_slugs(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    slugs = []
    for _ in range(2):
        response = await client.post(
            a.g(f"/wikis/{wiki.id}/pages"),
            headers=a.headers,
            json={"title": "Rules"},
        )
        assert response.status_code == 201, response.text
        slugs.append(response.json()["slug"])

    assert slugs == ["rules", "rules-2"]


async def test_a_name_goes_back_into_circulation_with_the_trash(
    client: AsyncClient, acting_user, session
):
    """Write "Step 1", throw it away, write "Step 1" again.

    A page in the bin holds no address, so the second one gets the first one's
    slug rather than a suffix — and, before this was a partial index, rather
    than a unique violation nobody could see the cause of.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    first = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    assert first.status_code == 201, first.text
    assert first.json()["slug"] == "step-1"

    trashed = await client.delete(
        a.g(f"/wikis/{wiki.id}/pages/{first.json()['id']}"), headers=a.headers
    )
    assert trashed.status_code == 204, trashed.text

    second = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )

    assert second.status_code == 201, second.text
    assert second.json()["slug"] == "step-1"


async def test_a_page_can_be_renamed_onto_a_trashed_pages_name(
    client: AsyncClient, acting_user, session
):
    """The same freed name, taken by a rename rather than by a new page."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    first = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    assert first.status_code == 201, first.text
    await client.delete(
        a.g(f"/wikis/{wiki.id}/pages/{first.json()['id']}"), headers=a.headers
    )

    second = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Untitled"}
    )
    assert second.status_code == 201, second.text

    renamed = await client.patch(
        a.g(f"/wikis/{wiki.id}/pages/{second.json()['id']}"),
        headers=a.headers,
        json={"title": "Step 1"},
    )

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["slug"] == "step-1"


async def test_a_restored_page_takes_its_name_back(
    client: AsyncClient, acting_user, session
):
    """Out of the bin and back at its own address, when it is still free."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    page = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    page_id = page.json()["id"]
    await client.delete(a.g(f"/wikis/{wiki.id}/pages/{page_id}"), headers=a.headers)

    restored = await client.post(
        a.g(f"/trash/wiki_page/{page_id}/restore"), headers=a.headers
    )

    assert restored.status_code == 200, restored.text
    back = await client.get(a.g(f"/wikis/{wiki.id}/pages/{page_id}"), headers=a.headers)
    assert back.status_code == 200, back.text
    assert back.json()["slug"] == "step-1"


async def test_a_restored_page_comes_back_beside_the_one_that_took_its_name(
    client: AsyncClient, acting_user, session
):
    """The other end of the same rule: a page in the bin has no claim on a name
    somebody has used since, so it comes back under a suffixed one rather than
    not coming back at all."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    first = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    page_id = first.json()["id"]
    await client.delete(a.g(f"/wikis/{wiki.id}/pages/{page_id}"), headers=a.headers)
    replacement = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": "Step 1"}
    )
    assert replacement.json()["slug"] == "step-1"

    restored = await client.post(
        a.g(f"/trash/wiki_page/{page_id}/restore"), headers=a.headers
    )

    assert restored.status_code == 200, restored.text
    back = await client.get(a.g(f"/wikis/{wiki.id}/pages/{page_id}"), headers=a.headers)
    assert back.status_code == 200, back.text
    assert back.json()["slug"] == "step-1-2"
    # And the page that took the name in the meantime keeps it.
    held = await client.get(
        a.g(f"/wikis/{wiki.id}/pages/{replacement.json()['id']}"), headers=a.headers
    )
    assert held.json()["slug"] == "step-1"


async def test_a_wiki_restored_whole_keeps_its_pages_addresses(
    client: AsyncClient, acting_user, session
):
    """Nothing can take a name while the whole wiki is in the bin, so every
    page comes back at the address links point at."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    for title in ("Step 1", "Step 2"):
        response = await client.post(
            a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers, json={"title": title}
        )
        assert response.status_code == 201, response.text

    await client.delete(a.g(f"/wikis/{wiki.id}"), headers=a.headers)
    restored = await client.post(
        a.g(f"/trash/wiki/{wiki.id}/restore"), headers=a.headers
    )
    assert restored.status_code == 200, restored.text

    pages = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert pages.status_code == 200, pages.text
    assert [page["slug"] for page in pages.json()["items"]] == ["step-1", "step-2"]


async def test_the_tree_comes_back_in_reading_order(
    client: AsyncClient, acting_user, session
):
    """In the order somebody arranged them, so a client draws the list without
    sorting it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="Bar")
    await create_wiki_page(session, wiki, a.user, title="Float")
    await create_wiki_page(session, wiki, a.user, title="Kitchen")

    response = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)

    assert response.status_code == 200, response.text
    titles = [page["title"] for page in response.json()["items"]]
    assert titles == ["Bar", "Float", "Kitchen"]


async def test_moving_a_page_renumbers_its_new_siblings(
    client: AsyncClient, acting_user, session
):
    """A move is one fact — where in the list this page now goes — and the
    whole list is renumbered so the order it lands in is the order drawn."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="First")
    await create_wiki_page(session, wiki, a.user, title="Second")
    moved = await create_wiki_page(session, wiki, a.user, title="Third")

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages/{moved.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )
    assert response.status_code == 200, response.text

    tree = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [p["title"] for p in tree.json()["items"]] == ["Third", "First", "Second"]


async def test_a_page_from_another_wiki_reads_as_missing(
    client: AsyncClient, acting_user, session
):
    """A page is addressed through its wiki, so an id from a different one is
    not found rather than somebody else's page."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    mine = await create_wiki(session, a.initiative, a.user)
    theirs = await create_wiki(session, a.initiative, a.user)
    stray = await create_wiki_page(session, theirs, a.user, title="Elsewhere")

    response = await client.get(
        a.g(f"/wikis/{mine.id}/pages/{stray.id}"), headers=a.headers
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "WIKI_PAGE_NOT_FOUND"


async def test_deleting_a_page_takes_its_sub_pages(
    client: AsyncClient, acting_user, session
):
    """The page goes, and the ones around it stay."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    doomed = await create_wiki_page(session, wiki, a.user, title="Bar")
    await create_wiki_page(session, wiki, a.user, title="Kitchen")

    response = await client.delete(
        a.g(f"/wikis/{wiki.id}/pages/{doomed.id}"), headers=a.headers
    )
    assert response.status_code == 204, response.text

    tree = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [p["title"] for p in tree.json()["items"]] == ["Kitchen"]


# ---------------------------------------------------------------------------
# Documents put in a wiki
# ---------------------------------------------------------------------------


async def test_a_document_put_in_a_wiki_is_one_of_its_pages(
    client: AsyncClient, acting_user, session
):
    """It joins by an edge, so it reads as a page without becoming one."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(session, wiki, a.user, title="Written here")
    document = await create_document(session, a.initiative, a.user)

    response = await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    assert response.status_code == 200, response.text

    rows = {row["title"]: row["kind"] for row in response.json()["items"]}
    assert rows == {"Written here": "page", document.name: "document"}


async def test_a_page_filed_under_another_reads_after_it(
    client: AsyncClient, acting_user, session
):
    """Reading order is depth-first: a page, then what is filed under it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(session, wiki, a.user, title="Afterwards")

    filed = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=a.headers,
        json={"title": "Combat", "parent_page_id": parent.id},
    )

    assert filed.status_code == 201, filed.text
    assert filed.json()["parent_page_id"] == parent.id

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Rules",
        "Combat",
        "Afterwards",
    ]


async def test_a_drag_files_a_page_and_places_it_in_one_request(
    client: AsyncClient, acting_user, session
):
    """A drag is one gesture, so filing and ordering arrive together."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=parent.id, position=0
    )
    loose = await create_wiki_page(session, wiki, a.user, title="Travel")

    moved = await client.post(
        a.g(f"/wikis/{wiki.id}/pages/{loose.id}/move"),
        headers=a.headers,
        json={"parent_page_id": parent.id, "position": 0},
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["parent_page_id"] == parent.id

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Rules",
        "Travel",
        "Combat",
    ]


async def test_a_page_cannot_be_filed_under_its_own_descendant(
    client: AsyncClient, acting_user, session
):
    """It would take the branch out of the wiki, so it is refused by name."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    child = await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=parent.id
    )

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages/{parent.id}/move"),
        headers=a.headers,
        json={"parent_page_id": child.id, "position": 0},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "WIKI_PAGE_PARENT_DESCENDANT"


async def test_a_page_cannot_be_its_own_parent(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(session, wiki, a.user, title="Rules")

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages/{page.id}/move"),
        headers=a.headers,
        json={"parent_page_id": page.id, "position": 0},
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "WIKI_PAGE_PARENT_ITSELF"


async def test_trashing_a_page_takes_what_is_filed_under_it(
    client: AsyncClient, acting_user, session
):
    """A section is put away whole, and comes back whole."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    parent = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=parent.id
    )

    trashed = await client.delete(
        a.g(f"/wikis/{wiki.id}/pages/{parent.id}"), headers=a.headers
    )
    assert trashed.status_code == 204, trashed.text

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert listed.json()["items"] == []

    restored = await client.post(
        a.g(f"/trash/wiki_page/{parent.id}/restore"), headers=a.headers
    )
    assert restored.status_code == 200, restored.text
    back = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in back.json()["items"]] == ["Rules", "Combat"]


async def test_a_document_can_be_moved_among_the_pages(
    client: AsyncClient, acting_user, session
):
    """A borrowed document is a row of the wiki's list, so it is arranged like
    one — and the document itself is never written to say so."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(session, wiki, a.user, title="First")
    await create_wiki_page(session, wiki, a.user, title="Second")
    document = await create_document(session, a.initiative, a.user, name="Borrowed")
    await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )

    moved = await client.post(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )

    assert moved.status_code == 200, moved.text
    assert [row["title"] for row in moved.json()["items"]] == [
        "Borrowed",
        "First",
        "Second",
    ]

    # And it stays there, because the order is the wiki's own record of it.
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Borrowed",
        "First",
        "Second",
    ]


async def test_a_document_can_be_filed_under_a_page(
    client: AsyncClient, acting_user, session
):
    """Where a document sits is this wiki's record, so filing it under a page
    is the same kind of fact as its place in the list — and it comes back out
    to the top the same way."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    rules = await create_wiki_page(session, wiki, a.user, title="Rules")
    await create_wiki_page(
        session, wiki, a.user, title="Combat", parent_page_id=rules.id, position=0
    )
    await create_wiki_page(session, wiki, a.user, title="Afterwards")
    document = await create_document(session, a.initiative, a.user, name="Borrowed")
    await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )

    moved = await client.post(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}/move"),
        headers=a.headers,
        json={"parent_page_id": rules.id, "position": 1},
    )
    assert moved.status_code == 200, moved.text
    rows = moved.json()["items"]
    assert [row["title"] for row in rows] == [
        "Rules",
        "Combat",
        "Borrowed",
        "Afterwards",
    ]
    borrowed = next(row for row in rows if row["kind"] == "document")
    assert borrowed["parent_page_id"] == rules.id

    # A page dragged in beside it counts it among its neighbours.
    loose = await create_wiki_page(session, wiki, a.user, title="Travel")
    await client.post(
        a.g(f"/wikis/{wiki.id}/pages/{loose.id}/move"),
        headers=a.headers,
        json={"parent_page_id": rules.id, "position": 2},
    )
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Rules",
        "Combat",
        "Borrowed",
        "Travel",
        "Afterwards",
    ]

    unfiled = await client.post(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )
    rows = unfiled.json()["items"]
    assert rows[0]["title"] == "Borrowed" and rows[0]["parent_page_id"] is None


async def test_a_document_is_not_filed_under_a_page_of_another_wiki(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    other = await create_wiki(session, a.initiative, a.user, name="Elsewhere")
    elsewhere = await create_wiki_page(session, other, a.user, title="Not here")
    document = await create_document(session, a.initiative, a.user)
    await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}/move"),
        headers=a.headers,
        json={"parent_page_id": elsewhere.id, "position": 0},
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "WIKI_PAGE_NOT_FOUND"


async def test_a_document_under_a_trashed_page_is_drawn_at_the_top(
    client: AsyncClient, acting_user, session
):
    """The page is the wiki's to put away; the document is not. It stays in
    the wiki, at the top, and goes back under the page when it is restored."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    rules = await create_wiki_page(session, wiki, a.user, title="Rules")
    document = await create_document(session, a.initiative, a.user, name="Borrowed")
    await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    await client.post(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}/move"),
        headers=a.headers,
        json={"parent_page_id": rules.id, "position": 0},
    )

    await client.delete(a.g(f"/wikis/{wiki.id}/pages/{rules.id}"), headers=a.headers)
    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    (row,) = listed.json()["items"]
    assert row["title"] == "Borrowed" and row["parent_page_id"] is None

    await client.post(a.g(f"/trash/wiki_page/{rules.id}/restore"), headers=a.headers)
    back = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    rows = back.json()["items"]
    assert [row["title"] for row in rows] == ["Rules", "Borrowed"]
    assert rows[1]["parent_page_id"] == rules.id


async def test_a_document_row_says_what_kind_of_document_it_is(
    client: AsyncClient, acting_user, session
):
    """So the navigation can draw a spreadsheet as a spreadsheet."""
    from app.models.tenant.document import DocumentType

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(session, wiki, a.user, title="Written here")
    document = await create_document(
        session,
        a.initiative,
        a.user,
        name="Budget",
        document_type=DocumentType.spreadsheet,
    )

    response = await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    rows = {row["title"]: row for row in response.json()["items"]}
    assert rows["Budget"]["document_type"] == "spreadsheet"
    assert rows["Written here"]["document_type"] is None


async def test_a_page_can_be_moved_past_a_document(
    client: AsyncClient, acting_user, session
):
    """The other half of one list: moving a page counts the documents in it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    first = await create_wiki_page(session, wiki, a.user, title="First")
    await create_wiki_page(session, wiki, a.user, title="Second")
    document = await create_document(session, a.initiative, a.user, name="Borrowed")
    await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )

    moved = await client.post(
        a.g(f"/wikis/{wiki.id}/pages/{first.id}/move"),
        headers=a.headers,
        json={"position": 2},
    )
    assert moved.status_code == 200, moved.text

    listed = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert [row["title"] for row in listed.json()["items"]] == [
        "Second",
        "Borrowed",
        "First",
    ]


async def test_a_document_taken_out_gives_up_its_place(
    client: AsyncClient, acting_user, session
):
    """Put back in later, it arrives at the end like a new one rather than in
    the spot it held last time."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await create_wiki_page(session, wiki, a.user, title="First")
    document = await create_document(session, a.initiative, a.user, name="Borrowed")
    await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    await client.post(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}/move"),
        headers=a.headers,
        json={"position": 0},
    )

    removed = await client.delete(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    assert removed.status_code == 204, removed.text
    again = await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )

    assert [row["title"] for row in again.json()["items"]] == ["First", "Borrowed"]


async def test_a_document_in_a_wiki_is_never_a_draft(
    client: AsyncClient, acting_user, session
):
    """It is readable wherever else it lives, so this wiki cannot hold it back."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    document = await create_document(session, a.initiative, a.user)

    response = await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["items"] if r["kind"] == "document")
    assert row["is_draft"] is False


async def test_taking_a_document_out_leaves_the_document(
    client: AsyncClient, acting_user, session
):
    """The wiki loses a page. The document loses nothing."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    document = await create_document(session, a.initiative, a.user)

    await client.put(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    removed = await client.delete(
        a.g(f"/wikis/{wiki.id}/documents/{document.id}"), headers=a.headers
    )
    assert removed.status_code == 204, removed.text

    pages = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)
    assert pages.json()["items"] == []

    still_there = await client.get(a.g(f"/documents/{document.id}"), headers=a.headers)
    assert still_there.status_code == 200


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


async def test_a_draft_is_not_in_the_list_a_reader_gets(
    client: AsyncClient, acting_user, session
):
    """A page somebody is still writing belongs to the people writing it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="Finished")
    await create_wiki_page(session, wiki, a.user, title="Half written", is_draft=True)

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    response = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=b.headers)

    assert response.status_code == 200, response.text
    assert [p["title"] for p in response.json()["items"]] == ["Finished"]


async def test_a_writer_sees_their_own_drafts(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    await create_wiki_page(session, wiki, a.user, title="Finished")
    await create_wiki_page(session, wiki, a.user, title="Half written", is_draft=True)

    response = await client.get(a.g(f"/wikis/{wiki.id}/pages"), headers=a.headers)

    assert response.status_code == 200, response.text
    titles = {p["title"]: p["is_draft"] for p in response.json()["items"]}
    assert titles == {"Finished": False, "Half written": True}


async def test_a_draft_page_reads_as_missing_to_a_reader(
    client: AsyncClient, acting_user, session
):
    """Missing rather than refused: being told a page exists is being told
    something about it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(
        session, wiki, a.user, title="Half written", is_draft=True
    )

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    response = await client.get(
        a.g(f"/wikis/{wiki.id}/pages/{page.id}"), headers=b.headers
    )

    assert response.status_code == 404

    # The page's own address answers the same way: its writer reads it, and a
    # reader is told nothing.
    by_id = a.g(f"/wiki-pages/{page.id}")
    written = await client.get(by_id, headers=a.headers)
    assert written.status_code == 200, written.text
    assert written.json()["wiki_id"] == wiki.id
    assert (await client.get(by_id, headers=b.headers)).status_code == 404


# ---------------------------------------------------------------------------
# The home page
# ---------------------------------------------------------------------------


async def test_home_page_has_to_be_one_of_this_wikis_pages(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    mine = await create_wiki(session, a.initiative, a.user)
    theirs = await create_wiki(session, a.initiative, a.user)
    stray = await create_wiki_page(session, theirs, a.user, title="Elsewhere")

    response = await client.patch(
        a.g(f"/wikis/{mine.id}"),
        headers=a.headers,
        json={"home_page_id": stray.id},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "WIKI_HOME_NOT_IN_WIKI"


# ---------------------------------------------------------------------------
# The web — links both ways
# ---------------------------------------------------------------------------


async def test_a_page_reports_what_links_to_it(
    client: AsyncClient, acting_user, session
):
    """The backlink. One page's body names another, and the named page says so
    without anybody recording it twice."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    target = await create_wiki_page(session, wiki, a.user, title="The bar float")
    source = await create_wiki_page(session, wiki, a.user, title="Opening up")

    # A body that names the other page, in the shape the editor writes.
    body = {
        "root": {
            "type": "root",
            "children": [
                {
                    "type": "paragraph",
                    "children": [
                        {
                            # What both `[[ ]]` and `#` write now: the kind is
                            # part of the node, so a page can name anything.
                            "type": "entity-mention",
                            "entityType": "wiki_page",
                            "entityId": target.id,
                            "text": "The bar float",
                        }
                    ],
                }
            ],
        }
    }
    patched = await client.patch(
        a.g(f"/wikis/{wiki.id}/pages/{source.id}"),
        headers=a.headers,
        json={"content": body},
    )
    assert patched.status_code == 200, patched.text

    links = await client.get(
        a.g(f"/wikis/{wiki.id}/pages/{target.id}/links"), headers=a.headers
    )
    assert links.status_code == 200, links.text
    incoming = links.json()["incoming"]
    assert [row["entity_id"] for row in incoming] == [source.id]
    assert incoming[0]["entity_type"] == "wiki_page"
    # Enough to address the far end without a second request.
    assert incoming[0]["tool"] == "wiki"
    assert incoming[0]["tool_id"] == wiki.id


async def test_links_are_empty_for_a_page_nothing_names(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    page = await create_wiki_page(session, wiki, a.user, title="Alone")

    response = await client.get(
        a.g(f"/wikis/{wiki.id}/pages/{page.id}/links"), headers=a.headers
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"outgoing": [], "incoming": []}


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------


async def test_read_access_cannot_write_a_page(
    client: AsyncClient, acting_user, session
):
    """Gate 4: a page is the wiki's content, so adding one asks for write on
    the wiki."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        a.g(f"/wikis/{wiki.id}/pages"),
        headers=b.headers,
        json={"title": "Sneaking one in"},
    )

    assert response.status_code == 403


async def test_an_unshared_wiki_is_invisible_to_a_co_member(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await strip_non_owner_grants(session, wiki, a.user.id)

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    listing = await client.get(
        a.g("/wikis/"), headers=b.headers, params={"initiative_id": a.initiative.id}
    )
    assert listing.status_code == 200
    assert listing.json()["items"] == []
