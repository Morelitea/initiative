"""Reporting something, who can read the report, and settling it."""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.moderation import ReportOutcome, ReportVenue
from app.core.tools import Tool
from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.core.intake import IntakeStream
from app.models.platform.app_setting import AppSetting
from app.models.tenant.intake import IntakeBinding
from app.models.tenant.moderation import ModerationReport, ModerationReportReporter
from app.models.tenant.task import Task
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_comment,
    create_guild,
    create_initiative,
    create_project,
    create_guild_membership,
    create_initiative_member,
    create_task,
    create_user,
    get_auth_headers,
)

pytestmark = pytest.mark.integration


async def _report(client, actor, **body):
    return await client.post("/api/v1/me/reports", json=body, headers=actor.headers)


@pytest.fixture
async def scene(session, acting_user):
    """A moderator, an ordinary member, and a comment to report.

    The moderator is not the initiative's creator: the standing that opens this
    surface is the role's "Full access" flag, not having made the place.
    """
    owner = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    mod = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="moderator",
    )
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    # Shared with the initiative, which is what makes the comment something an
    # ordinary member can see — and therefore something they can report. A
    # report is only ever about a thing the reporter could reach.
    session.add(
        ResourceGrant(
            guild_id=owner.guild.id,
            resource_type=Tool.project.value,
            resource_id=owner.project.id,
            all_initiative_members=True,
            level=ResourceAccessLevel.write,
        )
    )
    await session.commit()

    task = await create_task(session, owner.project)
    comment = await create_comment(session, member.user, task=task)
    await set_rls_context(session)
    return {
        "guild": owner.guild,
        "initiative": owner.initiative,
        "mod": mod,
        "member": member,
        "task": task,
        "comment": comment,
    }


@pytest.fixture
async def operations(session):
    """A deployment with somewhere for platform reports to go.

    A separate community, as it would be: the operations guild is an ordinary
    one that happens to be pointed at.
    """
    staff = await create_user(session)
    ops_guild = await create_guild(session, creator=staff)
    ops_initiative = await create_initiative(session, ops_guild, staff)
    ops_project = await create_project(session, ops_initiative, staff)

    await set_rls_context(session)
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = ops_guild.id
    session.add(row)
    await session.commit()

    await set_rls_context(session, guild_id=ops_guild.id, guild_role="admin")
    session.add(
        IntakeBinding(stream=IntakeStream.moderation, project_id=ops_project.id)
    )
    await session.commit()
    await set_rls_context(session)
    return {"guild": ops_guild, "project": ops_project}


async def test_reporting_community_content_lands_in_its_initiative(
    client, session, scene
):
    response = await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="harassment",
        detail="This is abusive.",
        guild_id=scene["guild"].id,
    )
    assert response.status_code == 202, response.text
    assert response.json()["venue"] == ReportVenue.initiative.value

    await set_rls_context(session, guild_id=scene["guild"].id, guild_role="admin")
    report = (await session.exec(select(ModerationReport))).one()
    assert report.initiative_id == scene["initiative"].id
    assert report.target_type == "comment"
    assert report.outcome is None


async def test_reporting_identity_goes_to_the_platform(
    client, session, scene, operations
):
    """No community owns a complaint about a username."""
    response = await _report(
        client,
        scene["member"],
        target_type="username",
        target_id=scene["member"].user.id,
        reason="hate",
    )
    assert response.status_code == 202
    assert response.json()["venue"] == ReportVenue.platform.value

    # It landed as an ordinary intake case in the operations community.
    await set_rls_context(session, guild_id=operations["guild"].id, guild_role="admin")
    task = (
        await session.exec(
            select(Task).where(Task.project_id == operations["project"].id)
        )
    ).one()
    assert "username" in task.title


async def test_a_reporter_cannot_read_the_report_they_filed(client, session, scene):
    """Filing gains nothing: reading stays with the initiative's moderators."""
    await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="spam",
        guild_id=scene["guild"].id,
    )
    listed = await client.get(
        f"/api/v1/g/{scene['guild'].id}/initiatives/{scene['initiative'].id}/reports",
        headers=scene["member"].headers,
    )
    assert listed.status_code == 200
    assert listed.json()["items"] == []


