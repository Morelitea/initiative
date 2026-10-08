"""Files attached to tickets and reports: sealed where they land, opened only
through their own row, carried sealed when a report is escalated, and gone
once their case has been closed long enough."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.core import blob_crypto
from app.core.messages import EvidenceMessages
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.guild import CommunityRole
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.evidence import Evidence
from app.models.tenant.intake import IntakeCase
from app.services import storage as storage_service
from app.services.platform import evidence as evidence_service
from app.services.platform.evidence_test import picture
from app.api.v1.platform_endpoints import tickets_following_test as following
from app.api.v1.platform_endpoints.tickets_following_test import TICKETS, _file, _move
from app.api.v1.platform_endpoints.tickets_test import _set_support
from app.api.v1.tenant_endpoints import moderation_test as moderation

# The neighbouring suites' fixtures, by name.
desk = following.desk
scene = moderation.scene
operations = moderation.operations


def _jpeg(name: str = "photo.jpg", *, located: bool = False):
    return ("files", (name, picture(located=located), "image/jpeg"))


async def _ask(client, actor, community_id: int, files):
    return await client.post(
        TICKETS,
        data={
            "payload": json.dumps(
                {
                    "stream": "support",
                    "community_id": community_id,
                    "subject": "Lost my phone",
                    "body": "Here is the screen.",
                }
            )
        },
        files=files,
        headers=actor.headers,
    )


async def _evidence(session, guild_id: int) -> list[Evidence]:
    await set_rls_context(session, SystemGuild(guild_id))
    rows = (await session.exec(select(Evidence).order_by(Evidence.id))).all()
    # Ids restart in every community: keep one community's rows from standing
    # in for another's in the identity map.
    session.expunge_all()
    await set_rls_context(session, Unattributed())
    return list(rows)


@pytest.fixture
async def asker(session, acting_user, desk):
    """A member of a community whose members may ask for help."""
    member = await acting_user(guild_role=CommunityRole.member)
    await _set_support(session, member.guild.id, True)
    return member


# -- Filing -------------------------------------------------------------------


async def test_a_filing_stores_its_files_sealed_beside_the_opening_words(
    client,
    session,
    desk,
    asker,
):
    response = await _ask(client, asker, asker.guild.id, [_jpeg(located=True)])
    assert response.status_code == 202, response.text

    (row,) = await _evidence(session, desk["guild_id"])
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    case = (await session.exec(select(IntakeCase))).one()
    opening = (
        await session.exec(
            select(Comment).where(Comment.audience == CommentAudience.filer)
        )
    ).one()
    await set_rls_context(session, Unattributed())
    assert row.case_id == case.id
    assert row.comment_id == opening.id
    assert row.created_by == asker.user.id
    assert row.content_type == "image/jpeg"
    assert row.display_name == "photo.jpg"

    stored = storage_service.get_guild_storage(desk["guild_id"]).open_readable(
        row.storage_key
    )
    sealed = stored.path.read_bytes()
    assert sealed.startswith(b"IEV1")
    assert b"JFIF" not in sealed


async def test_a_file_the_stream_does_not_take_files_nothing(
    client,
    session,
    desk,
    asker,
):
    response = await _ask(
        client,
        asker,
        asker.guild.id,
        [("files", ("photo.png", b"PK\x03\x04" + b"\x00" * 60, "image/png"))],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == EvidenceMessages.TYPE_NOT_ALLOWED
    assert await _evidence(session, desk["guild_id"]) == []
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    assert (await session.exec(select(IntakeCase))).all() == []


async def test_more_files_than_the_stream_takes_are_refused(
    client,
    desk,
    asker,
):
    response = await _ask(
        client, asker, asker.guild.id, [_jpeg(f"{n}.jpg") for n in range(6)]
    )
    assert response.status_code == 400
    assert response.json()["detail"] == EvidenceMessages.TOO_MANY


# -- Reading it back ----------------------------------------------------------


async def test_the_filer_opens_their_own_file_and_nobody_else_can_there(
    client,
    session,
    acting_user,
    desk,
    asker,
):
    assert (
        await _ask(client, asker, asker.guild.id, [_jpeg(located=True)])
    ).status_code == 202
    (row,) = await _evidence(session, desk["guild_id"])
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    case = (await session.exec(select(IntakeCase))).one()
    await set_rls_context(session, Unattributed())

    detail = (
        await client.get(f"{TICKETS}/{case.task_id}", headers=asker.headers)
    ).json()
    (attachment,) = detail["messages"][0]["attachments"]
    assert attachment["id"] == row.id

    url = f"{TICKETS}/{case.task_id}/evidence/{row.id}"
    response = await client.get(url, headers=asker.headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"] == "image/jpeg"
    assert len(response.content) == row.size_bytes

    stranger = await acting_user("member")
    response = await client.get(url, headers=stranger.headers)
    assert response.status_code == 404
    assert response.json()["detail"] == EvidenceMessages.NOT_FOUND


async def test_the_team_opens_a_case_file_and_others_in_the_community_cannot(
    client,
    session,
    acting_user,
    desk,
    asker,
):
    assert (await _ask(client, asker, asker.guild.id, [_jpeg()])).status_code == 202
    (row,) = await _evidence(session, desk["guild_id"])
    staff = desk["staff"]

    response = await client.get(staff.g(f"/evidence/{row.id}"), headers=staff.headers)
    assert response.status_code == 200
    assert response.content.startswith(b"\xff\xd8")

    # In the community, but not in the initiative the case is worked in.
    outsider = await acting_user(guild_role=CommunityRole.member, guild=staff.guild)
    response = await client.get(
        outsider.g(f"/evidence/{row.id}"), headers=outsider.headers
    )
    assert response.status_code == 404


async def test_an_answer_carries_its_files(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)

    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "The screen again."},
        files=[_jpeg("again.jpg")],
        headers=filer.headers,
    )
    assert response.status_code == 201, response.text
    answer = response.json()["messages"][-1]
    assert [a["display_name"] for a in answer["attachments"]] == ["again.jpg"]

    staff = desk["staff"]
    case = (
        await client.get(staff.g(f"/tasks/{task_id}/case"), headers=staff.headers)
    ).json()
    (item,) = case["evidence"]
    assert item["from_requester"] is True
    assert item["comment_id"] == answer["id"]


async def test_an_answer_with_a_refused_file_is_not_taken(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "Look."},
        files=[("files", ("x.exe", b"MZ\x90\x00" + b"\x00" * 60, "image/png"))],
        headers=filer.headers,
    )
    assert response.status_code == 400
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    said = (
        await session.exec(select(Comment.content).where(Comment.task_id == task_id))
    ).all()
    assert "Look." not in said


async def test_a_file_on_someone_elses_case_does_not_open_through_mine(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    other = await acting_user("member")
    mine = await _file(filer.user)
    theirs = await _file(other.user, subject="Theirs")
    response = await client.post(
        f"{TICKETS}/{theirs}/replies",
        data={"body": "Mine."},
        files=[_jpeg()],
        headers=other.headers,
    )
    assert response.status_code == 201
    (row,) = await _evidence(session, desk["guild_id"])

    response = await client.get(
        f"{TICKETS}/{mine}/evidence/{row.id}", headers=filer.headers
    )
    assert response.status_code == 404


# -- Reports, and escalating one ----------------------------------------------


async def test_a_reports_files_are_read_by_its_moderators_and_carried_on_escalation(
    client,
    session,
    scene,
    operations,
):
    community = scene["guild"].id
    response = await client.post(
        "/api/v1/me/tickets",
        data={
            "payload": json.dumps(
                {
                    "stream": "moderation",
                    "target_type": "comment",
                    "target_id": scene["comment"].id,
                    "reason": "harassment",
                    "community_id": community,
                }
            )
        },
        files=[_jpeg("screenshot.jpg")],
        headers=scene["member"].headers,
    )
    assert response.status_code == 202, response.text
    (row,) = await _evidence(session, community)
    assert row.report_id is not None

    mod = scene["mod"]
    reports = (
        await client.get(
            f"/api/v1/c/{community}/initiatives/{scene['initiative'].id}/reports",
            headers=mod.headers,
        )
    ).json()
    assert [e["id"] for e in reports["items"][0]["evidence"]] == [row.id]
    opened = await client.get(mod.g(f"/evidence/{row.id}"), headers=mod.headers)
    assert opened.status_code == 200
    original = opened.content

    settled = await client.post(
        f"/api/v1/c/{community}/reports/{row.report_id}/settle",
        json={"outcome": "escalated"},
        headers=mod.headers,
    )
    assert settled.status_code == 200, settled.text

    (carried,) = await _evidence(session, operations["guild"].id)
    # The same object, keyed for the operations community.
    assert carried.origin_id == row.origin_id
    assert carried.origin_guild_id == community
    assert carried.sha256 == row.sha256
    assert carried.wrapped_dek != row.wrapped_dek
    with pytest.raises(blob_crypto.BlobCryptoError):
        blob_crypto.unwrap(
            carried.wrapped_dek, holding_guild_id=community, origin_id=row.origin_id
        )
    copied = storage_service.get_guild_storage(operations["guild"].id).open_readable(
        carried.storage_key
    )
    kept = storage_service.get_guild_storage(community).open_readable(row.storage_key)
    # Copied as it was stored: never opened on the way.
    assert copied.path.read_bytes() == kept.path.read_bytes()

    await set_rls_context(session, SystemGuild(operations["guild"].id))
    obj = await evidence_service.sealed(session, carried.id)
    await set_rls_context(session, Unattributed())
    assert b"".join(evidence_service.plaintext(operations["guild"].id, obj)) == original


# -- Keeping and rotating -----------------------------------------------------


async def test_a_closed_cases_files_are_kept_for_the_stream_then_go(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "Here."},
        files=[_jpeg()],
        headers=filer.headers,
    )
    await _move(session, desk, task_id, desk["done"])

    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    await evidence_service.purge_due(session, desk["guild_id"])
    (row,) = (await session.exec(select(Evidence))).all()
    assert row.purge_after is not None
    assert row.purge_after > datetime.now(timezone.utc) + timedelta(days=89)
    storage = storage_service.get_guild_storage(desk["guild_id"])
    assert storage.exists(row.storage_key)

    row.purge_after = datetime.now(timezone.utc) - timedelta(minutes=1)
    session.add(row)
    await session.commit()
    assert await evidence_service.purge_due(session, desk["guild_id"]) == 1
    assert (await session.exec(select(Evidence))).all() == []
    assert not storage.exists(row.storage_key)


async def test_a_reopened_case_keeps_its_files(
    client,
    session,
    acting_user,
    desk,
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "Here."},
        files=[_jpeg()],
        headers=filer.headers,
    )
    await _move(session, desk, task_id, desk["done"])
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    await evidence_service.purge_due(session, desk["guild_id"])
    await _move(session, desk, task_id, desk["active"])
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    await evidence_service.purge_due(session, desk["guild_id"])
    (row,) = (await session.exec(select(Evidence))).all()
    assert row.purge_after is None


async def test_rotation_rewraps_the_keys_and_leaves_the_objects(
    client,
    session,
    desk,
    asker,
):
    from app.core.config import settings

    assert (await _ask(client, asker, asker.guild.id, [_jpeg()])).status_code == 202
    (row,) = await _evidence(session, desk["guild_id"])
    storage = storage_service.get_guild_storage(desk["guild_id"])
    before = storage.open_readable(row.storage_key).path.read_bytes()

    new_key = "rotated-" + "z" * 40
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    rotated = await evidence_service.rewrap_guild(
        session,
        desk["guild_id"],
        old_secret_key=settings.SECRET_KEY,
        new_secret_key=new_key,
    )
    await session.commit()
    assert rotated == (1, 0, 0)
    # Again: already under the new key.
    assert await evidence_service.rewrap_guild(
        session,
        desk["guild_id"],
        old_secret_key=settings.SECRET_KEY,
        new_secret_key=new_key,
        dry_run=True,
    ) == (0, 1, 0)

    (after,) = (await session.exec(select(Evidence))).all()
    assert storage.open_readable(row.storage_key).path.read_bytes() == before
    dek = blob_crypto.unwrap(
        after.wrapped_dek,
        holding_guild_id=desk["guild_id"],
        origin_id=after.origin_id,
        secret_key=new_key,
    )
    assert blob_crypto.decrypt(
        before, dek, origin_guild_id=after.origin_guild_id, origin_id=after.origin_id
    ).startswith(b"\xff\xd8")
