"""Tests for the wiki endpoints — CRUD, the page list, moves, drafts, and the
links both ways.

The wiki-specific concerns beyond the usual tool contract are the two things a
body of linked pages owns: the **spine** (a page's place in the list, and who
is shown it) and the **web** (what a page's body names, and what names it
back).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete as sa_delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.resource_grant import ResourceGrant
from app.testing import create_document, create_wiki, create_wiki_page


async def _wikis_enabled(session: AsyncSession, initiative) -> None:
    initiative.wikis_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _strip_non_owner_grants(session, wiki, owner_id: int) -> None:
    """Remove every grant except the owner's own — the wiki becomes invisible
    to other members."""
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == "wiki",
            ResourceGrant.resource_id == wiki.id,
            ResourceGrant.user_id.is_distinct_from(owner_id),
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
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
    assert body["my_permission_level"] == "owner"
    assert body["page_count"] == 0
    assert body["home_page_id"] is None
    levels = {(g.get("all_initiative_members"), g["level"]) for g in body["grants"]}
    assert (True, "read") in levels


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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
    assert body["is_draft"] is False


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


# ---------------------------------------------------------------------------
# The home page
# ---------------------------------------------------------------------------


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
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


@pytest.mark.integration
async def test_an_unshared_wiki_is_invisible_to_a_co_member(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _wikis_enabled(session, a.initiative)
    wiki = await create_wiki(session, a.initiative, a.user)
    await _strip_non_owner_grants(session, wiki, a.user.id)

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
