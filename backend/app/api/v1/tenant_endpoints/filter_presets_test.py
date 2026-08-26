"""Filter preset endpoints, and who may curate them.

Reads follow project read. Every mutation needs the right to *configure* the
project — a project manager, the project owner, or a guild admin — which is a
step above plain write access.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.services.tenant import filter_presets as filter_presets_service
from app.testing.factories import create_project

pytestmark = pytest.mark.integration


def _url(project, suffix: str = "/") -> str:
    return f"/api/v1/g/{project.guild_id}/projects/{project.id}/filter-presets{suffix}"


async def _grant(session: AsyncSession, project, user, level: ResourceAccessLevel):
    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=project.id,
            user_id=user.id,
            level=level,
            guild_id=project.guild_id,
            initiative_id=project.initiative_id,
        )
    )
    await session.commit()


async def _seed(session: AsyncSession, project):
    presets = await filter_presets_service.ensure_default_presets(session, project.id)
    await session.commit()
    return presets


# ── Reads ────────────────────────────────────────────────────────────


async def test_list_returns_the_seeded_defaults(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _seed(session, a.project)

    response = await client.get(_url(a.project), headers=a.headers)

    assert response.status_code == 200
    body = response.json()
    assert [p["slug"] for p in body["items"]] == [
        "all",
        "incomplete",
        "unassigned",
        "mine",
    ]
    assert body["can_manage"] is True


async def test_list_does_not_seed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A GET must not write: a read-only PAM grantee and a frozen guild both
    route into a SELECT-only role, and a mutating read would fail for them."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    response = await client.get(_url(a.project), headers=a.headers)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert await filter_presets_service.list_presets(session, a.project.id) == []


async def test_a_project_without_presets_heals_on_the_next_write(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The read path never seeds — a read-only grantee routes into a
    SELECT-only role and could not — so writing a task is what repairs a
    project the backfill never reached."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    assert await filter_presets_service.list_presets(session, a.project.id) == []

    created = await client.post(
        a.g("/tasks/"),
        json={"title": "First task", "project_id": a.project.id},
        headers=a.headers,
    )
    assert created.status_code == 201

    listed = await client.get(_url(a.project), headers=a.headers)
    assert [p["slug"] for p in listed.json()["items"]] == [
        "all",
        "incomplete",
        "unassigned",
        "mine",
    ]


# ── The permission matrix ────────────────────────────────────────────


async def test_initiative_manager_may_manage_without_a_grant(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    pm = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="project_manager",
    )
    await _grant(session, owner.project, pm.user, ResourceAccessLevel.read)
    await _seed(session, owner.project)

    response = await client.post(
        _url(owner.project),
        json={"name": "Blocked work"},
        headers=pm.headers,
    )

    assert response.status_code == 201


async def test_project_owner_may_manage(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _seed(session, a.project)

    response = await client.post(
        _url(a.project), json={"name": "My sprint"}, headers=a.headers
    )

    assert response.status_code == 201


async def test_guild_admin_may_manage(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)
    await _seed(session, owner.project)

    response = await client.post(
        _url(owner.project), json={"name": "Triage"}, headers=admin.headers
    )

    assert response.status_code == 201


async def test_plain_write_access_is_not_enough(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    editor = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await _grant(session, owner.project, editor.user, ResourceAccessLevel.write)
    presets = await _seed(session, owner.project)

    create = await client.post(
        _url(owner.project), json={"name": "Nope"}, headers=editor.headers
    )
    patch = await client.patch(
        _url(owner.project, f"/{presets[0].id}"),
        json={"name": "Renamed"},
        headers=editor.headers,
    )
    remove = await client.delete(
        _url(owner.project, f"/{presets[3].id}"), headers=editor.headers
    )

    assert create.status_code == 403
    assert create.json()["detail"] == "PROJECT_ADMIN_REQUIRED"
    assert patch.status_code == 403
    assert remove.status_code == 403
    # …but they can still read them.
    listed = await client.get(_url(owner.project), headers=editor.headers)
    assert listed.status_code == 200
    assert listed.json()["can_manage"] is False


async def test_read_access_cannot_mutate(
    client: AsyncClient, session: AsyncSession, acting_user
):
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    viewer = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await _grant(session, owner.project, viewer.user, ResourceAccessLevel.read)
    await _seed(session, owner.project)

    response = await client.post(
        _url(owner.project), json={"name": "Nope"}, headers=viewer.headers
    )

    assert response.status_code == 403


async def test_non_member_of_the_initiative_gets_404(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """RLS hides the initiative's content from a guild member who isn't in it,
    so this is a 404 rather than a 403."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)
    await _seed(session, owner.project)

    listed = await client.get(_url(owner.project), headers=outsider.headers)
    created = await client.post(
        _url(owner.project), json={"name": "Nope"}, headers=outsider.headers
    )

    assert listed.status_code == 404
    assert created.status_code == 404


