"""What a community's moderators do to content, and the log they do it in.

Every act here is a real request through the seam, so the row policies decide
who reads what; the log's own reads go through its policy too.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.api.v1.tenant_endpoints import moderation_test as moderation
from app.core.messages import CommentMessages, ModerationMessages
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.comment import Comment
from app.models.tenant.intake import IntakeCase
from app.models.tenant.moderation import ModerationAction, ModerationReport
from app.models.tenant.post import Post
from app.models.tenant.reaction import Reaction
from app.models.tenant.search_entry import SearchEntry
from app.services.tenant.soft_delete import hard_purge_entity
from app.testing import (
    create_comment,
    create_post,
    create_reaction,
    drain_notices,
)

# The moderation suite's fixtures, by name.
scene = moderation.scene
operations = moderation.operations


async def _act(client, actor, act: str, target_type: str, target_id: int, **extra):
    return await client.post(
        actor.g("/moderation/acts"),
        json={"act": act, "target_type": target_type, "target_id": target_id, **extra},
        headers=actor.headers,
    )


async def _thread(client, actor, task_id: int) -> dict:
    response = await client.get(
        actor.g("/comments/"), params={"task_id": task_id}, headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _log(client, actor, initiative_id: int):
    return await client.get(
        actor.g(f"/initiatives/{initiative_id}/moderation/log"), headers=actor.headers
    )


async def _system(session, guild_id: int) -> None:
    await set_rls_context(session, SystemGuild(guild_id))


async def _bell(session, user_id: int, kind: NotificationType) -> list[Notification]:
    await drain_notices()
    await set_rls_context(session, Unattributed())
    return list(
        (
            await session.exec(
                select(Notification)
                .where(Notification.user_id == user_id)
                .where(Notification.type == kind)
            )
        ).all()
    )


# -- Removing a comment ---------------------------------------------------------


async def test_a_removed_comment_is_a_tombstone_and_its_words_are_in_the_log(
    client, session, scene
):
    comment = scene["comment"]
    reply = await create_comment(
        session, scene["mod"].user, task=scene["task"], parent_comment_id=comment.id
    )
    await create_reaction(session, scene["mod"].user, comment=comment)
    await set_rls_context(session, Unattributed())

    removed = await _act(
        client,
        scene["mod"],
        "remove",
        "comment",
        comment.id,
        reason="harassment",
        note="Second time this week.",
    )
    assert removed.status_code == 201, removed.text
    assert removed.json()["action"] == "remove"
    assert removed.json()["restorable"] is True

    # In the thread: where it was, saying who and why, and nothing it said.
    page = await _thread(client, scene["member"], scene["task"].id)
    shown = {c["id"]: c for c in page["comments"]}
    tombstone = shown[comment.id]
    assert tombstone["removed"] == {"by": "moderator", "reason": "harassment"}
    assert tombstone["content"] == ""
    assert tombstone["author"] is None and tombstone["created_by"] is None
    assert tombstone["reactions"] == []
    # The reply is somebody else's words, and stays under it.
    assert shown[reply.id]["parent_comment_id"] == comment.id
    assert shown[reply.id]["removed"] is None

    # The words live in the log alone, read by the moderators.
    await _system(session, scene["guild"].id)
    row = (await session.exec(select(Comment).where(Comment.id == comment.id))).one()
    assert row.content == "" and row.removal_id == removed.json()["id"]
    assert (
        await session.exec(select(Reaction).where(Reaction.target_id == comment.id))
    ).all() == []
    assert (
        await session.exec(
            select(SearchEntry)
            .where(SearchEntry.entity_type == "comment")
            .where(SearchEntry.entity_id == comment.id)
        )
    ).all() == []
    await set_rls_context(session, Unattributed())

    log = await _log(client, scene["mod"], scene["initiative"].id)
    assert log.status_code == 200, log.text
    (entry,) = log.json()["items"]
    assert entry["snapshot"] == "A test comment"
    assert entry["note"] == "Second time this week."
    assert entry["subject"]["id"] == scene["member"].user.id
    assert entry["actor"]["id"] == scene["mod"].user.id

    # The author is told why, and never by whom.
    (notice,) = await _bell(
        session, scene["member"].user.id, NotificationType.moderation_removal
    )
    assert notice.data["reason"] == "harassment"
    assert notice.data["target_type"] == "comment"
    # It opens where the comment was said: its task.
    assert notice.data["target_path"] == f"/go/task/{scene['task'].id}"
    assert "actor_id" not in notice.data or notice.data["actor_id"] is None


async def test_a_tombstone_is_not_edited_reacted_to_or_deleted(client, session, scene):
    comment = scene["comment"]
    removed = await _act(
        client, scene["mod"], "remove", "comment", comment.id, reason="spam"
    )
    assert removed.status_code == 201, removed.text
    member = scene["member"]

    edited = await client.patch(
        member.g(f"/comments/{comment.id}"),
        json={"content": "Back again"},
        headers=member.headers,
    )
    assert edited.status_code == 400
    assert edited.json()["detail"] == CommentMessages.REMOVED

    reacted = await client.put(
        member.g(f"/reactions/comment/{comment.id}"),
        json={"emoji": "\N{THUMBS UP SIGN}"},
        headers=member.headers,
    )
    assert reacted.status_code == 409

    again = await _act(
        client, scene["mod"], "remove", "comment", comment.id, reason="spam"
    )
    assert again.status_code == 409
    assert again.json()["detail"] == ModerationMessages.ALREADY_REMOVED

    # Replying under it is still fine: the conversation goes on.
    replied = await client.post(
        member.g("/comments/"),
        json={
            "content": "Fair enough",
            "task_id": scene["task"].id,
            "parent_comment_id": comment.id,
        },
        headers=member.headers,
    )
    assert replied.status_code == 201, replied.text


async def test_the_database_keeps_a_tombstone_and_the_log_as_they_are(
    client, scene, reading_as
):
    """The guards hold on the request login: for the comment's own author,
    whom the author guard lets write it, and for the community's own
    moderators, whom the row policies would let write the log."""
    removed = await _act(
        client, scene["mod"], "remove", "comment", scene["comment"].id, reason="spam"
    )
    assert removed.status_code == 201, removed.text
    params = {"id": scene["comment"].id, "action": removed.json()["id"]}

    for who, statement in (
        ("member", "UPDATE comments SET content = 'edited' WHERE id = :id"),
        ("mod", "UPDATE moderation_actions SET note = 'edited' WHERE id = :action"),
        ("mod", "DELETE FROM moderation_actions WHERE id = :action"),
    ):
        asking = await reading_as(scene[who].user.id, scene["guild"].id)
        with pytest.raises(Exception) as refused:
            await asking.exec(text(statement), params=params)
        assert "ObjectNotInPrerequisiteState" in str(refused.value), statement
        await asking.rollback()


async def test_restoring_puts_the_words_back_once(client, session, scene):
    comment = scene["comment"]
    removed = await _act(
        client, scene["mod"], "remove", "comment", comment.id, reason="off_topic"
    )
    action_id = removed.json()["id"]

    restored = await client.post(
        scene["mod"].g(f"/moderation/acts/{action_id}/restore"),
        json={"note": "Misread it."},
        headers=scene["mod"].headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["action"] == "restore"

    page = await _thread(client, scene["member"], scene["task"].id)
    (shown,) = page["comments"]
    assert shown["removed"] is None
    assert shown["content"] == "A test comment"
    assert shown["author"]["id"] == scene["member"].user.id

    twice = await client.post(
        scene["mod"].g(f"/moderation/acts/{action_id}/restore"),
        json={},
        headers=scene["mod"].headers,
    )
    assert twice.status_code == 409
    assert twice.json()["detail"] == ModerationMessages.NOT_REMOVED

    log = (await _log(client, scene["mod"], scene["initiative"].id)).json()["items"]
    assert [entry["action"] for entry in log] == ["restore", "remove"]
    assert all(entry["restorable"] is False for entry in log)


async def test_only_the_moderation_set_acts_or_reads_the_log(
    client, session, scene, acting_user
):
    """Full access or community admin; a manager runs the work, and does not
    moderate it."""
    manager = await acting_user(
        guild=scene["guild"],
        initiative=scene["initiative"],
        initiative_role="project_manager",
    )
    for actor in (scene["member"], manager):
        refused = await _act(
            client, actor, "remove", "comment", scene["comment"].id, reason="spam"
        )
        assert refused.status_code == 403, refused.text
        assert refused.json()["detail"] == ModerationMessages.NOT_A_MODERATOR
        assert (await _log(client, actor, scene["initiative"].id)).status_code == 403

    # And a manager's Delete is their own comments' alone now.
    deleted = await client.delete(
        manager.g(f"/comments/{scene['comment'].id}"), headers=manager.headers
    )
    assert deleted.status_code == 403
    assert deleted.json()["detail"] == CommentMessages.AUTHOR_ONLY_DELETE


async def test_a_removal_needs_a_reason_and_a_warning_needs_words(client, scene):
    target = ("comment", scene["comment"].id)
    no_reason = await _act(client, scene["mod"], "remove", *target)
    assert no_reason.status_code == 422
    no_words = await _act(client, scene["mod"], "warn", *target, note="  ")
    assert no_words.status_code == 422
    restore = await _act(client, scene["mod"], "restore", *target)
    assert restore.status_code == 422


# -- Other content ----------------------------------------------------------------


async def test_a_removed_post_goes_to_the_trash_and_comes_back(client, session, scene):
    post = await create_post(session, scene["initiative"], scene["member"].user)
    await set_rls_context(session, Unattributed())

    removed = await _act(
        client, scene["mod"], "remove", "post", post.id, reason="misinformation"
    )
    assert removed.status_code == 201, removed.text

    await _system(session, scene["guild"].id)
    row = (
        await session.exec(
            select(Post)
            .where(Post.id == post.id)
            .execution_options(include_deleted=True, populate_existing=True)
        )
    ).one()
    assert row.deleted_at is not None
    assert row.deleted_by == scene["mod"].user.id
    await set_rls_context(session, Unattributed())

    # The post is gone, so its author is sent to the board it was on.
    (notice,) = await _bell(
        session, scene["member"].user.id, NotificationType.moderation_removal
    )
    assert notice.data["target_path"] == f"/i/{scene['initiative'].id}/posts"

    restored = await client.post(
        scene["mod"].g(f"/moderation/acts/{removed.json()['id']}/restore"),
        json={},
        headers=scene["mod"].headers,
    )
    assert restored.status_code == 200, restored.text
    await _system(session, scene["guild"].id)
    row = (
        await session.exec(
            select(Post)
            .where(Post.id == post.id)
            .execution_options(include_deleted=True, populate_existing=True)
        )
    ).one()
    assert row.deleted_at is None


async def test_a_locked_thread_reads_and_only_moderators_add_to_it(
    client, session, scene
):
    task_id = scene["task"].id
    locked = await _act(client, scene["mod"], "lock_comments", "task", task_id)
    assert locked.status_code == 201, locked.text
    again = await _act(client, scene["mod"], "lock_comments", "task", task_id)
    assert again.json()["detail"] == ModerationMessages.ALREADY_LOCKED

    page = await _thread(client, scene["member"], task_id)
    assert page["locked"] is True and page["can_moderate"] is False
    assert len(page["comments"]) == 1

    body = {"content": "One more thing", "task_id": task_id}
    refused = await client.post(
        scene["member"].g("/comments/"), json=body, headers=scene["member"].headers
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == CommentMessages.LOCKED
    allowed = await client.post(
        scene["mod"].g("/comments/"), json=body, headers=scene["mod"].headers
    )
    assert allowed.status_code == 201, allowed.text

    unlocked = await _act(client, scene["mod"], "unlock_comments", "task", task_id)
    assert unlocked.status_code == 201, unlocked.text
    reopened = await client.post(
        scene["member"].g("/comments/"), json=body, headers=scene["member"].headers
    )
    assert reopened.status_code == 201, reopened.text

    # Only what a thread hangs off takes a lock.
    not_taken = await _act(
        client, scene["mod"], "lock_comments", "comment", scene["comment"].id
    )
    assert not_taken.json()["detail"] == ModerationMessages.ACT_NOT_TAKEN


async def test_clearing_reactions_takes_every_one_off(client, session, scene):
    comment = scene["comment"]
    await create_reaction(session, scene["mod"].user, comment=comment)
    await create_reaction(
        session, scene["member"].user, comment=comment, emoji="\N{HEAVY BLACK HEART}"
    )
    await set_rls_context(session, Unattributed())

    cleared = await _act(client, scene["mod"], "clear_reactions", "comment", comment.id)
    assert cleared.status_code == 201, cleared.text
    (shown,) = (await _thread(client, scene["member"], scene["task"].id))["comments"]
    assert shown["reactions"] == []

    not_taken = await _act(
        client, scene["mod"], "clear_reactions", "task", scene["task"].id
    )
    assert not_taken.json()["detail"] == ModerationMessages.ACT_NOT_TAKEN


async def test_a_warning_reaches_the_author_in_the_moderators_words(
    client, session, scene
):
    warned = await _act(
        client,
        scene["mod"],
        "warn",
        "comment",
        scene["comment"].id,
        note="Keep it civil, please.",
    )
    assert warned.status_code == 201, warned.text
    assert warned.json()["subject"]["id"] == scene["member"].user.id

    (notice,) = await _bell(
        session, scene["member"].user.id, NotificationType.moderation_warning
    )
    assert notice.data["message"] == "Keep it civil, please."
    assert notice.data["target_path"] == f"/go/task/{scene['task'].id}"


# -- An author deleting their own comment ------------------------------------------


async def test_an_author_deleting_a_comment_with_replies_leaves_them_in_place(
    client, session, scene
):
    comment = scene["comment"]
    reply = await create_comment(
        session, scene["mod"].user, task=scene["task"], parent_comment_id=comment.id
    )
    await set_rls_context(session, Unattributed())
    member = scene["member"]

    deleted = await client.delete(
        member.g(f"/comments/{comment.id}"), headers=member.headers
    )
    assert deleted.status_code == 204, deleted.text

    # The same for everyone: those the trash hides it from, and its author
    # and the community's admin, whom the trash lets see it.
    for reader in (scene["mod"], member, scene["admin"]):
        shown = {
            c["id"]: c
            for c in (await _thread(client, reader, scene["task"].id))["comments"]
        }
        assert shown[comment.id]["removed"] == {"by": "author", "reason": None}
        assert shown[comment.id]["content"] == ""
        assert shown[reply.id]["parent_comment_id"] == comment.id

    # The reply is its writer's to change still: nothing above it froze it.
    edited = await client.patch(
        scene["mod"].g(f"/comments/{reply.id}"),
        json={"content": "Edited after"},
        headers=scene["mod"].headers,
    )
    assert edited.status_code == 200, edited.text

    # It is in its author's trash, whole, until the trash lets go of it — and
    # then it stays as a tombstone, for the reply.
    await _system(session, scene["guild"].id)
    row = (
        await session.exec(
            select(Comment)
            .where(Comment.id == comment.id)
            .execution_options(include_deleted=True)
        )
    ).one()
    assert row.deleted_at is not None and row.content == "A test comment"
    await hard_purge_entity(session, row)
    await session.commit()
    row = (
        await session.exec(
            select(Comment)
            .where(Comment.id == comment.id)
            .execution_options(include_deleted=True, populate_existing=True)
        )
    ).one()
    assert row.deleted_at is None and row.removed_at is not None
    assert row.content == "" and row.removal_id is None
    await set_rls_context(session, Unattributed())
    shown = {
        c["id"]: c
        for c in (await _thread(client, scene["mod"], scene["task"].id))["comments"]
    }
    assert shown[comment.id]["removed"] == {"by": "author", "reason": None}


async def test_an_author_deleting_a_lone_comment_trashes_it_as_before(
    client, session, scene
):
    member = scene["member"]
    deleted = await client.delete(
        member.g(f"/comments/{scene['comment'].id}"), headers=member.headers
    )
    assert deleted.status_code == 204, deleted.text
    assert (await _thread(client, member, scene["task"].id))["comments"] == []


# -- Settling a report acts on it --------------------------------------------------


async def test_settling_as_removed_takes_it_down(client, session, scene):
    report_id = await moderation._filed_report_id(client, session, scene)
    settled = await client.post(
        scene["mod"].g(f"/reports/{report_id}/settle"),
        json={"outcome": "content_removed", "note": "Clear spam."},
        headers=scene["mod"].headers,
    )
    assert settled.status_code == 200, settled.text
    assert settled.json()["action_id"] is not None

    (shown,) = (await _thread(client, scene["member"], scene["task"].id))["comments"]
    # For the reason it was reported for, unless the moderator said otherwise.
    assert shown["removed"] == {"by": "moderator", "reason": "spam"}

    (entry,) = (await _log(client, scene["mod"], scene["initiative"].id)).json()[
        "items"
    ]
    assert entry["report_id"] == report_id
    assert entry["id"] == settled.json()["action_id"]


async def test_settling_as_warned_tells_the_author(client, session, scene):
    report_id = await moderation._filed_report_id(client, session, scene)
    url = scene["mod"].g(f"/reports/{report_id}/settle")
    silent = await client.post(
        url, json={"outcome": "member_warned"}, headers=scene["mod"].headers
    )
    assert silent.status_code == 422

    settled = await client.post(
        url,
        json={"outcome": "member_warned", "message": "Please stop posting links."},
        headers=scene["mod"].headers,
    )
    assert settled.status_code == 200, settled.text
    (notice,) = await _bell(
        session, scene["member"].user.id, NotificationType.moderation_warning
    )
    assert notice.data["message"] == "Please stop posting links."
    # Nothing about who reported it, or how many did.
    assert "reporter" not in json.dumps(notice.data)


# -- Reporting something illegal ---------------------------------------------------


async def test_an_illegal_report_names_its_law_and_says_what_is_wrong(client, scene):
    for body, code in (
        ({"reason": "illegal", "detail": "x"}, ModerationMessages.LEGAL_BASIS_REQUIRED),
        (
            {"reason": "illegal", "legal_basis": "privacy"},
            ModerationMessages.DETAIL_REQUIRED,
        ),
        ({"reason": "other"}, ModerationMessages.DETAIL_REQUIRED),
        (
            {"reason": "spam", "legal_basis": "fraud"},
            ModerationMessages.LEGAL_BASIS_NOT_TAKEN,
        ),
    ):
        refused = await moderation._report_comment(client, scene, **body)
        assert refused.status_code == 400, (body, refused.text)
        assert refused.json()["detail"] == code


async def test_an_illegal_report_goes_to_the_community_and_the_platform(
    client, session, scene, operations
):
    filed = await moderation._report_comment(
        client,
        scene,
        reason="illegal",
        legal_basis="privacy",
        detail="They posted my home address.",
    )
    assert filed.status_code == 202, filed.text
    assert filed.json()["venue"] == "initiative"
    assert filed.json()["platform_contact"] is None

    await _system(session, scene["guild"].id)
    report = (await session.exec(select(ModerationReport))).one()
    assert report.legal_basis == "privacy"
    assert report.platform_notified_at is not None
    await _system(session, operations["guild"].id)
    case = (await session.exec(select(IntakeCase))).one()
    assert report.platform_case_id == case.task_id
    # The reporter follows it from their tickets.
    assert case.filer_user_id == scene["member"].user.id
    assert case.dedupe_key == (
        f"report:{scene['guild'].id}:comment:{scene['comment'].id}"
    )
    await set_rls_context(session, Unattributed())

    card = (
        await client.get(moderation._reports_url(scene), headers=scene["mod"].headers)
    ).json()["items"][0]
    assert card["platform_notified_at"] is not None
    assert card["legal_basis"] == "privacy"

    # Settling the community's half notes it on the platform's case.
    settled = await client.post(
        scene["mod"].g(f"/reports/{report.id}/settle"),
        json={"outcome": "dismissed"},
        headers=scene["mod"].headers,
    )
    assert settled.status_code == 200, settled.text
    await _system(session, operations["guild"].id)
    notes = (
        await session.exec(
            select(Comment.system_kind).where(Comment.task_id == case.task_id)
        )
    ).all()
    assert "community_settled" in notes


async def test_without_a_platform_inbox_the_reporter_is_told_who_to_tell(
    client, session, scene
):
    from app.models.platform.app_setting import AppSetting

    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.intake_general_contact = "abuse@example.org"
    session.add(row)
    await session.commit()

    filed = await moderation._report_comment(
        client,
        scene,
        reason="illegal",
        legal_basis="fraud",
        detail="A scam link.",
    )
    assert filed.status_code == 202, filed.text
    assert filed.json()["platform_contact"] == "abuse@example.org"


async def test_a_child_safety_report_carries_no_files_and_asks_for_a_hold(
    client, session, scene, operations
):
    body = {
        "stream": "moderation",
        "target_type": "comment",
        "target_id": scene["comment"].id,
        "reason": "illegal",
        "legal_basis": "child_safety",
        "detail": "In this thread.",
        "community_id": scene["guild"].id,
    }
    with_file = await client.post(
        "/api/v1/me/tickets",
        data={"payload": json.dumps(body)},
        files={
            "files": (
                "where.pdf",
                b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n",
                "application/pdf",
            )
        },
        headers=scene["member"].headers,
    )
    assert with_file.status_code == 400, with_file.text
    assert with_file.json()["detail"] == ModerationMessages.NO_ATTACHMENTS

    filed = await moderation._report_comment(
        client,
        scene,
        reason="illegal",
        legal_basis="child_safety",
        detail="In this thread.",
    )
    assert filed.status_code == 202, filed.text
    await _system(session, operations["guild"].id)
    case = (await session.exec(select(IntakeCase))).one()
    notes = (
        await session.exec(
            select(Comment.system_kind).where(Comment.task_id == case.task_id)
        )
    ).all()
    assert "hold_requested" in notes


async def test_the_log_is_its_initiatives_alone(client, session, scene):
    removed = await _act(
        client, scene["mod"], "remove", "comment", scene["comment"].id, reason="spam"
    )
    assert removed.status_code == 201
    await _system(session, scene["guild"].id)
    (row,) = (await session.exec(select(ModerationAction))).all()
    assert row.initiative_id == scene["initiative"].id
    # Sealed at rest.
    assert row.snapshot and "A test comment" not in row.snapshot


async def test_a_later_illegal_report_makes_the_open_one_illegal(
    client, session, scene, operations
):
    """The gravest reason wins, with the law it names."""
    first = await moderation._report_comment(client, scene, reason="spam")
    assert first.status_code == 202, first.text
    second = await moderation._report(
        client,
        scene["mod"],
        target_type="comment",
        target_id=scene["comment"].id,
        reason="illegal",
        legal_basis="privacy",
        detail="My address.",
        community_id=scene["guild"].id,
    )
    assert second.status_code == 202, second.text

    await _system(session, scene["guild"].id)
    report = (await session.exec(select(ModerationReport))).one()
    assert report.reason == "illegal"
    assert report.legal_basis == "privacy"
    assert report.platform_notified_at is not None


async def test_child_safety_asks_for_a_hold_on_a_case_already_open(
    client, session, scene, operations
):
    """A case another law opened still hears that a hold is needed — once."""
    for actor, basis in (
        (scene["member"], "privacy"),
        (scene["mod"], "child_safety"),
        (scene["member"], "child_safety"),
    ):
        filed = await moderation._report(
            client,
            actor,
            target_type="comment",
            target_id=scene["comment"].id,
            reason="illegal",
            legal_basis=basis,
            detail="Here.",
            community_id=scene["guild"].id,
        )
        assert filed.status_code == 202, filed.text

    await _system(session, operations["guild"].id)
    case = (await session.exec(select(IntakeCase))).one()
    notes = (
        await session.exec(
            select(Comment.system_kind).where(Comment.task_id == case.task_id)
        )
    ).all()
    assert notes.count("hold_requested") == 1


async def test_settling_as_removed_refuses_what_the_platform_holds(
    client, session, scene, operations
):
    """Held is out of sight, not down: closing the report as removed would
    record a removal the hold's end could undo."""
    report_id = await moderation._filed_report_id(client, session, scene)
    held = await client.post(
        scene["mod"].g("/holds"),
        json={
            "target_type": "comment",
            "target_id": scene["comment"].id,
            "reason": "legal_request",
        },
        headers=scene["mod"].headers,
    )
    assert held.status_code == 201, held.text

    settled = await client.post(
        scene["mod"].g(f"/reports/{report_id}/settle"),
        json={"outcome": "content_removed"},
        headers=scene["mod"].headers,
    )
    assert settled.status_code == 409, settled.text
    await _system(session, scene["guild"].id)
    report = (
        await session.exec(
            select(ModerationReport)
            .where(ModerationReport.id == report_id)
            .execution_options(populate_existing=True)
        )
    ).one()
    assert report.outcome is None