async def test_a_moderator_reads_it(client, scene):
    await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="spam",
        detail="Nonsense.",
        guild_id=scene["guild"].id,
    )
    listed = await client.get(
        f"/api/v1/g/{scene['guild'].id}/initiatives/{scene['initiative'].id}/reports",
        headers=scene["mod"].headers,
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["reporter_count"] == 1
    assert items[0]["details"] == ["Nonsense."]
    # Who reported it is deliberately absent from the payload.
    assert "reporter_id" not in items[0]
    assert "reporters" not in items[0]


async def test_a_second_reporter_joins_the_open_report(client, session, scene):
    another = await create_user(session)
    await create_guild_membership(
        session, user=another, guild=scene["guild"], role=GuildRole.member
    )
    await create_initiative_member(
        session, scene["initiative"], another, role_name="member"
    )
    await set_rls_context(session)

    for headers in (scene["member"].headers, get_auth_headers(another)):
        response = await client.post(
            "/api/v1/me/reports",
            json={
                "target_type": "comment",
                "target_id": scene["comment"].id,
                "reason": "spam",
                "guild_id": scene["guild"].id,
            },
            headers=headers,
        )
        assert response.status_code == 202

    listed = await client.get(
        f"/api/v1/g/{scene['guild'].id}/initiatives/{scene['initiative'].id}/reports",
        headers=scene["mod"].headers,
    )
    items = listed.json()["items"]
    assert len(items) == 1, "two people reporting one thing is one thing to decide"
    assert items[0]["reporter_count"] == 2


async def test_the_same_person_reporting_twice_does_not_raise_the_count(client, scene):
    """The count has to mean distinct people, or it means nothing."""
    for _ in range(3):
        await _report(
            client,
            scene["member"],
            target_type="comment",
            target_id=scene["comment"].id,
            reason="spam",
            guild_id=scene["guild"].id,
        )
    listed = await client.get(
        f"/api/v1/g/{scene['guild'].id}/initiatives/{scene['initiative'].id}/reports",
        headers=scene["mod"].headers,
    )
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["reporter_count"] == 1


async def test_a_community_a_reporter_is_not_in_places_nothing_there(
    client, session, scene, operations
):
    """Ids are unique only within a schema, so a named community is checked."""
    outsider = await create_user(session)
    await set_rls_context(session)

    response = await client.post(
        "/api/v1/me/reports",
        json={
            "target_type": "comment",
            "target_id": scene["comment"].id,
            "reason": "spam",
            "guild_id": scene["guild"].id,
        },
        headers=get_auth_headers(outsider),
    )
    # Accepted, and routed to the platform rather than into a community the
    # reporter has no standing in.
    assert response.status_code == 202
    assert response.json()["venue"] == ReportVenue.platform.value

    await set_rls_context(session, guild_id=scene["guild"].id, guild_role="admin")
    assert (await session.exec(select(ModerationReport))).all() == []


async def test_settling_closes_it(client, session, scene):
    await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="spam",
        guild_id=scene["guild"].id,
    )
    await set_rls_context(session, guild_id=scene["guild"].id, guild_role="admin")
    report_id = (await session.exec(select(ModerationReport))).one().id
    await set_rls_context(session)

    response = await client.post(
        f"/api/v1/g/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": ReportOutcome.dismissed.value, "note": "Looked; fine."},
        headers=scene["mod"].headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "dismissed"
    assert body["decided_by"] == scene["mod"].user.id
    assert body["decided_at"] is not None


async def test_a_settled_report_is_not_settled_again(client, session, scene):
    await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="spam",
        guild_id=scene["guild"].id,
    )
    await set_rls_context(session, guild_id=scene["guild"].id, guild_role="admin")
    report_id = (await session.exec(select(ModerationReport))).one().id
    await set_rls_context(session)

    url = f"/api/v1/g/{scene['guild'].id}/reports/{report_id}/settle"
    first = await client.post(
        url, json={"outcome": "dismissed"}, headers=scene["mod"].headers
    )
    assert first.status_code == 200
    second = await client.post(
        url, json={"outcome": "content_removed"}, headers=scene["mod"].headers
    )
    assert second.status_code == 400
    assert second.json()["detail"] == "MODERATION_REPORT_ALREADY_SETTLED"


async def test_an_ordinary_member_cannot_settle(client, session, scene):
    await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="spam",
        guild_id=scene["guild"].id,
    )
    await set_rls_context(session, guild_id=scene["guild"].id, guild_role="admin")
    report_id = (await session.exec(select(ModerationReport))).one().id
    await set_rls_context(session)

    response = await client.post(
        f"/api/v1/g/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": "dismissed"},
        headers=scene["member"].headers,
    )
    # RLS hides the row, so it is not there to settle.
    assert response.status_code == 404


async def test_reporting_something_that_is_not_reportable(client, scene):
    response = await _report(
        client,
        scene["member"],
        target_type="the_vibes",
        target_id=1,
        reason="spam",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "MODERATION_UNKNOWN_TARGET_TYPE"


async def test_reporters_are_recorded_even_though_they_are_not_shown(
    client, session, scene
):
    """Held for dedupe and for an escalation to carry, not for display."""
    await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="spam",
        guild_id=scene["guild"].id,
    )
    await set_rls_context(session, guild_id=scene["guild"].id, guild_role="admin")
    rows = (await session.exec(select(ModerationReportReporter))).all()
    assert [row.reporter_id for row in rows] == [scene["member"].user.id]


async def test_a_report_that_reaches_nobody_is_refused(client, scene):
    """Every install starts with no moderation project bound."""
    response = await _report(
        client,
        scene["member"],
        target_type="username",
        target_id=scene["member"].user.id,
        reason="hate",
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "MODERATION_NOWHERE_TO_SEND"


async def test_an_identity_target_that_does_not_exist_is_refused(client, scene):
    """Checked before it becomes work, so no task names a row that is not there."""
    response = await _report(
        client,
        scene["member"],
        target_type="username",
        target_id=999_999,
        reason="hate",
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "MODERATION_TARGET_NOT_FOUND"


async def test_settling_returns_the_reporters_it_had(client, session, scene):
    """A settled report is the same shape as an open one."""
    await _report(
        client,
        scene["member"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="spam",
        detail="Nonsense.",
        guild_id=scene["guild"].id,
    )
    await set_rls_context(session, guild_id=scene["guild"].id, guild_role="admin")
    report_id = (await session.exec(select(ModerationReport))).one().id
    await set_rls_context(session)

    response = await client.post(
        f"/api/v1/g/{scene['guild'].id}/reports/{report_id}/settle",
        json={"outcome": "dismissed"},
        headers=scene["mod"].headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reporter_count"] == 1
    assert body["details"] == ["Nonsense."]


async def test_the_list_is_paged(client, scene):
    response = await client.get(
        f"/api/v1/g/{scene['guild'].id}/initiatives/{scene['initiative'].id}/reports",
        params={"limit": 1, "offset": 0},
        headers=scene["mod"].headers,
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) <= 1
