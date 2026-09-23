"""The deferred link pass: what resolves, what is counted, and what is not
written twice."""

import pytest

from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.models.platform.guild import GuildRole
from app.services.import_engine.links import LinkCollector
from app.services.tenant import relationships as relationships_service
from app.services.tenant.relationships import Endpoint
from app.testing.factories import create_task


@pytest.mark.unit
def test_a_ref_nothing_named_registers_nothing():
    """A task with no external ref is a task nothing can point at — not an
    error, and not a key in the map."""
    collector = LinkCollector()
    collector.register(None, SearchEntityType.task, 1)
    collector.register("", SearchEntityType.task, 2)
    collector.register("jira:ACME-1", SearchEntityType.task, None)
    collector.link("jira:ACME-1", RelationshipType.depends_on, "jira:ACME-2")
    assert collector.pending_count == 1


@pytest.mark.unit
def test_a_link_missing_an_end_is_not_a_link():
    collector = LinkCollector()
    collector.link(None, RelationshipType.depends_on, "jira:ACME-2")
    collector.link("jira:ACME-1", RelationshipType.depends_on, None)
    assert collector.pending_count == 0


@pytest.mark.integration
async def test_links_resolve_once_both_ends_exist(session, acting_user):
    """The whole point: an edge between two things written by two different
    entries becomes a row, and the order they arrived in does not matter."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    blocker = await create_task(session, a.project, title="Pour the footings")
    blocked = await create_task(session, a.project, title="Raise the frame")

    collector = LinkCollector()
    # The link is recorded BEFORE the far end is registered, which is the
    # situation the pass exists for.
    collector.link("jira:ACME-2", RelationshipType.depends_on, "jira:ACME-1")
    collector.register("jira:ACME-2", SearchEntityType.task, blocked.id)
    collector.register("jira:ACME-1", SearchEntityType.task, blocker.id)

    resolution = await collector.resolve(session, created_by=a.user.id)
    assert (resolution.created, resolution.unresolved) == (1, 0)

    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.task, id=blocked.id),
        relationship_type=RelationshipType.depends_on,
        other_kind=SearchEntityType.task,
    ) == [blocker.id]


@pytest.mark.integration
async def test_a_link_out_of_the_selection_is_counted_not_failed(session, acting_user):
    """A Jira project links to issues nobody selected all the time. That is
    a number in the report, not a failed import."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project, title="Fit the door")

    collector = LinkCollector()
    collector.register("jira:ACME-1", SearchEntityType.task, task.id)
    collector.link("jira:ACME-1", RelationshipType.related_to, "jira:OTHER-9")

    resolution = await collector.resolve(session, created_by=a.user.id)
    assert (resolution.created, resolution.unresolved) == (0, 1)


@pytest.mark.integration
async def test_a_ref_pointing_at_itself_writes_nothing(session, acting_user):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    task = await create_task(session, a.project, title="Sand the sill")

    collector = LinkCollector()
    collector.register("jira:ACME-1", SearchEntityType.task, task.id)
    collector.link("jira:ACME-1", RelationshipType.related_to, "jira:ACME-1")

    resolution = await collector.resolve(session, created_by=a.user.id)
    assert (resolution.created, resolution.unresolved) == (0, 1)


@pytest.mark.integration
async def test_an_edge_already_there_is_counted_as_a_duplicate(session, acting_user):
    """Re-asserting an edge is the answer already being correct, not a
    second row and not a failure."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    one = await create_task(session, a.project, title="Hang the gate")
    two = await create_task(session, a.project, title="Oil the hinge")

    collector = LinkCollector()
    collector.register("a", SearchEntityType.task, one.id)
    collector.register("b", SearchEntityType.task, two.id)
    collector.link("a", RelationshipType.related_to, "b")
    collector.link("a", RelationshipType.related_to, "b")

    resolution = await collector.resolve(session, created_by=a.user.id)
    assert (resolution.created, resolution.duplicate) == (1, 1)


@pytest.mark.integration
async def test_resolving_twice_does_not_write_twice(session, acting_user):
    """The collection is emptied by the pass, so a second call is a no-op
    rather than a second set of edges."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    one = await create_task(session, a.project, title="Set the post")
    two = await create_task(session, a.project, title="String the wire")

    collector = LinkCollector()
    collector.register("a", SearchEntityType.task, one.id)
    collector.register("b", SearchEntityType.task, two.id)
    collector.link("a", RelationshipType.part_of, "b")

    first = await collector.resolve(session, created_by=a.user.id)
    second = await collector.resolve(session, created_by=a.user.id)
    assert first.created == 1
    assert (second.created, second.unresolved, second.duplicate) == (0, 0, 0)


@pytest.mark.integration
async def test_two_things_claiming_one_name_keeps_the_first(session, acting_user):
    """A repeated ref is the source's ambiguity. Keeping the earlier one at
    least makes a re-run land in the same place."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    first_task = await create_task(session, a.project, title="Lay the course")
    second_task = await create_task(session, a.project, title="Point the joints")
    other = await create_task(session, a.project, title="Clean the tools")

    collector = LinkCollector()
    collector.register("dup", SearchEntityType.task, first_task.id)
    collector.register("dup", SearchEntityType.task, second_task.id)
    collector.register("other", SearchEntityType.task, other.id)
    collector.link("dup", RelationshipType.related_to, "other")

    await collector.resolve(session, created_by=a.user.id)
    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.task, id=first_task.id),
        relationship_type=RelationshipType.related_to,
        other_kind=SearchEntityType.task,
    ) == [other.id]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["Priority", "Team"], frozenset({"Priority", "Team"})),
        (None, frozenset()),
        ("Priority", frozenset()),
        (["Priority", 3, "", None], frozenset({"Priority"})),
    ],
)
def test_unticked_properties_are_read_back_defensively(raw, expected):
    """They round-tripped through a request into the job's params, so only a
    list of names counts."""
    from app.services.import_engine.context import excluded_property_names

    assert excluded_property_names(raw) == expected
