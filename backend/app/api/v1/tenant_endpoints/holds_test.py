"""Holds: content kept in place for the platform.

A held thing reads as absent to the whole community, its admins and the
moderator who held it included, can't be changed or destroyed by anyone in
it, and comes back only when the platform releases it. Every read here is a
real request through the seam, so the row policies decide, not the code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.api.v1.tenant_endpoints import moderation_test as moderation
from app.core.messages import HoldMessages
from app.db.holds import HoldsInForce, refuse_while_held
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.tenant.comment import Comment
from app.models.tenant.content_hold import ContentHold
from app.models.tenant.intake import IntakeCase
from app.models.tenant.task import Task
from app.services.platform import holds as holds_service
from app.testing import create_comment, create_user
from app.testing.factories import create_access_grant, get_auth_headers

# The moderation suite's fixtures, by name.
scene = moderation.scene
operations = moderation.operations


async def _hold(client, actor, target_type: str, target_id: int, **extra):
    return await client.post(
        actor.g("/holds"),
        json={
            "target_type": target_type,
            "target_id": target_id,
            "reason": "legal_request",
            **extra,
        },
        headers=actor.headers,
    )


async def _thread(client, actor, task_id: int) -> list[dict]:
    response = await client.get(
        actor.g("/comments/"), params={"task_id": task_id}, headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["comments"]


async def _system(session, guild_id: int):
    await set_rls_context(session, SystemGuild(guild_id))


async def _moderator(session, guild, level: str = "moderate"):
    """A platform moderator holding a content grant on ``guild``."""
    user = await create_user(session, role="moderator")
    await create_access_grant(session, user=user, guild=guild, access_level=level)
    return user


# -- Placing ------------------------------------------------------------------


async def test_a_held_comment_reads_as_absent_to_the_whole_community(
    client, session, scene, operations
):
    owner_admin = scene["mod"]
    response = await _hold(client, owner_admin, "comment", scene["comment"].id)
    assert response.status_code == 201, response.text

    # The moderator who held it can't see it either, nor can the author.
    for actor in (scene["mod"], scene["member"]):
        assert scene["comment"].id not in {
            c["id"] for c in await _thread(client, actor, scene["task"].id)
        }

    await _system(session, scene["guild"].id)
    held = (
        await session.exec(select(Comment).where(Comment.id == scene["comment"].id))
    ).one()
    assert held.held_at is not None
    (hold,) = (await session.exec(select(ContentHold))).all()
    assert hold.placed_via == "community"
    assert hold.case_task_id is not None
    await set_rls_context(session, Unattributed())

    # It opened a moderation case in the operations community.
    await _system(session, operations["guild"].id)
    case = (await session.exec(select(IntakeCase))).one()
    assert case.task_id == hold.case_task_id
    assert case.dedupe_key == (
        f"hold:{scene['guild'].id}:comment:{scene['comment'].id}"
    )


async def test_settling_a_report_as_held_hands_it_over_hidden(
    client, session, scene, operations
):
    report_id = await moderation._filed_report_id(
        client, session, scene, reason="illegal", detail="They posted my address."
    )
    settle = f"/api/v1/c/{scene['guild'].id}/reports/{report_id}/settle"

    # A hold goes with ``held``, and only with it.
    for body in (
        {"outcome": "held"},
        {"outcome": "escalated", "hold": {"reason": "legal_request"}},
    ):
        refused = await client.post(settle, json=body, headers=scene["mod"].headers)
        assert refused.status_code == 422

    response = await client.post(
        settle,
        json={
            "outcome": "held",
            "note": "Doxxing.",
            "hold": {
                "reason": "illegal_content",
                "legal_basis": "privacy",
                "note": "Reported to the police, ref 7",
            },
        },
        headers=scene["mod"].headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "held"

    # Gone from the community, the moderator who settled it included.
    assert scene["comment"].id not in {
        c["id"] for c in await _thread(client, scene["mod"], scene["task"].id)
    }

    # One case: the report's, carrying the reporters, with the hold worked on it.
    await _system(session, operations["guild"].id)
    (case,) = (await session.exec(select(IntakeCase))).all()
    assert (
        case.dedupe_key == f"report:{scene['guild'].id}:comment:{scene['comment'].id}"
    )
    task = (await session.exec(select(Task).where(Task.id == case.task_id))).one()
    assert "They posted my address." in (task.description or "")
    await set_rls_context(session, Unattributed())
    await _system(session, scene["guild"].id)
    hold = (await session.exec(select(ContentHold))).one()
    assert hold.case_task_id == case.task_id
    assert hold.reason == "illegal_content"
    assert hold.legal_basis == "privacy"


async def test_a_reply_to_a_held_comment_stays_under_a_placeholder(
    client, session, scene, operations
):
    reply = await create_comment(
        session,
        scene["mod"].user,
        task=scene["task"],
        parent_comment_id=scene["comment"].id,
    )
    await set_rls_context(session, Unattributed())
    assert (
        await _hold(client, scene["mod"], "comment", scene["comment"].id)
    ).status_code == 201

    thread = await _thread(client, scene["member"], scene["task"].id)
    assert [(c["id"], c["parent_comment_id"]) for c in thread] == [
        (reply.id, scene["comment"].id)
    ]


async def test_holding_needs_a_moderator(client, scene, operations):
    response = await _hold(client, scene["member"], "comment", scene["comment"].id)
    assert response.status_code == 403
    assert response.json()["detail"] == HoldMessages.NOT_ALLOWED


async def test_with_nowhere_to_send_it_nothing_is_held(client, session, scene):
    response = await _hold(client, scene["mod"], "comment", scene["comment"].id)
    assert response.status_code == 503
    assert response.json()["detail"] == HoldMessages.NOWHERE_TO_SEND
    assert scene["comment"].id in {
        c["id"] for c in await _thread(client, scene["member"], scene["task"].id)
    }


async def test_illegal_content_names_its_law(client, scene, operations):
    response = await _hold(
        client, scene["mod"], "comment", scene["comment"].id, reason="illegal_content"
    )
    assert response.status_code == 400
    assert response.json()["detail"] == HoldMessages.LEGAL_BASIS_REQUIRED


async def test_what_the_reader_cant_see_cant_be_held(client, scene, operations):
    response = await _hold(client, scene["mod"], "comment", 999_999)
    assert response.status_code == 404


async def test_holding_a_task_holds_its_comments_and_takes_it_out_of_search(
    client, session, scene, operations
):
    task = scene["task"]
    await _system(session, scene["guild"].id)
    indexed = (
        await session.exec(
            text(
                "SELECT count(*) FROM search_entries WHERE entity_type = 'task'"
                " AND entity_id = :id"
            ),
            params={"id": task.id},
        )
    ).scalar()
    assert indexed
    await set_rls_context(session, Unattributed())

    assert (await _hold(client, scene["mod"], "task", task.id)).status_code == 201

    read = await client.get(
        scene["member"].g(f"/tasks/{task.id}"), headers=scene["member"].headers
    )
    assert read.status_code == 404
    await _system(session, scene["guild"].id)
    comment = (
        await session.exec(select(Comment).where(Comment.id == scene["comment"].id))
    ).one()
    assert comment.held_at is not None
    assert (
        await session.exec(
            text(
                "SELECT count(*) FROM search_entries WHERE entity_type = 'task'"
                " AND entity_id = :id"
            ),
            params={"id": task.id},
        )
    ).scalar() == 0


async def test_the_community_cant_change_or_delete_held_content(
    client, session, scene, operations
):
    admin = scene["mod"]
    assert (await _hold(client, admin, "task", scene["task"].id)).status_code == 201
    renamed = await client.patch(
        admin.g(f"/tasks/{scene['task'].id}"),
        json={"title": "x"},
        headers=admin.headers,
    )
    assert renamed.status_code == 404
    deleted = await client.delete(
        admin.g(f"/tasks/{scene['task'].id}"), headers=admin.headers
    )
    assert deleted.status_code == 404


async def test_trashing_what_holds_it_leaves_it_and_purging_waits(
    client, session, acting_user, scene, operations
):
    owner = await acting_user(
        guild_role=CommunityRole.admin,
        guild=scene["guild"],
        initiative=scene["initiative"],
    )
    project_id = scene["task"].project_id
    assert (await _hold(client, owner, "task", scene["task"].id)).status_code == 201

    trashed = await client.delete(
        owner.g(f"/projects/{project_id}"), headers=owner.headers
    )
    assert trashed.status_code in (200, 204), trashed.text
    await _system(session, scene["guild"].id)
    task = (
        await session.exec(
            select(Task)
            .where(Task.id == scene["task"].id)
            .execution_options(include_deleted=True)
        )
    ).one()
    assert task.deleted_at is None and task.held_at is not None
    await set_rls_context(session, Unattributed())

    purged = await client.delete(
        owner.g(f"/trash/project/{project_id}/purge"), headers=owner.headers
    )
    assert purged.status_code == 409


async def test_a_community_whose_content_is_held_is_not_destroyed(
    client, session, scene, operations
):
    assert (
        await _hold(client, scene["mod"], "comment", scene["comment"].id)
    ).status_code == 201
    with pytest.raises(HoldsInForce):
        await refuse_while_held(scene["guild"].id)


# -- The platform -------------------------------------------------------------


async def test_a_moderate_grantee_reads_what_is_held_and_others_dont(
    client, session, scene, operations
):
    assert (
        await _hold(client, scene["mod"], "comment", scene["comment"].id)
    ).status_code == 201
    guild = scene["guild"]
    path = f"/api/v1/c/{guild.id}/comments/"
    params = {"task_id": scene["task"].id}

    moderator = await _moderator(session, guild)
    seen = await client.get(path, params=params, headers=get_auth_headers(moderator))
    assert scene["comment"].id in {c["id"] for c in seen.json()["comments"]}
    holds = await client.get(
        f"/api/v1/c/{guild.id}/holds", headers=get_auth_headers(moderator)
    )
    (listed,) = holds.json()
    assert listed["target_id"] == scene["comment"].id

    for level in ("read", "read_write"):
        other = await _moderator(session, guild, level)
        seen = await client.get(path, params=params, headers=get_auth_headers(other))
        assert scene["comment"].id not in {c["id"] for c in seen.json()["comments"]}
        holds = await client.get(
            f"/api/v1/c/{guild.id}/holds", headers=get_auth_headers(other)
        )
        assert holds.json() == []

    # The community reads none of the platform's record.
    holds = await client.get(scene["mod"].g("/holds"), headers=scene["mod"].headers)
    assert holds.json() == []


@pytest.mark.parametrize("outcome", ["restore", "remove", "purge"])
async def test_the_platform_releases_a_hold(
    client, session, scene, operations, outcome
):
    assert (
        await _hold(client, scene["mod"], "comment", scene["comment"].id)
    ).status_code == 201
    guild = scene["guild"]
    moderator = await _moderator(session, guild)
    (listed,) = (
        await client.get(
            f"/api/v1/c/{guild.id}/holds", headers=get_auth_headers(moderator)
        )
    ).json()

    # The community can't release it.
    refused = await client.post(
        scene["mod"].g(f"/holds/{listed['id']}/release"),
        json={"outcome": outcome},
        headers=scene["mod"].headers,
    )
    assert refused.status_code == 404

    released = await client.post(
        f"/api/v1/c/{guild.id}/holds/{listed['id']}/release",
        json={"outcome": outcome},
        headers=get_auth_headers(moderator),
    )
    assert released.status_code == 200, released.text
    assert released.json()["release_outcome"] == outcome

    thread = {c["id"] for c in await _thread(client, scene["member"], scene["task"].id)}
    assert (scene["comment"].id in thread) is (outcome == "restore")
    await _system(session, guild.id)
    row = (
        await session.exec(
            select(Comment)
            .where(Comment.id == scene["comment"].id)
            .execution_options(include_deleted=True)
        )
    ).first()
    if outcome == "purge":
        assert row is None
    else:
        assert row is not None and row.held_at is None
        assert (row.deleted_at is not None) is (outcome == "remove")


async def test_a_platform_moderator_holds_against_a_case(
    client, session, scene, operations
):
    guild = scene["guild"]
    moderator = await _moderator(session, guild)
    body = {
        "target_type": "comment",
        "target_id": scene["comment"].id,
        "reason": "illegal_content",
        "legal_basis": "privacy",
        "note": "Ref 42/2026",
    }
    unknown = await client.post(
        f"/api/v1/c/{guild.id}/holds",
        json={**body, "case_task_id": 999_999},
        headers=get_auth_headers(moderator),
    )
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == HoldMessages.CASE_NOT_FOUND

    # Without one named, the hold opens its own.
    response = await client.post(
        f"/api/v1/c/{guild.id}/holds", json=body, headers=get_auth_headers(moderator)
    )
    assert response.status_code == 201, response.text
    (listed,) = (
        await client.get(
            f"/api/v1/c/{guild.id}/holds", headers=get_auth_headers(moderator)
        )
    ).json()
    assert listed["placed_via"] == "platform"
    assert listed["case_task_id"] is not None
    assert listed["note"] == "Ref 42/2026"
    assert listed["legal_basis"] == "privacy"

    # Released, it can be held again under the case it was worked on.
    await client.post(
        f"/api/v1/c/{guild.id}/holds/{listed['id']}/release",
        json={"outcome": "restore"},
        headers=get_auth_headers(moderator),
    )
    again = await client.post(
        f"/api/v1/c/{guild.id}/holds",
        json={**body, "case_task_id": listed["case_task_id"]},
        headers=get_auth_headers(moderator),
    )
    assert again.status_code == 201, again.text


async def test_a_hold_standing_30_days_is_noted_on_its_case(
    client, session, scene, operations
):
    assert (
        await _hold(client, scene["mod"], "comment", scene["comment"].id)
    ).status_code == 201
    guild_id = scene["guild"].id
    await _system(session, guild_id)
    hold = (await session.exec(select(ContentHold))).one()
    hold.placed_at = datetime.now(timezone.utc) - timedelta(days=31)
    session.add(hold)
    await session.commit()

    await _system(session, guild_id)
    assert await holds_service.remind_due(session, guild_id) == 1
    await _system(session, guild_id)
    assert await holds_service.remind_due(session, guild_id) == 0

    await _system(session, operations["guild"].id)
    notes = (
        await session.exec(
            select(Comment.system_kind).where(Comment.task_id == hold.case_task_id)
        )
    ).all()
    assert "hold_reminder" in notes
    assert "hold_placed" in notes
