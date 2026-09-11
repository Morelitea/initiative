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
    create_initiative,
    create_tag,
    create_task,
)

pytestmark = pytest.mark.integration


def _url(a) -> str:
    return a.g("/relationships/")


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
    assert body["other"] == {
        "type": "document",
        "id": doc.id,
        "title": doc.name,
        "initiative_id": a.initiative.id,
    }

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