# ── Behaviour ────────────────────────────────────────────────────────


async def test_create_derives_a_unique_slug(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _seed(session, a.project)

    first = await client.post(_url(a.project), json={"name": "Mine"}, headers=a.headers)
    second = await client.post(
        _url(a.project), json={"name": "Mine"}, headers=a.headers
    )

    assert first.json()["slug"] == "mine-2"
    assert second.json()["slug"] == "mine-3"


async def test_create_as_default_demotes_the_previous_one(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _seed(session, a.project)

    created = await client.post(
        _url(a.project),
        json={"name": "Sprint", "is_default": True},
        headers=a.headers,
    )

    assert created.status_code == 201
    listed = (await client.get(_url(a.project), headers=a.headers)).json()["items"]
    assert [p["slug"] for p in listed if p["is_default"]] == ["sprint"]


async def test_patch_cannot_change_the_slug(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A slug is what a shared link carries, so renaming must not move it."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    presets = await _seed(session, a.project)
    mine = next(p for p in presets if p.slug == "mine")

    response = await client.patch(
        _url(a.project, f"/{mine.id}"),
        json={"name": "Assigned to me", "slug": "assigned"},
        headers=a.headers,
    )

    assert response.status_code == 200
    assert response.json()["slug"] == "mine"
    assert response.json()["name"] == "Assigned to me"


async def test_deleting_the_default_promotes_a_survivor(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    presets = await _seed(session, a.project)
    all_preset = next(p for p in presets if p.slug == "all")

    response = await client.delete(
        _url(a.project, f"/{all_preset.id}"), headers=a.headers
    )

    assert response.status_code == 204
    listed = (await client.get(_url(a.project), headers=a.headers)).json()["items"]
    assert sum(1 for p in listed if p["is_default"]) == 1
    assert listed[0]["slug"] == "incomplete"


async def test_reorder_rejects_a_duplicate_id(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    presets = await _seed(session, a.project)

    response = await client.post(
        _url(a.project, "/reorder"),
        json={
            "items": [
                {"id": presets[0].id, "position": 0},
                {"id": presets[0].id, "position": 1},
            ]
        },
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "FILTER_PRESET_DUPLICATE_ID"


async def test_reorder_persists_positions(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    presets = await _seed(session, a.project)
    reversed_ids = [p.id for p in reversed(presets)]

    response = await client.post(
        _url(a.project, "/reorder"),
        json={
            "items": [
                {"id": pid, "position": index} for index, pid in enumerate(reversed_ids)
            ]
        },
        headers=a.headers,
    )

    assert response.status_code == 200
    assert [p["slug"] for p in response.json()] == [
        "mine",
        "unassigned",
        "incomplete",
        "all",
    ]


async def test_unknown_filter_key_is_rejected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _seed(session, a.project)

    response = await client.post(
        _url(a.project),
        json={"name": "Weird", "filters": {"colour": ["blue"]}},
        headers=a.headers,
    )

    assert response.status_code == 422


async def test_assignee_tokens_are_validated(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _seed(session, a.project)

    response = await client.post(
        _url(a.project),
        json={"name": "Bad", "filters": {"assignees": ["everyone"]}},
        headers=a.headers,
    )

    assert response.status_code == 422


async def test_preset_limit(client: AsyncClient, session: AsyncSession, acting_user):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await _seed(session, a.project)
    for index in range(filter_presets_service.MAX_PRESETS_PER_PROJECT - 4):
        created = await client.post(
            _url(a.project), json={"name": f"Preset {index}"}, headers=a.headers
        )
        assert created.status_code == 201

    response = await client.post(
        _url(a.project), json={"name": "One too many"}, headers=a.headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "FILTER_PRESET_LIMIT_REACHED"


async def test_presets_are_scoped_to_their_project(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    other = await create_project(session, a.initiative, a.user, name="Other")
    presets = await _seed(session, a.project)

    response = await client.patch(
        f"/api/v1/g/{other.guild_id}/projects/{other.id}"
        f"/filter-presets/{presets[0].id}",
        json={"name": "Stolen"},
        headers=a.headers,
    )

    assert response.status_code == 404
