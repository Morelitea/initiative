"""What a tag assignment is now that it is an edge.

The surfaces are covered where they live (``tenant_endpoints/tags_test``); what
these hold is the storage change underneath them — direction, the gate a write
asks, and the three things a junction used to do by foreign key that something
explicit now has to do instead: drop with the tag, drop with the tagged thing,
and disappear the moment the tag is trashed.
"""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import ENDPOINT_KINDS, RelationshipType, node_id
from app.core.search import SearchEntityType
from app.models.platform.guild import GuildRole
from app.models.tenant.relationship import EntityRelationship
from app.db.session import set_rls_context
from app.services.tenant import tags as tags_service
from app.services.tenant.trash_purge import hard_purge_entity
from app.testing.factories import (
    assign_tag,
    create_document,
    create_tag,
    create_task,
)
from app.testing.schema_harness import route_session_to_guild

pytestmark = pytest.mark.integration


@pytest.mark.unit
def test_every_taggable_kind_can_sit_on_an_edge():
    """The registry is one list now: a spec names a model and the kind an edge
    addresses it by, and a kind no edge may name would be a tag surface with
    nowhere to store an assignment."""
    for name, spec in tags_service.TAG_LINKS.items():
        assert spec.kind in ENDPOINT_KINDS, name


async def _edges(session, guild_id: int, kind, entity_id: int):
    await route_session_to_guild(session, guild_id)
    return (
        await session.exec(
            select(EntityRelationship).where(
                EntityRelationship.source_node == node_id(kind, entity_id)
            )
        )
    ).all()


async def test_a_tag_is_stored_as_an_edge_the_tagged_thing_owns(
    session: AsyncSession, acting_user
):
    """Direction is the whole of the write rule: a tag is a label, so the edge
    describes the thing carrying it. Source is the task, target is the tag —
    which is what makes tagging ask write on the task and nothing of the tag."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    await assign_tag(session, task, tag, commit=True)

    rows = await _edges(session, a.guild.id, SearchEntityType.task, task.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.relationship_type == RelationshipType.tagged_with.value
    assert (row.source_type, row.source_id) == (SearchEntityType.task.value, task.id)
    assert (row.target_type, row.target_id) == (SearchEntityType.tag.value, tag.id)
    assert row.guild_id == a.guild.id


async def test_two_kinds_sharing_an_id_do_not_share_tags(
    session: AsyncSession, acting_user
):
    """Ids are unique within a table, not across them. The packed node id is
    what keeps a document's tags off a task that happens to have the same
    number — the one thing a per-entity junction got for free."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task_tag = await create_tag(session, a.guild, name="for-the-task")
    doc_tag = await create_tag(session, a.guild, name="for-the-doc")
    task = await create_task(session, a.project)
    doc = await create_document(session, a.initiative, a.user)
    await assign_tag(session, task, task_tag)
    await assign_tag(session, doc, doc_tag)
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    assert await tags_service.active_tag_ids(
        session, tags_service.TAG_LINKS["task"], task.id
    ) == [task_tag.id]
    assert await tags_service.active_tag_ids(
        session, tags_service.TAG_LINKS["document"], doc.id
    ) == [doc_tag.id]


async def test_a_trashed_tag_stops_being_an_assignment(
    session: AsyncSession, acting_user
):
    """The junction era decided this by joining ``tags`` on every read; the
    edge era has to decide it the same way, or a trashed tag would come back
    everywhere at once."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    await assign_tag(session, task, tag, commit=True)

    await route_session_to_guild(session, a.guild.id)
    tag.deleted_at = datetime.now(timezone.utc)
    session.add(tag)
    await session.commit()

    await route_session_to_guild(session, a.guild.id)
    assert (
        await tags_service.active_tag_ids(
            session, tags_service.TAG_LINKS["task"], task.id
        )
        == []
    )
    # The edge itself is still there: trashing is reversible, and a restore has
    # to bring the assignments back with it.
    assert len(await _edges(session, a.guild.id, SearchEntityType.task, task.id)) == 1


async def test_purging_a_tag_takes_its_assignments(session: AsyncSession, acting_user):
    """A junction row went with its tag by foreign key. Nothing carries an edge
    out now, so the purge path has to name it — and it does, from the endpoint
    registry rather than a second list of tables."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    tag = await create_tag(session, a.guild)
    task = await create_task(session, a.project)
    await assign_tag(session, task, tag, commit=True)
    tag.deleted_at = datetime.now(timezone.utc)
    session.add(tag)
    await session.commit()

    await set_rls_context(session, guild_id=a.guild.id, guild_role="admin")
    await hard_purge_entity(session, tag)
    await session.commit()

    assert await _edges(session, a.guild.id, SearchEntityType.task, task.id) == []


async def test_replacing_a_tag_set_leaves_no_tombstone(
    session: AsyncSession, acting_user
):
    """A replace is the UI restating a set, not a person taking one link back.
    Reading every dropped assignment as a considered negative would flood the
    signal tombstones exist to keep."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    first = await create_tag(session, a.guild, name="one")
    second = await create_tag(session, a.guild, name="two")
    task = await create_task(session, a.project)

    await route_session_to_guild(session, a.guild.id)
    spec = tags_service.TAG_LINKS["task"]
    await tags_service.replace_entity_tags(session, spec, task.id, [first.id])
    await session.commit()
    await route_session_to_guild(session, a.guild.id)
    await tags_service.replace_entity_tags(session, spec, task.id, [second.id])
    await session.commit()

    rows = await _edges(session, a.guild.id, SearchEntityType.task, task.id)
    assert [r.target_id for r in rows] == [second.id]


async def test_a_tag_assignment_is_invisible_to_a_reader_outside_the_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Every member of a guild sees every tag, so the tag end of this edge
    admits anyone. The other end is initiative content, and it is the one that
    decides — which is why a guild-level endpoint had to declare its leg rather
    than default to one."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    tag = await create_tag(session, owner.guild, name="secret-project")
    doc = await create_document(session, owner.initiative, owner.user)
    await assign_tag(session, doc, tag, commit=True)

    outsider = await acting_user(
        guild_role=GuildRole.member, guild=owner.guild, initiative=True
    )
    response = await client.get(
        outsider.g(f"/tags/{tag.id}/entities"), headers=outsider.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["documents"] == []


async def test_the_endpoint_gate_answers_in_the_schema_the_request_is_routed_to(
    session: AsyncSession, acting_user
):
    """The gate is one function in ``public`` that reads guild-local tables
    through ``search_path``, so a connection that has served one community must
    not answer the next one from what it saw first. Asked here on the same
    connection, twice, with only the routing changed: the second guild has no
    task by that id, and the answer has to be no."""
    from sqlalchemy import text

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project)
    task_id = task.id
    other = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )

    async def reachable(guild_id: int) -> bool:
        await set_rls_context(session, user_id=a.user.id, guild_id=guild_id)
        await route_session_to_guild(session, guild_id)
        return (
            await session.exec(
                text(
                    "SELECT public.relationship_endpoint_access('task', :id, false)"
                ).bindparams(id=task_id)
            )
        ).one()[0]

    assert await reachable(a.guild.id) is True
    assert await reachable(other.guild.id) is False
