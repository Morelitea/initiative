"""The operations community's intake, set by its superadmin.

Which project each stream lands in is configured on the community's own
routes, by its seat, and only in the community the platform names.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.core.intake import IntakeStream
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildRole, GuildStatus
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.models.tenant.task import Task, TaskStatus
from app.services.platform import intake as intake_service
from app.services.tenant import task_statuses as task_statuses_service
from app.testing import (
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
    route_session_to_guild,
)

pytestmark = pytest.mark.integration


async def _point_platform_at(session, guild_id: int | None) -> None:
    """Set (or clear) ``app_settings.operations_guild_id``."""
    await set_rls_context(session)
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()


@pytest.fixture
async def ops(session, acting_user):
    """The operations community's seat, and an initiative the seat is not in.

    The initiative belongs to somebody else, so what the seat reaches inside it
    is the community admin's reach rather than an initiative membership.
    """
    seat = await acting_user(guild_role=GuildRole.superadmin)
    staff = await create_user(session)
    await create_guild_membership(
        session, user=staff, guild=seat.guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, seat.guild, staff, name="Trust")
    ids = {
        "seat": seat,
        "guild_id": seat.guild.id,
        "initiative_id": initiative.id,
        "staff_id": staff.id,
    }
    await _point_platform_at(session, seat.guild.id)
    return ids


def _url(ops, path: str = "") -> str:
    return f"/api/v1/g/{ops['guild_id']}/intake{path}"


async def _project_in(session, ops, **overrides) -> int:
    """Another project in the operations community, owned by its staff."""
    await route_session_to_guild(session, ops["guild_id"])
    initiative = (
        await session.exec(
            select(Initiative).where(Initiative.id == ops["initiative_id"])
        )
    ).one()
    staff = (await session.exec(select(User).where(User.id == ops["staff_id"]))).one()
    project = await create_project(session, initiative, staff, **overrides)
    project_id = project.id
    assert project_id is not None
    await set_rls_context(session)
    return project_id


# ── The seat of the operations community ────────────────────────────────────


async def test_every_stream_is_listed_before_anything_is_bound(client, ops):
    response = await client.get(_url(ops), headers=ops["seat"].headers)
    assert response.status_code == 200, response.text
    bindings = response.json()["bindings"]
    assert {b["stream"] for b in bindings} == {s.value for s in IntakeStream}
    assert all(b["enabled"] is False for b in bindings)


async def test_setting_a_stream_up_from_its_blueprint(client, session, ops):
    response = await client.post(
        _url(ops, "/security/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stream"] == "security"
    assert body["project_name"] == "Security"
    assert body["enabled"] is True
    assert body["initiative_id"] == ops["initiative_id"]

    # A case filed now lands in what the blueprint produced.
    outcome = await intake_service.open_case(
        IntakeStream.security, title="Refused sign-ins", body="Ten in fifteen minutes."
    )
    assert outcome is not None
    await set_rls_context(session, guild_id=ops["guild_id"])
    task = (await session.exec(select(Task).where(Task.id == outcome.task_id))).one()
    assert task.project_id == body["project_id"]


async def test_options_offer_the_communitys_projects(client, ops):
    created = await client.post(
        _url(ops, "/support/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    project_id = created.json()["project_id"]

    response = await client.get(_url(ops, "/options"), headers=ops["seat"].headers)
    assert response.status_code == 200, response.text
    initiatives = response.json()["initiatives"]
    mine = next(i for i in initiatives if i["id"] == ops["initiative_id"])
    project = next(p for p in mine["projects"] if p["id"] == project_id)
    # The blueprint's four columns, so the landing-status picker has something
    # to offer.
    assert [s["name"] for s in project["statuses"]] == [
        "Triage",
        "Investigating",
        "Awaiting response",
        "Resolved",
    ]


async def test_binding_an_existing_project(client, ops, session):
    project_id = await _project_in(session, ops)
    response = await client.put(
        _url(ops, "/support"),
        json={"project_id": project_id},
        headers=ops["seat"].headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["project_id"] == project_id
    assert response.json()["initiative_name"] == "Trust"
    assert await intake_service.stream_is_bound(IntakeStream.support) is True


async def test_unbinding_keeps_the_project(client, session, ops):
    created = await client.post(
        _url(ops, "/feedback/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    project_id = created.json()["project_id"]

    response = await client.delete(_url(ops, "/feedback"), headers=ops["seat"].headers)
    assert response.status_code == 204
    assert await intake_service.open_case(IntakeStream.feedback, title="Idea") is None

    await set_rls_context(session, guild_id=ops["guild_id"])
    assert (
        await session.exec(select(Project).where(Project.id == project_id))
    ).one_or_none() is not None


async def test_an_unknown_stream_is_not_a_stream(client, ops):
    response = await client.put(
        _url(ops, "/rumours"), json={"project_id": 1}, headers=ops["seat"].headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "INTAKE_UNKNOWN_STREAM"


async def test_a_status_from_another_project_is_refused(client, session, ops):
    created = await client.post(
        _url(ops, "/support/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    elsewhere_id = await _project_in(session, ops)
    await route_session_to_guild(session, ops["guild_id"])
    await task_statuses_service.ensure_default_statuses(session, elsewhere_id)
    await session.commit()
    foreign = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == elsewhere_id)
        )
    ).first()
    foreign_id = foreign.id
    await set_rls_context(session)

    response = await client.put(
        _url(ops, "/support"),
        json={
            "project_id": created.json()["project_id"],
            "default_status_id": foreign_id,
        },
        headers=ops["seat"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_STATUS_NOT_IN_PROJECT"


async def test_repointing_a_stream_starts_fresh_in_the_new_project(
    client, session, ops
):
    """Cases are keyed by project, so a repeat follows the binding."""
    first = await client.post(
        _url(ops, "/support/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    opened = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert opened is not None

    elsewhere_id = await _project_in(session, ops)
    repointed = await client.put(
        _url(ops, "/support"),
        json={"project_id": elsewhere_id},
        headers=ops["seat"].headers,
    )
    assert repointed.status_code == 200
    assert repointed.json()["project_id"] == elsewhere_id

    again = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert again is not None
    assert again.opened is True
    assert again.task_id != opened.task_id

    await set_rls_context(session, guild_id=ops["guild_id"])
    landed = (await session.exec(select(Task).where(Task.id == again.task_id))).one()
    assert landed.project_id == elsewhere_id
    assert first.json()["project_id"] != elsewhere_id


async def test_rebinding_the_same_project_finds_the_open_case(client, ops):
    """Unbinding keeps the history, so a repeat does not open a second case."""
    created = await client.post(
        _url(ops, "/support/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    project_id = created.json()["project_id"]
    opened = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert opened is not None

    await client.delete(_url(ops, "/support"), headers=ops["seat"].headers)
    rebound = await client.put(
        _url(ops, "/support"),
        json={"project_id": project_id},
        headers=ops["seat"].headers,
    )
    assert rebound.status_code == 200

    again = await intake_service.open_case(
        IntakeStream.support, title="Refused", dedupe_key="refused:42"
    )
    assert again is not None
    assert again.opened is False
    assert again.task_id == opened.task_id


async def test_the_last_case_time_ignores_ordinary_tasks(client, ops):
    """A blueprint's seed task is not a case, and must not read as one."""
    created = await client.post(
        _url(ops, "/feedback/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    assert created.json()["last_case_at"] is None

    await intake_service.open_case(IntakeStream.feedback, title="An idea")
    listed = await client.get(_url(ops), headers=ops["seat"].headers)
    feedback = next(b for b in listed.json()["bindings"] if b["stream"] == "feedback")
    assert feedback["last_case_at"] is not None


async def test_a_stream_cannot_be_bound_to_an_archived_project(client, session, ops):
    """Archived content takes no writes, so a case could never land there."""
    shelved_id = await _project_in(session, ops, archived_at=datetime.now(timezone.utc))
    response = await client.put(
        _url(ops, "/support"),
        json={"project_id": shelved_id},
        headers=ops["seat"].headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "INTAKE_PROJECT_NOT_LIVE"


async def test_a_binding_says_when_its_project_has_been_archived(client, session, ops):
    """Archiving the destination later is a state the page has to show."""
    created = await client.post(
        _url(ops, "/support/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    assert created.json()["project_archived"] is False
    project_id = created.json()["project_id"]

    await set_rls_context(session, guild_id=ops["guild_id"])
    project = (
        await session.exec(select(Project).where(Project.id == project_id))
    ).one()
    project.archived_at = datetime.now(timezone.utc)
    session.add(project)
    await session.commit()
    await set_rls_context(session)

    listed = await client.get(_url(ops), headers=ops["seat"].headers)
    support = next(b for b in listed.json()["bindings"] if b["stream"] == "support")
    assert support["project_archived"] is True
    assert support["project_name"] == "Support"

    # And nothing lands there while it is archived, rather than the database
    # refusing the write.
    assert await intake_service.open_case(IntakeStream.support, title="Help") is None


async def test_a_guild_member_outside_the_initiative_cannot_read_a_case(
    client, session, ops
):
    """Gate 2, unchanged: the bound project's initiative is who reads its cases."""
    await client.post(
        _url(ops, "/security/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )

    await set_rls_context(session)
    outsider = await create_user(session)
    guild = (await session.exec(select(Guild).where(Guild.id == ops["guild_id"]))).one()
    await create_guild_membership(
        session, user=outsider, guild=guild, role=GuildRole.member
    )

    outcome = await intake_service.open_case(
        IntakeStream.security, title="Refused sign-ins"
    )
    assert outcome is not None

    response = await client.get(
        f"/api/v1/g/{ops['guild_id']}/tasks/{outcome.task_id}",
        headers=get_auth_headers(outsider),
    )
    assert response.status_code == 404


# ── Who is refused ──────────────────────────────────────────────────────────


async def test_a_guild_admin_who_is_not_the_seat_is_refused(
    client, session, acting_user, ops
):
    guild = (await session.exec(select(Guild).where(Guild.id == ops["guild_id"]))).one()
    admin = await acting_user(guild_role=GuildRole.admin, guild=guild)
    for method, path, body in (
        ("get", "", None),
        ("get", "/options", None),
        ("put", "/support", {"project_id": 1}),
        ("post", "/support/blueprint", {"initiative_id": ops["initiative_id"]}),
        ("delete", "/support", None),
    ):
        kwargs = {"headers": admin.headers}
        if body is not None:
            kwargs["json"] = body
        response = await getattr(client, method)(_url(ops, path), **kwargs)
        assert response.status_code == 403, (method, path, response.text)
        assert response.json()["detail"] == "GUILD_SUPERADMIN_REQUIRED"


async def test_the_seat_of_another_community_is_refused(client, acting_user, ops):
    other = await acting_user(guild_role=GuildRole.superadmin, initiative=True)
    base = f"/api/v1/g/{other.guild.id}/intake"
    for method, path, body in (
        ("get", "", None),
        ("get", "/options", None),
        ("put", "/support", {"project_id": 1}),
        ("post", "/support/blueprint", {"initiative_id": other.initiative.id}),
        ("delete", "/support", None),
    ):
        kwargs = {"headers": other.headers}
        if body is not None:
            kwargs["json"] = body
        response = await getattr(client, method)(base + path, **kwargs)
        assert response.status_code == 404, (method, path, response.text)
        assert response.json()["detail"] == "INTAKE_NOT_OPERATIONS_GUILD"

    # And it reaches nothing in the operations community either.
    response = await client.get(_url(ops), headers=other.headers)
    assert response.status_code == 403


async def test_a_platform_owner_who_is_not_a_member_is_refused(
    client, acting_user, ops
):
    """Naming the community is the platform's; what is inside it is not."""
    owner = await acting_user("owner")
    assert (await client.get(_url(ops), headers=owner.headers)).status_code == 403
    assert (
        await client.post(
            _url(ops, "/support/blueprint"),
            json={"initiative_id": ops["initiative_id"]},
            headers=owner.headers,
        )
    ).status_code == 403


async def test_nothing_is_offered_before_a_community_is_named(client, session, ops):
    await _point_platform_at(session, None)
    response = await client.get(_url(ops), headers=ops["seat"].headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "INTAKE_NOT_OPERATIONS_GUILD"


async def test_a_read_only_community_takes_no_intake_changes(client, session, ops):
    await set_rls_context(session)
    guild = (await session.exec(select(Guild).where(Guild.id == ops["guild_id"]))).one()
    guild.status = GuildStatus.read_only.value
    session.add(guild)
    await session.commit()

    listed = await client.get(_url(ops), headers=ops["seat"].headers)
    assert listed.status_code == 200, listed.text
    response = await client.post(
        _url(ops, "/support/blueprint"),
        json={"initiative_id": ops["initiative_id"]},
        headers=ops["seat"].headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "INTAKE_WRITE_REQUIRED"
