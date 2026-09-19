"""The one surface for links, in place of the five per-tool attach routes.

What it owes: the same gate the tables apply, the same refusal when a picker
reaches across initiatives, and an answer rendered from the side that asked —
so a caller never has to know that a symmetric edge is stored in node-id order.
"""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from app.core.messages import RelationshipMessages
from app.models.platform.guild import GuildRole
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing.schema_harness import route_session_to_guild
from app.testing import (
    create_calendar_event,
    create_document,
    create_guild_calendar,
    create_gallery,
    create_gallery_image,
    create_initiative,
    create_project,
    create_tag,
    create_task,
)

pytestmark = pytest.mark.integration


def _url(a) -> str:
    return a.g("/relationships/")


async def _galleries_enabled(session, initiative) -> None:
    """A gallery only exists in an initiative that has galleries turned on."""
    initiative.galleries_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


def _wikilink_body(document_id: int) -> dict:
    """A document body holding one ``[[ ]]`` link."""
    return {
        "root": {
            "children": [
                {
                    "type": "paragraph",
                    "children": [{"type": "wikilink", "documentId": document_id}],
                }
            ]
        }
    }


async def test_a_link_is_made_and_read_back_from_either_side(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)

    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": doc.id},
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["other"]["type"] == "document"
    assert body["other"]["id"] == doc.id
    assert body["other"]["title"] == doc.name
    assert body["other"]["initiative_id"] == a.initiative.id

    # The same edge, asked for from the document. ``attached`` is symmetric and
    # stored once in node-id order, which the caller never has to know.
    from_doc = await client.get(
        _url(a), headers=a.headers, params={"entity": f"document:{doc.id}"}
    )
    assert from_doc.status_code == 200, from_doc.text
    (edge,) = from_doc.json()
    assert edge["other"]["type"] == "project"
    assert edge["other"]["id"] == a.project.id


async def test_the_same_pair_is_refused_twice(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)
    payload = {
        "source": {"type": "project", "id": a.project.id},
        "relationship_type": "attached",
        "target": {"type": "document", "id": doc.id},
    }
    assert (
        await client.post(_url(a), headers=a.headers, json=payload)
    ).status_code == 201
    again = await client.post(_url(a), headers=a.headers, json=payload)
    assert again.status_code == 409
    assert again.json()["detail"] == RelationshipMessages.EXISTS


