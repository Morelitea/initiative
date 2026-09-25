"""
Integration tests for the project endpoints: listing, creating (blank and from
a template), duplicating, updating, deleting, favorites, the assignable
roster, and what a grant change does to a project's task assignees.

Sharing and archiving are proved for every tool in ``tool_grants_test`` and
``archive_test``.
"""

import json
from dataclasses import replace
from datetime import date, datetime, timezone

from httpx import AsyncClient
from sqlalchemy import text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.core.relationships import RelationshipType
from app.core.search import SearchEntityType
from app.core.tools import Tool
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.task import TaskStatusCategory
from app.testing import route_session_to_guild
from app.testing.factories import (
    create_document,
    create_guild,
    create_relationship,
    create_guild_membership,
    create_initiative,
    create_project,
    create_resource_grant,
    create_task,
    create_task_status,
)


async def test_list_projects_as_admin_shows_all(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can see all projects."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_project(session, admin.initiative, admin.user, name="Test Project")
    await create_project(session, admin.initiative, admin.user, name="Project 2")

    response = await client.get(admin.g("/projects/"), headers=admin.headers)

    assert response.status_code == 200
    body = response.json()
    data = body["items"]
    assert len(data) >= 2
    assert body["page"] == 1
    assert body["page_size"] == 0
    assert body["has_next"] is False
    assert body["total_count"] >= 2


async def test_list_projects_member_sees_initiative_projects(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that initiative members see projects in their initiative."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    project = await create_project(session, admin.initiative, admin.user)
    # Pure DAC: the member reads it only once it is shared with them.
    await create_resource_grant(session, project, user=member.user)

    response = await client.get(member.g("/projects/"), headers=member.headers)

    assert response.status_code == 200
    data = response.json()["items"]
    project_ids = {p["id"] for p in data}
    assert project.id in project_ids


async def test_search_project_members_returns_write_access_set(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The assignable roster is the project's write/owner DAC set: the owner
    and write-granted members, but not read-only members nor members with no
    grant. Returns the slim UserSummary envelope."""
    # Every handle here is stated, the owner's included. The searches below
    # assert an exact result set, and an account that seeds no handle gets
    # ``{adjective}-{noun}`` — one of whose nouns is ``quill``, which the term
    # this test filters on is a fragment of.
    admin = await acting_user(
        guild_role=GuildRole.admin, initiative=True, username="sparrow"
    )
    project = await create_project(
        session, admin.initiative, admin.user, name="Assignable Project"
    )

    writer = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
        username="quill",
        full_name="Wanda Writer",
    )
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
        username="lantern",
        full_name="Rob Reader",
    )
    # A member of the initiative with no grant at all.
    await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
        username="thistle",
        full_name="Nora None",
    )

    await create_resource_grant(
        session, project, user=writer.user, level=ResourceAccessLevel.write
    )
    await create_resource_grant(session, project, user=reader.user)

    response = await client.get(
        admin.g(f"/projects/{project.id}/members/search"), headers=admin.headers
    )

    assert response.status_code == 200
    body = response.json()
    handles = {item["username"] for item in body["items"]}
    # Owner (admin) + write-granted member are assignable.
    assert admin.user.username in handles
    assert "quill" in handles
    # Read-only and no-grant members are not.
    assert "lantern" not in handles
    assert "thistle" not in handles
    # Slim projection shape.
    assert set(body["items"][0].keys()) == {
        "id",
        "username",
        "discriminator",
        "full_name",
        "avatar_url",
        "status",
        "profile_decorations",
        "guild_role",
    }
    # Asserted as a value, not only as a key: the schema leaves it unset, so a
    # key-set check passes just as happily on an endpoint that never fills it
    # in.
    by_username = {item["username"]: item for item in body["items"]}
    assert by_username[admin.user.username]["guild_role"] == "admin"
    assert by_username["quill"]["guild_role"] == "member"

    # The filter matches what the guild renders — the handle always.
    response = await client.get(
        admin.g(f"/projects/{project.id}/members/search"),
        headers=admin.headers,
        params={"search": "quil"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["username"] for item in body["items"]] == ["quill"]

    # And her name too, because this guild takes the default and shows names.
    response = await client.get(
        admin.g(f"/projects/{project.id}/members/search"),
        headers=admin.headers,
        params={"search": "Wanda"},
    )
    assert [item["username"] for item in response.json()["items"]] == ["quill"]

    # Id filter (a picker resolving stored ids into handles) narrows the same
    # assignable set — the read-only member is not resolvable through it.
    response = await client.get(
        admin.g(f"/projects/{project.id}/members/search"),
        headers=admin.headers,
        params={"user_id": [writer.user.id, reader.user.id]},
    )
    assert response.status_code == 200
    body = response.json()
    assert [item["username"] for item in body["items"]] == ["quill"]


async def test_search_project_members_requires_read_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild member with no access to the project (not in its initiative)
    cannot read its assignable roster."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)
    outsider = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    response = await client.get(
        outsider.g(f"/projects/{project.id}/members/search"), headers=outsider.headers
    )
    # RLS hides the initiative's content from a non-member → 404.
    assert response.status_code in (403, 404)


async def test_list_projects_shows_archived_only_when_asked(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(
        session, admin.initiative, admin.user, archived_at=datetime.now(timezone.utc)
    )

    response = await client.get(admin.g("/projects/"), headers=admin.headers)
    assert response.status_code == 200
    assert project.id not in {p["id"] for p in response.json()["items"]}

    response = await client.get(
        admin.g("/projects/?archived=true"), headers=admin.headers
    )
    assert response.status_code == 200
    assert project.id in {p["id"] for p in response.json()["items"]}


async def test_list_projects_filters_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A project list is scoped to one initiative in SQL.

    Every tool page is addressed inside its initiative now, so the list it
    renders must come back already narrowed rather than filtered client-side.
    """
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    other_initiative = await create_initiative(session, admin.guild, admin.user)
    mine = await create_project(session, admin.initiative, admin.user, name="Mine")
    theirs = await create_project(session, other_initiative, admin.user, name="Theirs")

    response = await client.get(
        admin.g(f"/projects/?initiative_id={admin.initiative.id}"),
        headers=admin.headers,
    )

    assert response.status_code == 200
    body = response.json()
    project_ids = {p["id"] for p in body["items"]}
    assert mine.id in project_ids
    assert theirs.id not in project_ids
    # The count is narrowed too, or the pager would offer empty pages.
    assert body["total_count"] == 1


async def test_list_projects_without_initiative_spans_them_all(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Omitting the filter keeps the cross-initiative behaviour the guild home
    and the sidebar's project tree depend on."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    other_initiative = await create_initiative(session, admin.guild, admin.user)
    mine = await create_project(session, admin.initiative, admin.user, name="Mine")
    theirs = await create_project(session, other_initiative, admin.user, name="Theirs")

    response = await client.get(admin.g("/projects/"), headers=admin.headers)

    assert response.status_code == 200
    project_ids = {p["id"] for p in response.json()["items"]}
    assert {mine.id, theirs.id} <= project_ids


async def test_list_projects_search_filters_by_name(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The ``search`` param matches a word, by prefix, through the index.

    Not a substring match on the name, which is what it used to be and what
    this said until the index took over: a partial word finds it, and a word
    from the description would too.
    """
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    alpha = await create_project(session, admin.initiative, admin.user, name="Alpha")
    await create_project(session, admin.initiative, admin.user, name="Beta")

    response = await client.get(
        admin.g("/projects/?search=alph"), headers=admin.headers
    )

    assert response.status_code == 200
    data = response.json()["items"]
    names = {p["name"] for p in data}
    assert names == {"Alpha"}
    assert data[0]["id"] == alpha.id


async def test_list_projects_search_with_no_searchable_term_matches_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Punctuation is not a word, so there is nothing for it to match.

    Searching is indexed now, and an index holds words. A bare ``%`` used to be
    matched literally as a substring; it now matches nothing — which reads
    better than the unfiltered list, where the filter looks ignored.
    """
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_project(session, admin.initiative, admin.user, name="50% done")
    await create_project(session, admin.initiative, admin.user, name="Beta")

    response = await client.get(admin.g("/projects/?search=%25"), headers=admin.headers)

    assert response.status_code == 200
    assert response.json()["items"] == []

    # The words around it are what finds it.
    response = await client.get(
        admin.g("/projects/?search=done"), headers=admin.headers
    )
    assert {p["name"] for p in response.json()["items"]} == {"50% done"}


async def test_list_projects_paginates_in_sql(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """total_count reflects the full matching set even when a page truncates it."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    for i in range(3):
        await create_project(session, admin.initiative, admin.user, name=f"P{i}")

    response = await client.get(
        admin.g("/projects/?page=1&page_size=2"), headers=admin.headers
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total_count"] >= 3
    assert body["has_next"] is True

    page2 = await client.get(
        admin.g("/projects/?page=2&page_size=2"), headers=admin.headers
    )
    assert page2.status_code == 200
    # Pages don't overlap.
    ids_p1 = {p["id"] for p in body["items"]}
    ids_p2 = {p["id"] for p in page2.json()["items"]}
    assert ids_p1.isdisjoint(ids_p2)


async def test_list_projects_slim_projection(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """slim=true keeps id/name/initiative/can but drops the
    heavy relationships (documents, grants, nested initiative)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(
        session, admin.initiative, admin.user, name="Slim One"
    )

    response = await client.get(admin.g("/projects/?slim=true"), headers=admin.headers)

    assert response.status_code == 200
    item = next(p for p in response.json()["items"] if p["id"] == project.id)
    assert item["name"] == "Slim One"
    assert item["initiative_id"] == admin.initiative.id
    # Guild admin holds the owner's rung on every project.
    assert item["can"]["delete"] is True
    # Heavy fields collapse to their empty defaults in slim mode.
    assert item["documents"] == []
    assert item["grants"] == []
    assert item["tags"] == []
    assert item["initiative"] is None


async def test_list_projects_slim_permission_for_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Slim projection computes ``can`` from DAC grants, not just
    the guild-admin shortcut."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, admin.user)
    await create_resource_grant(
        session, project, user=member.user, level=ResourceAccessLevel.write
    )

    response = await client.get(
        member.g("/projects/?slim=true"), headers=member.headers
    )

    assert response.status_code == 200
    item = next(p for p in response.json()["items"] if p["id"] == project.id)
    assert (item["can"]["edit"], item["can"]["delete"]) == (True, False)


async def test_create_project(client: AsyncClient, acting_user):
    """Test creating a new project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "name": "New Project",
        "description": "Project description",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Project"
    assert data["description"] == "Project description"
    assert data["initiative"]["id"] == admin.initiative.id


async def test_create_refuses_when_projects_are_switched_off(
    client: AsyncClient, acting_user, session
):
    """Projects are a tool like any other now: an initiative that has turned
    them off refuses to hold one, and says so rather than letting RLS drop the
    row and answering as though it were never asked."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.projects_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/projects/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "PROJECTS_NOT_ENABLED"


async def test_a_guild_admin_does_not_list_projects_of_a_switched_off_initiative(
    client: AsyncClient, acting_user, session
):
    """The RLS leg admits a guild admin and a PAM reader so a maintenance sweep
    can still reach the rows. A list is not where that exemption should surface:
    otherwise the two readers with the most authority are the only ones shown
    content that the detail route then refuses them."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    listed = await client.get(a.g("/projects/"), headers=a.headers)
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()["items"]] == [a.project.id]

    a.initiative.projects_enabled = False
    session.add(a.initiative)
    await session.commit()

    listed = await client.get(a.g("/projects/"), headers=a.headers)
    assert listed.status_code == 200
    assert listed.json()["items"] == []


async def test_create_project_with_dates(client: AsyncClient, acting_user):
    """Start/end dates round-trip through create, the detail read, and the list."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "name": "Scheduled Project",
        "initiative_id": admin.initiative.id,
        "start_date": "2026-03-02",
        "end_date": "2026-09-30",
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    created = response.json()
    assert created["start_date"] == "2026-03-02"
    assert created["end_date"] == "2026-09-30"

    listed = await client.get(admin.g("/projects/"), headers=admin.headers)
    assert listed.status_code == 200
    item = next(p for p in listed.json()["items"] if p["id"] == created["id"])
    assert item["start_date"] == "2026-03-02"
    assert item["end_date"] == "2026-09-30"


async def test_create_project_without_dates_leaves_them_unset(
    client: AsyncClient, acting_user
):
    """Both dates are optional — omitting them is not an error."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.post(
        admin.g("/projects/"),
        headers=admin.headers,
        json={"name": "Undated Project", "initiative_id": admin.initiative.id},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["start_date"] is None
    assert data["end_date"] is None


def _as_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _tasks_by_title(
    client: AsyncClient, actor, project_id: int
) -> dict[str, dict]:
    conditions = json.dumps([{"field": "project_id", "op": "eq", "value": project_id}])
    response = await client.get(
        actor.g(f"/tasks/?conditions={conditions}"), headers=actor.headers
    )
    assert response.status_code == 200
    return {item["title"]: item for item in response.json()["items"]}


async def test_create_from_template_shifts_task_dates(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Template task dates are re-anchored to the new project's start date.

    A task due three weeks after the template's start lands three weeks after
    the new start, keeping its time of day.
    """
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    template = await create_project(
        session,
        admin.initiative,
        admin.user,
        name="Launch Template",
        is_template=True,
        start_date=date(2026, 1, 5),
        end_date=date(2026, 2, 2),
    )
    await create_task(
        session,
        template,
        title="Kickoff",
        start_date=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        due_date=datetime(2026, 1, 7, 17, 0, tzinfo=timezone.utc),
    )
    await create_task(
        session,
        template,
        title="Three weeks in",
        due_date=datetime(2026, 1, 26, 12, 0, tzinfo=timezone.utc),
    )

    response = await client.post(
        admin.g("/projects/"),
        headers=admin.headers,
        json={
            "name": "Spring Launch",
            "initiative_id": admin.initiative.id,
            "template_id": template.id,
            "start_date": "2026-04-06",
            "end_date": "2026-05-04",
        },
    )
    assert response.status_code == 201

    tasks = await _tasks_by_title(client, admin, response.json()["id"])
    kickoff = tasks["Kickoff"]
    assert _as_utc(kickoff["start_date"]) == datetime(
        2026, 4, 6, 9, 0, tzinfo=timezone.utc
    )
    assert _as_utc(kickoff["due_date"]) == datetime(
        2026, 4, 8, 17, 0, tzinfo=timezone.utc
    )
    assert _as_utc(tasks["Three weeks in"]["due_date"]) == datetime(
        2026, 4, 27, 12, 0, tzinfo=timezone.utc
    )


async def _relations_of(client: AsyncClient, actor, task_id: int) -> list[dict]:
    response = await client.get(
        actor.g(f"/relationships/?entity=task:{task_id}"), headers=actor.headers
    )
    assert response.status_code == 200
    return response.json()


async def _template_with_dependency(session: AsyncSession, admin) -> tuple:
    """A template whose second task is blocked by its first."""
    template = await create_project(
        session, admin.initiative, admin.user, name="Tpl", is_template=True
    )
    first = await create_task(session, template, title="Design")
    second = await create_task(session, template, title="Build")
    await create_relationship(
        session,
        admin.guild,
        source=(SearchEntityType.task, second.id),
        target=(SearchEntityType.task, first.id),
        relationship_type=RelationshipType.depends_on,
    )
    return template, first, second


async def test_create_from_template_copies_task_relations(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A dependency between two template tasks lands between their copies.

    Both ends are remapped to the new project's tasks; the template's own
    tasks keep their edge and gain nothing pointing at the copies.
    """
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    template, first, second = await _template_with_dependency(session, admin)

    response = await client.post(
        admin.g("/projects/"),
        headers=admin.headers,
        json={
            "name": "From template",
            "initiative_id": admin.initiative.id,
            "template_id": template.id,
        },
    )
    assert response.status_code == 201

    tasks = await _tasks_by_title(client, admin, response.json()["id"])
    new_first, new_second = tasks["Design"], tasks["Build"]
    assert {new_first["id"], new_second["id"]}.isdisjoint({first.id, second.id})

    blocked = await _relations_of(client, admin, new_second["id"])
    assert [
        (r["relationship_type"], r["direction"], r["other"]["id"]) for r in blocked
    ] == [("depends_on", "outbound", new_first["id"])]
    blocking = await _relations_of(client, admin, new_first["id"])
    assert [(r["direction"], r["other"]["id"]) for r in blocking] == [
        ("inbound", new_second["id"])
    ]

    original = await _relations_of(client, admin, first.id)
    assert [r["other"]["id"] for r in original] == [second.id]


async def test_duplicate_project_copies_task_relations(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Duplicating a project carries its task relations, ids remapped, and
    a symmetric relation to something outside the project is kept as-is."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    source, first, second = await _template_with_dependency(session, admin)
    other_project = await create_project(
        session, admin.initiative, admin.user, name="Elsewhere"
    )
    outside = await create_task(session, other_project, title="Outside")
    await create_relationship(
        session,
        admin.guild,
        source=(SearchEntityType.task, outside.id),
        target=(SearchEntityType.task, first.id),
        relationship_type=RelationshipType.related_to,
    )

    response = await client.post(
        admin.g(f"/projects/{source.id}/duplicate"),
        headers=admin.headers,
        json={"name": "Copy"},
    )
    assert response.status_code == 201

    tasks = await _tasks_by_title(client, admin, response.json()["id"])
    new_first, new_second = tasks["Design"], tasks["Build"]

    relations = await _relations_of(client, admin, new_first["id"])
    assert sorted((r["relationship_type"], r["other"]["id"]) for r in relations) == [
        ("depends_on", new_second["id"]),
        ("related_to", outside.id),
    ]


async def test_a_duplicate_keeps_the_sources_sharing_and_needs_the_create_right(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A copy is shared with whoever the source is shared with, not with every
    member; and making one is making a project, so a writer whose role may not
    create projects is refused in those words."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    writer = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    bystander = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, owner.project, user=writer.user, level=ResourceAccessLevel.write
    )
    url = owner.g(f"/projects/{owner.project.id}/duplicate")

    refused = await client.post(url, headers=writer.headers, json={})
    assert refused.status_code == 403
    assert refused.json()["detail"] == Tool.project.create_permission_code

    copied = await client.post(url, headers=owner.headers, json={})
    assert copied.status_code == 201
    copy_url = owner.g(f"/projects/{copied.json()['id']}")
    as_writer = await client.get(copy_url, headers=writer.headers)
    assert as_writer.json()["can"]["edit"] is True
    assert as_writer.json()["can"]["share"] is False
    as_bystander = await client.get(copy_url, headers=bystander.headers)
    assert as_bystander.status_code == 403


async def test_create_from_undated_template_anchors_on_earliest_task(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A template without its own dates anchors on its earliest task date, so
    the first scheduled task lands on the new start and spacing is kept."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    template = await create_project(
        session, admin.initiative, admin.user, name="Undated Template", is_template=True
    )
    await create_task(
        session,
        template,
        title="First",
        due_date=datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc),
    )
    await create_task(
        session,
        template,
        title="Two weeks later",
        due_date=datetime(2026, 1, 19, 10, 0, tzinfo=timezone.utc),
    )

    response = await client.post(
        admin.g("/projects/"),
        headers=admin.headers,
        json={
            "name": "Summer Run",
            "initiative_id": admin.initiative.id,
            "template_id": template.id,
            "start_date": "2026-06-01",
        },
    )
    assert response.status_code == 201

    tasks = await _tasks_by_title(client, admin, response.json()["id"])
    assert _as_utc(tasks["First"]["due_date"]) == datetime(
        2026, 6, 1, 10, 0, tzinfo=timezone.utc
    )
    assert _as_utc(tasks["Two weeks later"]["due_date"]) == datetime(
        2026, 6, 15, 10, 0, tzinfo=timezone.utc
    )


async def test_create_from_template_end_date_only_anchors_on_end(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """With only an end date given, tasks shift so the template's end maps to
    the new end (a task due a week before the end stays a week before it)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    template = await create_project(
        session,
        admin.initiative,
        admin.user,
        name="Deadline Template",
        is_template=True,
        end_date=date(2026, 2, 2),
    )
    await create_task(
        session,
        template,
        title="Final review",
        due_date=datetime(2026, 1, 26, 15, 0, tzinfo=timezone.utc),
    )

    response = await client.post(
        admin.g("/projects/"),
        headers=admin.headers,
        json={
            "name": "Autumn Deadline",
            "initiative_id": admin.initiative.id,
            "template_id": template.id,
            "end_date": "2026-08-31",
        },
    )
    assert response.status_code == 201

    tasks = await _tasks_by_title(client, admin, response.json()["id"])
    assert _as_utc(tasks["Final review"]["due_date"]) == datetime(
        2026, 8, 24, 15, 0, tzinfo=timezone.utc
    )


async def test_create_from_template_without_dates_copies_task_dates_verbatim(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """No start or end on the new project means no re-anchoring — task dates
    (including start dates) come across unchanged."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    template = await create_project(
        session,
        admin.initiative,
        admin.user,
        name="Plain Template",
        is_template=True,
        start_date=date(2026, 1, 5),
    )
    await create_task(
        session,
        template,
        title="Kickoff",
        start_date=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
        due_date=datetime(2026, 1, 26, 12, 0, tzinfo=timezone.utc),
    )

    response = await client.post(
        admin.g("/projects/"),
        headers=admin.headers,
        json={
            "name": "Undated Run",
            "initiative_id": admin.initiative.id,
            "template_id": template.id,
        },
    )
    assert response.status_code == 201

    tasks = await _tasks_by_title(client, admin, response.json()["id"])
    kickoff = tasks["Kickoff"]
    assert _as_utc(kickoff["start_date"]) == datetime(
        2026, 1, 5, 9, 0, tzinfo=timezone.utc
    )
    assert _as_utc(kickoff["due_date"]) == datetime(
        2026, 1, 26, 12, 0, tzinfo=timezone.utc
    )


async def test_update_project_sets_and_clears_dates(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A patch can set either date on its own and clear it again with null."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)

    set_end_only = await client.patch(
        owner.g(f"/projects/{project.id}"),
        headers=owner.headers,
        json={"end_date": "2026-12-31"},
    )
    assert set_end_only.status_code == 200
    assert set_end_only.json()["end_date"] == "2026-12-31"
    assert set_end_only.json()["start_date"] is None

    # Omitted fields stay untouched; an explicit null clears.
    add_start = await client.patch(
        owner.g(f"/projects/{project.id}"),
        headers=owner.headers,
        json={"start_date": "2026-01-05"},
    )
    assert add_start.status_code == 200
    assert add_start.json()["start_date"] == "2026-01-05"
    assert add_start.json()["end_date"] == "2026-12-31"

    cleared = await client.patch(
        owner.g(f"/projects/{project.id}"),
        headers=owner.headers,
        json={"start_date": None, "end_date": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["start_date"] is None
    assert cleared.json()["end_date"] is None


async def test_create_project_as_member(client: AsyncClient, acting_user):
    """Test that initiative members can create projects."""
    member = await acting_user(guild_role=GuildRole.member, initiative=True)

    payload = {
        "name": "Member Project",
        "initiative_id": member.initiative.id,
    }

    response = await client.post(
        member.g("/projects/"), headers=member.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Member Project"


async def test_create_project_not_in_initiative_forbidden(
    client: AsyncClient, acting_user
):
    """Test that users not in initiative cannot create projects."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    payload = {
        "name": "Forbidden Project",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        outsider.g("/projects/"), headers=outsider.headers, json=payload
    )

    assert response.status_code == 403


async def test_get_project_by_id(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test getting a project by ID."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)

    response = await client.get(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project.id
    assert data["name"] == project.name


async def test_get_project_includes_task_statuses(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The detail read carries the project's task statuses, ordered by position."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)
    done = await create_task_status(
        session, project, name="Done", category=TaskStatusCategory.done, position=1
    )
    backlog = await create_task_status(
        session,
        project,
        name="Backlog",
        category=TaskStatusCategory.backlog,
        position=0,
    )

    response = await client.get(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )

    assert response.status_code == 200
    statuses = response.json()["task_statuses"]
    # Ordered by position: backlog (0) before done (1).
    assert [s["id"] for s in statuses] == [backlog.id, done.id]
    assert [s["category"] for s in statuses] == ["backlog", "done"]


async def test_list_projects_omits_task_statuses(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The list projection stays lean — statuses are a detail-read enrichment."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)
    await create_task_status(
        session, project, name="Done", category=TaskStatusCategory.done
    )

    response = await client.get(admin.g("/projects/"), headers=admin.headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert items and all(item["task_statuses"] == [] for item in items)


async def test_get_project_not_found(client: AsyncClient, acting_user):
    """Test getting non-existent project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(admin.g("/projects/99999"), headers=admin.headers)

    assert response.status_code == 404


async def test_update_project_as_owner(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that project owner can update project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)

    payload = {"name": "Updated Name", "description": "Updated description"}

    response = await client.patch(
        owner.g(f"/projects/{project.id}"), headers=owner.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"


async def test_update_project_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can update any project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    owner = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, owner.user)

    payload = {"name": "Admin Updated"}

    response = await client.patch(
        admin.g(f"/projects/{project.id}"), headers=admin.headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Admin Updated"


async def test_update_project_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that users without permission cannot update project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    project = await create_project(session, owner.initiative, owner.user)

    payload = {"name": "Hacked Name"}

    response = await client.patch(
        outsider.g(f"/projects/{project.id}"), headers=outsider.headers, json=payload
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


async def test_delete_project_as_owner(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that project owner can delete project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, owner.initiative, owner.user)

    response = await client.delete(
        owner.g(f"/projects/{project.id}"), headers=owner.headers
    )

    assert response.status_code == 204


async def test_delete_project_as_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that guild admin can delete any project."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    owner = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, owner.user)

    response = await client.delete(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )

    assert response.status_code == 204


async def test_delete_project_without_permission_forbidden(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that users without permission cannot delete project."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    project = await create_project(session, owner.initiative, owner.user)

    response = await client.delete(
        outsider.g(f"/projects/{project.id}"), headers=outsider.headers
    )

    assert (
        response.status_code == 404
    )  # RLS hides the content resource from a non-initiative-member (404, not 403)


async def test_favoriting_a_project_lists_it_until_it_is_unfavorited(
    client: AsyncClient, session: AsyncSession, acting_user
):
    user = await acting_user(guild_role=GuildRole.member, initiative=True)
    project = await create_project(session, user.initiative, user.user)
    url = user.g(f"/projects/{project.id}/favorite")

    added = await client.post(url, headers=user.headers)
    assert added.status_code == 200
    assert added.json()["is_favorited"] is True
    listed = await client.get(user.g("/projects/favorites"), headers=user.headers)
    assert [(p["id"], p["is_favorited"]) for p in listed.json()] == [(project.id, True)]

    removed = await client.delete(url, headers=user.headers)
    assert removed.status_code == 200
    assert removed.json()["is_favorited"] is False
    listed = await client.get(user.g("/projects/favorites"), headers=user.headers)
    assert listed.json() == []


async def _task_assignee_ids(session, guild_id: int, task_id: int) -> set[int]:
    """Read task_assignees straight from the guild schema (superuser session)."""
    await session.commit()
    await route_session_to_guild(session, guild_id)
    return set(
        (
            await session.exec(
                text("SELECT user_id FROM task_assignees WHERE task_id = :tid"),
                params={"tid": task_id},
            )
        ).scalars()
    )


async def test_a_grant_change_unassigns_only_who_loses_write(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Nobody stays assigned to tasks they can no longer edit, and the cleanup
    reads effective access: write kept through another grant keeps the
    assignment."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)
    await create_resource_grant(
        session, project, user=member.user, level=ResourceAccessLevel.write
    )
    task = await create_task(session, project, assignees=[member.user])
    url = owner.g(f"/projects/{project.id}/grants")

    # The per-user grant swapped for an all-members write grant: still write.
    r = await client.put(
        url,
        headers=owner.headers,
        json=[{"all_initiative_members": True, "level": "write"}],
    )
    assert r.status_code == 200
    assert member.user.id in await _task_assignee_ids(session, owner.guild.id, task.id)

    # Every grant removed: the member drops to nothing and is unassigned.
    r = await client.put(url, headers=owner.headers, json=[])
    assert r.status_code == 200
    assert member.user.id not in await _task_assignee_ids(
        session, owner.guild.id, task.id
    )


async def test_project_guild_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test that projects are isolated by guild."""
    # Same user is a guild admin in two separate guilds/initiatives.
    a1 = await acting_user(
        guild_role=GuildRole.admin, initiative=True, email="user@example.com"
    )
    user = a1.user
    initiative1 = a1.initiative

    guild2 = await create_guild(session, name="Guild 2")
    await create_guild_membership(
        session, user=user, guild=guild2, role=GuildRole.admin
    )
    initiative2 = await create_initiative(session, guild2, user)

    # Distinct names so the cross-guild check below can tell them apart even when
    # their per-schema ids collide.
    project1 = await create_project(session, initiative1, user, name="Guild 1 Project")
    await create_project(session, initiative2, user, name="Guild 2 Project")

    # Request with guild1 context
    response1 = await client.get(a1.g("/projects/"), headers=a1.headers)

    assert response1.status_code == 200
    data1 = response1.json()["items"]
    project_names1 = {p["name"] for p in data1}
    assert "Guild 1 Project" in project_names1
    assert "Guild 2 Project" not in project_names1

    # Cannot access guild1's project with guild2 context. Under schema-per-guild
    # ids are per-schema (not globally unique), so project1.id may collide with a
    # guild2 project — but it must never resolve to guild1's project.
    response2 = await client.get(
        replace(a1, guild=guild2).g(f"/projects/{project1.id}"), headers=a1.headers
    )

    if response2.status_code == 200:
        assert response2.json()["name"] != "Guild 1 Project"
    else:
        assert response2.status_code == 404


async def test_create_project_takes_its_sharing_from_grants(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The creator owns what they make: ``owner_id`` is not a field, and an
    owner-level grant is not taken. Named people and the initiative's own roles
    are shared with; a role from another initiative is dropped."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    other_initiative = await create_initiative(session, admin.guild, admin.user)
    member_role, foreign_role = [
        (
            await session.exec(
                select(InitiativeRoleModel.id).where(
                    InitiativeRoleModel.initiative_id == initiative.id,
                    InitiativeRoleModel.name == "member",
                )
            )
        ).one()
        for initiative in (admin.initiative, other_initiative)
    ]

    response = await client.post(
        admin.g("/projects/"),
        headers=admin.headers,
        json={
            "name": "Shared",
            "initiative_id": admin.initiative.id,
            "owner_id": member.user.id,
            "grants": [
                {"user_id": member.user.id, "level": "write"},
                {"user_id": other.user.id, "level": "owner"},
                {"role_id": member_role, "level": "read"},
                {"role_id": foreign_role, "level": "read"},
            ],
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["owner_id"] == admin.user.id
    assert {(g["level"], g["user_id"], g["role_id"]) for g in data["grants"]} == {
        ("owner", admin.user.id, None),
        ("write", member.user.id, None),
        ("read", None, member_role),
    }


async def test_create_project_defaults_to_all_members_viewer(
    client: AsyncClient, acting_user
):
    """Omitting `grants` defaults to Viewer for all initiative members (+ owner)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "name": "Project Default Share",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        admin.g("/projects/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Owner grant + an all-initiative-members Viewer (read) grant.
    assert any(
        g["user_id"] == admin.user.id and g["level"] == "owner" for g in data["grants"]
    )
    assert any(
        g["all_initiative_members"] and g["level"] == "read" for g in data["grants"]
    )
    assert data["can"]["delete"] is True


async def test_resaving_the_all_members_grant_does_not_collide_with_itself(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``replace_resource_grants`` deletes every non-owner grant and inserts
    the kept set. The delete is flushed first, or the new all-members row
    collides with the old one under ``resource_grants_unique_grantee``. One
    save hits both ways a sharing panel reaches it: dropping a person beside
    the all-members grant, and changing that grant's level."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)
    await create_resource_grant(session, project, all_initiative_members=True)
    await create_resource_grant(
        session, project, user=member.user, level=ResourceAccessLevel.write
    )

    r = await client.put(
        owner.g(f"/projects/{project.id}/grants"),
        headers=owner.headers,
        json=[{"all_initiative_members": True, "level": "write"}],
    )
    assert r.status_code == 200, r.text
    assert [
        (g["level"], g["user_id"], g["all_initiative_members"])
        for g in r.json()["grants"]
        if g["level"] != "owner"
    ] == [("write", None, True)]


async def test_project_shows_all_members_document_to_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A document attached to a project and shared with *all initiative members*
    is visible to a plain member on the project view. Regression: the linked-doc
    filter used to ignore all-members grants, so such docs vanished for anyone
    without a personal/role grant."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)
    doc = await create_document(session, owner.initiative, owner.user)
    # The project too, so the member can open it at all.
    await create_resource_grant(session, project, all_initiative_members=True)
    await create_resource_grant(session, doc, all_initiative_members=True)
    await create_relationship(
        session,
        owner.guild,
        source=(SearchEntityType.project, project.id),
        target=(SearchEntityType.document, doc.id),
        created_by=owner.user.id,
    )

    r = await client.get(member.g(f"/projects/{project.id}"), headers=member.headers)
    assert r.status_code == 200, r.text
    doc_ids = [d["document_id"] for d in r.json()["documents"]]
    assert doc.id in doc_ids


async def test_project_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts mirror the default list: visible, non-archived,
    non-template projects only, with no entry for unjoined initiatives."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    other_initiative = await create_initiative(session, admin.guild, admin.user)

    await create_project(session, admin.initiative, member.user, name="Member project")
    await create_project(session, admin.initiative, admin.user, name="Admin project")
    await create_project(
        session,
        admin.initiative,
        admin.user,
        name="Archived",
        archived_at=datetime.now(timezone.utc),
    )
    await create_project(
        session, admin.initiative, admin.user, name="Template", is_template=True
    )
    await create_project(session, other_initiative, admin.user, name="Other project")

    # Guild admin: the counts span initiatives, so they count what reaches
    # the reader — the admin's own project in each, not the member's beside it.
    response = await client.get(
        admin.g("/projects/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {
        str(admin.initiative.id): 1,
        str(other_initiative.id): 1,
    }

    # Member: only projects shared with them, and no entry for
    # initiatives they are not in.
    response = await client.get(
        member.g("/projects/counts/by-initiative"), headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {str(admin.initiative.id): 1}


# ── Default view mode ─────────────────────────────────────────────────
# Which view a project opens on is project configuration, not content: it takes
# a project manager, the project owner, or a guild admin — the same bar as
# pinning.


async def test_project_owner_sets_the_default_view(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    response = await client.patch(
        a.g(f"/projects/{a.project.id}"),
        json={"default_view_mode": "kanban"},
        headers=a.headers,
    )

    assert response.status_code == 200
    assert response.json()["default_view_mode"] == "kanban"


async def test_guild_admin_sets_the_default_view(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)

    response = await client.patch(
        admin.g(f"/projects/{owner.project.id}"),
        json={"default_view_mode": "calendar"},
        headers=admin.headers,
    )

    assert response.status_code == 200
    assert response.json()["default_view_mode"] == "calendar"


async def test_plain_write_edits_but_cannot_set_the_default_view(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The escalation is per-field: renaming a project is still plain write."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    editor = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, owner.project, user=editor.user, level=ResourceAccessLevel.write
    )
    url = editor.g(f"/projects/{owner.project.id}")

    response = await client.patch(
        url, json={"default_view_mode": "kanban"}, headers=editor.headers
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "PROJECT_CONFIGURE_REQUIRED"

    response = await client.patch(
        url, json={"name": "Renamed by an editor"}, headers=editor.headers
    )
    assert response.status_code == 200


async def test_default_view_rejects_an_unknown_mode(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    response = await client.patch(
        a.g(f"/projects/{a.project.id}"),
        json={"default_view_mode": "gantt"},
        headers=a.headers,
    )

    assert response.status_code == 422


# ── Presets travel with the project ───────────────────────────────────


async def test_new_project_is_seeded_with_default_presets(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)

    created = await client.post(
        a.g("/projects/"),
        json={"name": "Fresh", "initiative_id": a.initiative.id},
        headers=a.headers,
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    presets = await client.get(
        a.g(f"/projects/{project_id}/filter-presets/"), headers=a.headers
    )

    assert [p["slug"] for p in presets.json()["items"]] == [
        "all",
        "incomplete",
        "unassigned",
        "mine",
    ]


async def test_duplicating_a_project_clones_its_presets(
    client: AsyncClient, session: AsyncSession, acting_user
):
    from app.services.tenant import filter_presets as filter_presets_service

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    source_status = await create_task_status(session, project=a.project, name="Review")
    seeded = await filter_presets_service.ensure_default_presets(session, a.project.id)
    mine = next(p for p in seeded if p.slug == "mine")
    mine.filters = {"status_ids": [source_status.id], "assignees": ["me"]}
    session.add(mine)
    await session.commit()

    duplicated = await client.post(
        a.g(f"/projects/{a.project.id}/duplicate"),
        json={"name": "Copy"},
        headers=a.headers,
    )
    assert duplicated.status_code == 201
    copy_id = duplicated.json()["id"]

    presets = (
        await client.get(a.g(f"/projects/{copy_id}/filter-presets/"), headers=a.headers)
    ).json()["items"]
    by_slug = {p["slug"]: p for p in presets}

    assert set(by_slug) == {"all", "incomplete", "unassigned", "mine"}
    assert by_slug["all"]["is_default"] is True
    # The status id was translated to the copy's own status, not carried over.
    cloned_status_ids = by_slug["mine"]["filters"]["status_ids"]
    assert cloned_status_ids
    assert source_status.id not in cloned_status_ids