async def test_restoring_undoes_only_the_removal_standing_on_it(client, session, scene):
    post = await create_post(session, scene["initiative"], scene["member"].user)
    await set_rls_context(session, Unattributed())
    mod = scene["mod"]

    async def restore(action_id: int):
        return await client.post(
            mod.g(f"/moderation/acts/{action_id}/restore"), json={}, headers=mod.headers
        )

    first = (await _act(client, mod, "remove", "post", post.id, reason="spam")).json()
    assert (await restore(first["id"])).status_code == 200
    second = (await _act(client, mod, "remove", "post", post.id, reason="hate")).json()

    # The first was answered already; the second is the one standing.
    stale = await restore(first["id"])
    assert stale.status_code == 409
    assert stale.json()["detail"] == ModerationMessages.NOT_REMOVED
    assert (await restore(second["id"])).status_code == 200

    # Deleted by its author since: not a moderator's removal to undo.
    third = (await _act(client, mod, "remove", "post", post.id, reason="spam")).json()
    await _system(session, scene["guild"].id)
    row = (
        await session.exec(
            select(Post)
            .where(Post.id == post.id)
            .execution_options(include_deleted=True, populate_existing=True)
        )
    ).one()
    row.deleted_by = scene["member"].user.id
    session.add(row)
    await session.commit()
    await set_rls_context(session, Unattributed())
    assert (await restore(third["id"])).status_code == 409