async def test_a_thing_cannot_be_linked_to_itself(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "related_to",
            "target": {"type": "project", "id": a.project.id},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == RelationshipMessages.SELF


async def test_a_picker_does_not_reach_across_initiatives(
    client: AsyncClient, acting_user, session
):
    """The table permits a cross-initiative edge — that is where the graph gets
    its reach — but choosing one in a picker is not how they should arrive."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    elsewhere = await create_initiative(session, a.guild, a.user)
    doc = await create_document(session, elsewhere, a.user)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": doc.id},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.CROSS_INITIATIVE


async def test_an_end_the_caller_cannot_open_is_absent(
    client: AsyncClient, acting_user, session
):
    """Not forbidden — absent, which is what every other read here does with
    something out of reach."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    hidden = await create_initiative(session, owner.guild, owner.user)
    doc = await create_document(session, hidden, owner.user)

    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    response = await client.post(
        _url(reader),
        headers=reader.headers,
        json={
            "source": {"type": "project", "id": owner.project.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": doc.id},
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == RelationshipMessages.ENDPOINT_NOT_FOUND


async def test_a_slice_is_replaced_wholesale(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    first = await create_document(session, a.initiative, a.user, name="First")
    second = await create_document(session, a.initiative, a.user, name="Second")

    params = {
        "entity": f"project:{a.project.id}",
        "relationship_type": "attached",
        "other_type": "document",
    }
    set_one = await client.put(
        _url(a), headers=a.headers, params=params, json=[first.id]
    )
    assert set_one.status_code == 200, set_one.text
    assert [e["other"]["id"] for e in set_one.json()] == [first.id]

    set_other = await client.put(
        _url(a), headers=a.headers, params=params, json=[second.id]
    )
    assert set_other.status_code == 200, set_other.text
    assert [e["other"]["id"] for e in set_other.json()] == [second.id]


async def test_a_link_you_made_is_yours_to_remove(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)
    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": doc.id},
        },
    )
    edge_id = created.json()["id"]

    removed = await client.delete(a.g(f"/relationships/{edge_id}"), headers=a.headers)
    assert removed.status_code == 204, removed.text

    listing = await client.get(
        _url(a), headers=a.headers, params={"entity": f"project:{a.project.id}"}
    )
    assert listing.json() == []


async def test_a_task_link_is_addressed_by_the_same_surface(
    client: AsyncClient, acting_user, session
):
    """The point of one router: a queue item's tasks and a project's documents
    are the same request with different kinds in it."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project)
    doc = await create_document(session, a.initiative, a.user)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "task", "id": task.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": doc.id},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["other"]["type"] == "document"


async def test_a_kind_no_edge_may_name_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    response = await client.get(
        _url(a), headers=a.headers, params={"entity": "comment:1"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == RelationshipMessages.BAD_ENDPOINT


async def test_a_guild_calendars_event_holds_no_initiative_content(
    client: AsyncClient, acting_user, session
):
    """An event takes its initiative from its calendar, and a guild calendar
    has none — so its events are guild-level content and a document is not
    theirs to link. The per-tool endpoint called this
    ``GUILD_CALENDAR_NO_DOCUMENTS``; it was never about documents."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    document = await create_document(session, a.initiative, a.user)
    calendar = await create_guild_calendar(session, a.guild, a.user)
    event = await create_calendar_event(session, calendar, a.user)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "calendar_event", "id": event.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": document.id},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.CROSS_INITIATIVE


async def test_the_guilds_vocabulary_pairs_with_anything(
    client: AsyncClient, acting_user, session
):
    """A tag belongs to no initiative by its nature rather than by where it
    sits, so it is not the same case as the event above."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "task", "id": task.id},
            "relationship_type": "tagged_with",
            "target": {"type": "tag", "id": tag.id},
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["other"]["type"] == "tag"


async def test_a_replace_cannot_drop_a_link_a_delete_would_refuse(
    client: AsyncClient, acting_user, session
):
    """A replace is a bulk removal, so it answers the same question a DELETE
    does. ``attached`` is symmetric, which means anyone who can read both ends
    may write the row — the right rule for making one and the wrong rule for
    undoing somebody else's."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    doc = await create_document(session, owner.initiative, owner.user)
    made = await client.post(
        _url(owner),
        headers=owner.headers,
        json={
            "source": {"type": "project", "id": owner.project.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": doc.id},
        },
    )
    assert made.status_code == 201, made.text

    # A co-member who can read both ends but edit neither.
    await route_session_to_guild(session, owner.guild.id)
    for resource_type, resource_id in (
        ("project", owner.project.id),
        ("document", doc.id),
    ):
        session.add(
            ResourceGrant(
                resource_type=resource_type,
                resource_id=resource_id,
                all_initiative_members=True,
                level=ResourceAccessLevel.read,
                guild_id=owner.guild.id,
                initiative_id=owner.initiative.id,
            )
        )
    await session.commit()

    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    wipe = await client.put(
        _url(reader),
        headers=reader.headers,
        params={
            "entity": f"project:{owner.project.id}",
            "relationship_type": "attached",
            "other_type": "document",
        },
        json=[],
    )
    assert wipe.status_code == 403, wipe.text
    assert wipe.json()["detail"] == RelationshipMessages.REMOVE_DENIED

    # And it is still there.
    still = await client.get(
        _url(owner),
        headers=owner.headers,
        params={"entity": f"project:{owner.project.id}"},
    )
    assert [e["other"]["id"] for e in still.json()] == [doc.id]


async def test_a_kind_no_edge_may_name_is_refused_as_a_filter(
    client: AsyncClient, acting_user, session
):
    """``other_type`` takes any search kind, and the ones no edge can name have
    to be refused here rather than at the node encoder."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    response = await client.put(
        _url(a),
        headers=a.headers,
        params={
            "entity": f"project:{a.project.id}",
            "relationship_type": "attached",
            "other_type": "comment",
        },
        json=[],
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.BAD_ENDPOINT


async def test_an_archived_project_takes_no_new_links(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)
    await route_session_to_guild(session, a.guild.id)
    a.project.archived_at = datetime.now(timezone.utc)
    session.add(a.project)
    await session.commit()

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "document", "id": doc.id},
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"] == RelationshipMessages.ENDPOINT_ARCHIVED


async def test_a_link_read_out_of_a_body_is_not_one_to_assert_by_hand(
    client: AsyncClient, acting_user, session
):
    """Writing the sentence is how you make one."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)

    refused = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "document", "id": doc.id},
            "relationship_type": "references",
            "target": {"type": "document", "id": other.id},
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == RelationshipMessages.DERIVED


async def test_a_slice_of_derived_links_is_not_one_to_restate(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)

    refused = await client.put(
        _url(a),
        headers=a.headers,
        params={
            "entity": f"document:{doc.id}",
            "relationship_type": "references",
            "other_type": "document",
        },
        json=[],
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == RelationshipMessages.DERIVED


async def test_a_link_read_out_of_a_body_is_not_one_to_unlink_by_hand(
    client: AsyncClient, acting_user, session
):
    """Editing the body is how it goes away, so the button does not offer to."""
    from app.core.search import SearchEntityType
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)

    await route_session_to_guild(session, a.guild.id)
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.document, doc.id),
        body=_wikilink_body(other.id),
        author_id=a.user.id,
    )
    await session.commit()

    listed = await client.get(
        _url(a),
        headers=a.headers,
        params={"entity": f"document:{doc.id}", "relationship_type": "references"},
    )
    assert listed.status_code == 200, listed.text
    (edge,) = listed.json()
    assert edge["provenance"] == "content"

    refused = await client.delete(
        a.g(f"/relationships/{edge['id']}"), headers=a.headers
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["detail"] == RelationshipMessages.DERIVED


async def test_inbound_asks_what_links_here(client: AsyncClient, acting_user, session):
    """The two sides of a reference are different questions, and the backlinks
    panel asks only one of them."""
    from app.core.search import SearchEntityType
    from app.services.tenant import content_references
    from app.services.tenant.relationships import Endpoint

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)
    other = await create_document(session, a.initiative, a.user)

    await route_session_to_guild(session, a.guild.id)
    await content_references.sync_for_entity(
        session,
        Endpoint(SearchEntityType.document, doc.id),
        body=_wikilink_body(other.id),
        author_id=a.user.id,
    )
    await session.commit()

    def ask(entity: int, direction: str):
        return client.get(
            _url(a),
            headers=a.headers,
            params={
                "entity": f"document:{entity}",
                "relationship_type": "references",
                "direction": direction,
            },
        )

    into = await ask(other.id, "inbound")
    assert [row["other"]["id"] for row in into.json()] == [doc.id]
    assert into.json()[0]["other"]["updated_at"] is not None, (
        "a list ordered by recency needs the far end's own moment"
    )

    out_of = await ask(other.id, "outbound")
    assert out_of.json() == [], "the target names nothing; it is named"


# ---------------------------------------------------------------------------
# What a far end says about itself
#
# A list of edges is a list of mixed kinds. Each end has to carry enough to be
# drawn and linked to, or a reader would have to fetch every one of them to find
# out what it is called, what it looks like and where it lives.
# ---------------------------------------------------------------------------


async def _attach(client: AsyncClient, a, target_type: str, target_id: int) -> dict:
    """Attach one thing to the acting user's project, and return the edge."""
    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": target_type, "id": target_id},
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["other"]


async def test_a_far_end_inside_a_tool_carries_the_address_of_that_tool(
    client: AsyncClient, acting_user, session
):
    """A task has no id-addressable page of its own: it lives at its project.

    So the pair naming the project comes back with it, the same pair a search hit
    carries. Without it a caller holds `task:12` and cannot build a link at all.
    """
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    other_project = await create_project(session, a.initiative, a.user)
    task = await create_task(session, other_project)

    end = await _attach(client, a, "task", task.id)

    assert end["tool"] == "project"
    assert end["tool_id"] == other_project.id


async def test_a_far_end_that_is_a_tool_names_itself(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc = await create_document(session, a.initiative, a.user)

    end = await _attach(client, a, "document", doc.id)

    assert end["tool"] == "document"
    assert end["tool_id"] == doc.id


async def test_the_guilds_vocabulary_is_addressed_by_nothing_else(
    client: AsyncClient, acting_user, session
):
    """A tag is not inside a tool — it is the guild's own vocabulary — so it
    reports no governing tool rather than being fitted to one."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    tag = await create_tag(session, a.guild)

    end = await _attach(client, a, "tag", tag.id)

    assert end["tool"] is None
    assert end["tool_id"] is None


async def test_a_document_brings_its_featured_image(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc = await create_document(
        session, a.initiative, a.user, featured_image_url="/uploads/3/cover.png"
    )

    end = await _attach(client, a, "document", doc.id)

    assert end["image_urls"] == ["/uploads/3/cover.png"]
    assert end["icon"] is None
    assert end["color"] is None


async def test_a_picture_brings_its_thumbnail_and_falls_back_to_itself(
    client: AsyncClient, acting_user, session
):
    """A thumbnail is absent whenever the source was already small enough not to
    need one, so the full picture is the fallback — decided here rather than by
    every surface that draws one."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    small = await create_gallery_image(session, gallery, a.user)
    large = await create_gallery_image(
        session, gallery, a.user, thumbnail_url="/uploads/3/thumb.webp"
    )

    assert (await _attach(client, a, "gallery_image", small.id))["image_urls"] == [
        small.file_url
    ]
    assert (await _attach(client, a, "gallery_image", large.id))["image_urls"] == [
        "/uploads/3/thumb.webp"
    ]


async def test_a_gallery_brings_the_cover_somebody_chose(
    client: AsyncClient, acting_user, session
):
    """A gallery's picture lives on another row, so it is one hop away."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    cover = await create_gallery_image(
        session, gallery, a.user, thumbnail_url="/uploads/3/cover-thumb.webp"
    )
    gallery.cover_image_id = cover.id
    session.add(gallery)
    await session.commit()

    end = await _attach(client, a, "gallery", gallery.id)

    # The chosen one stands alone, even though the gallery holds others.
    assert end["image_urls"] == ["/uploads/3/cover-thumb.webp"]


async def test_a_kind_that_carries_a_colour_reports_it(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    tag = await create_tag(session, a.guild, color="#112233")

    end = await _attach(client, a, "tag", tag.id)

    assert end["color"] == "#112233"
    assert end["image_urls"] == []
    assert end["icon"] is None


async def test_a_project_reports_its_emoji(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    other_project = await create_project(session, a.initiative, a.user, icon="🎲")

    end = await _attach(client, a, "project", other_project.id)

    assert end["icon"] == "🎲"
    assert end["image_urls"] == []


async def test_a_kind_with_no_look_of_its_own_says_so(
    client: AsyncClient, acting_user, session
):
    """A task has no picture, emoji or colour. Reporting three nulls is the
    honest answer, and lets the reader draw the kind's own icon instead."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project)

    end = await _attach(client, a, "task", task.id)

    assert end["image_urls"] == []
    assert end["icon"] is None
    assert end["color"] is None


async def test_a_document_says_what_sort_of_document_it_is(
    client: AsyncClient, acting_user, session
):
    """A spreadsheet, a whiteboard and a PDF are all documents and none of them
    should be drawn as a scroll, so the far end carries what picks the icon."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    sheet = await create_document(
        session, a.initiative, a.user, document_type="spreadsheet"
    )

    end = await _attach(client, a, "document", sheet.id)

    assert end["document_type"] == "spreadsheet"


async def test_a_kind_with_one_fixed_icon_says_nothing_about_its_sort(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project)

    end = await _attach(client, a, "task", task.id)

    assert end["document_type"] is None
    assert end["mime_type"] is None
    assert end["original_filename"] is None
    assert end["smart_link_url"] is None


async def test_a_gallery_nobody_chose_a_cover_for_shows_its_newest(
    client: AsyncClient, acting_user, session
):
    """A gallery with no chosen cover is the usual kind, and it is not blank —
    it stands for itself with the newest few pictures, which is what it shows
    everywhere else."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)
    for n in range(5):
        await create_gallery_image(
            session, gallery, a.user, thumbnail_url=f"/uploads/3/pic-{n}.webp"
        )

    end = await _attach(client, a, "gallery", gallery.id)

    assert len(end["image_urls"]) == 4, end["image_urls"]
    # Newest first, so the four it shows are the four most recently added.
    assert end["image_urls"][0] == "/uploads/3/pic-4.webp"


async def test_an_empty_gallery_shows_no_pictures_rather_than_a_blank_one(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _galleries_enabled(session, a.initiative)
    gallery = await create_gallery(session, a.initiative, a.user)

    end = await _attach(client, a, "gallery", gallery.id)

    assert end["image_urls"] == []


async def test_asserting_a_link_from_something_you_may_read_but_not_edit(
    client: AsyncClient, acting_user, session
):
    """ "This blocks that" is stored as *that* depending on this, so the far end
    is the source — and a directional edge asks write on its source.

    So a reader who may open the far end but not change it cannot assert one, and
    has to be told so rather than the refusal arriving as a server error.
    """
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    mine = await create_task(session, a.project)
    theirs = await create_project(session, a.initiative, b.user)
    # Readable by everyone in the initiative, writable only by its owner.
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=theirs.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            guild_id=theirs.guild_id,
            initiative_id=theirs.initiative_id,
        )
    )
    await session.commit()

    readable = await client.get(a.g(f"/projects/{theirs.id}"), headers=a.headers)
    assert readable.status_code == 200, "the case needs a readable far end"

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": theirs.id},
            "relationship_type": "depends_on",
            "target": {"type": "task", "id": mine.id},
        },
    )
    # Refused by name, so the client can say which end the problem is at —
    # rather than as a bare privilege error with nothing to show for it.
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == RelationshipMessages.SOURCE_NOT_WRITABLE


async def test_a_symmetric_link_asks_only_that_both_ends_be_readable(
    client: AsyncClient, acting_user, session
):
    """`attached` describes the pair rather than either end, so it modifies
    neither — and being able to open both is the whole of what it asks."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    theirs = await create_document(session, a.initiative, b.user)
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=theirs.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.read,
            guild_id=theirs.guild_id,
            initiative_id=theirs.initiative_id,
        )
    )
    await session.commit()

    response = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "document", "id": theirs.id},
            "relationship_type": "attached",
            "target": {"type": "project", "id": a.project.id},
        },
    )
    assert response.status_code == 201, response.text


async def test_a_far_end_says_what_it_lives_in(
    client: AsyncClient, acting_user, session
):
    """A card reading "Do a thing" says nothing when six of them are linked.
    The far end carries its project so the card can say which one."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project, title="Do a thing")

    created = await client.post(
        _url(a),
        headers=a.headers,
        json={
            "source": {"type": "project", "id": a.project.id},
            "relationship_type": "attached",
            "target": {"type": "task", "id": task.id},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["other"]["tool_title"] == a.project.name

    # Read from the task's side, the far end is the project itself — which
    # lives in no tool, so there is nothing to name.
    from_task = await client.get(
        _url(a), headers=a.headers, params={"entity": f"task:{task.id}"}
    )
    (edge,) = from_task.json()
    assert edge["other"]["tool_title"] is None
