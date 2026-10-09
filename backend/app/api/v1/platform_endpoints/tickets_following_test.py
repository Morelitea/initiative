"""Following a filed ticket: the filer's list and view, their answers, what the
team says to them, and being told when the case moves.

The filer's routes read through the operations community's filer role, so
every fixture here provisions it the way choosing the community does.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.core.intake import IntakeStream
from app.core.messages import CommentMessages, TaskMessages, TicketMessages
from app.db import filer_access
from app.db.request_context import SystemGuild, Unattributed
from app.db.session import set_rls_context
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import CommunityRole
from app.models.platform.notice_outbox import NoticeOutboxItem
from app.models.platform.notification import NotificationType
from app.models.tenant.comment import Comment, CommentAudience
from app.models.tenant.intake import IntakeBinding, IntakeCase
from app.models.tenant.task import Task, TaskAssignee, TaskStatus, TaskStatusCategory
from app.services.platform.intake import CaseFiler, open_case
from app.services.platform.ticket_notices import notify_filers
from app.services.tenant import task_statuses as task_statuses_service

TICKETS = "/api/v1/me/tickets"


async def _statuses(session, project_id: int) -> dict[TaskStatusCategory, int]:
    rows = (
        await session.exec(
            select(TaskStatus).where(TaskStatus.project_id == project_id)
        )
    ).all()
    by_category: dict[TaskStatusCategory, int] = {}
    for row in sorted(rows, key=lambda r: r.position):
        by_category.setdefault(TaskStatusCategory(row.category), int(row.id))
    return by_category


@pytest.fixture
async def desk(session, acting_user):
    """An operations community whose staff work support and feedback, with
    each stream's "waiting on you" and "being worked" statuses named."""
    staff = await acting_user(
        guild_role=CommunityRole.admin, initiative=True, project=True
    )
    guild_id = staff.guild.id
    project_id = staff.project.id

    await set_rls_context(session, Unattributed())
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        row = AppSetting(id=1)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()

    await set_rls_context(session, SystemGuild(guild_id))
    await task_statuses_service.ensure_default_statuses(session, project_id)
    statuses = await _statuses(session, project_id)
    awaiting = TaskStatus(
        project_id=project_id,
        name="Waiting on requester",
        category=TaskStatusCategory.in_progress,
        position=99,
    )
    session.add(awaiting)
    await session.flush()
    for stream in (IntakeStream.support, IntakeStream.feedback):
        session.add(
            IntakeBinding(
                stream=stream,
                project_id=project_id,
                awaiting_filer_status_id=awaiting.id,
                active_status_id=statuses[TaskStatusCategory.in_progress],
            )
        )
    await session.commit()
    await set_rls_context(session, Unattributed())
    await filer_access.provision_filer_access(guild_id)

    yield {
        "staff": staff,
        "guild_id": guild_id,
        "project_id": project_id,
        "awaiting": int(awaiting.id),
        "active": statuses[TaskStatusCategory.in_progress],
        "done": statuses[TaskStatusCategory.done],
    }
    # Dropping the policies waits on every open reader of those tables.
    await session.rollback()
    await filer_access.deprovision_filer_access(guild_id)


async def _file(user, stream=IntakeStream.support, subject="Lost my phone") -> int:
    outcome = await open_case(
        stream,
        title=f"Staff title for {subject}",
        filer=CaseFiler(user_id=user.id, subject=subject, words="Help."),
    )
    assert outcome is not None
    return outcome.task_id


async def _say(client, desk, task_id: int, content: str, audience="filer"):
    staff = desk["staff"]
    return await client.post(
        staff.g("/comments/"),
        json={"content": content, "task_id": task_id, "audience": audience},
        headers=staff.headers,
    )


async def _move(session, desk, task_id: int, status_id: int) -> None:
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    task.task_status_id = status_id
    session.add(task)
    await session.commit()
    await set_rls_context(session, Unattributed())


async def _notices(session, user_id: int) -> list[dict]:
    await set_rls_context(session, Unattributed())
    rows = (
        await session.exec(
            select(NoticeOutboxItem)
            .where(NoticeOutboxItem.user_id == user_id)
            .where(NoticeOutboxItem.type == NotificationType.ticket_updated.value)
            .order_by(NoticeOutboxItem.id)
        )
    ).all()
    return [row.data for row in rows]


# ── The filer's view ─────────────────────────────────────────────────────────


async def test_a_filer_lists_their_own_tickets_and_nobody_elses(
    client, acting_user, desk
):
    filer = await acting_user("member")
    other = await acting_user("member")
    mine = await _file(filer.user)
    await _file(other.user, subject="Not yours")

    response = await client.get(TICKETS, headers=filer.headers)
    assert response.status_code == 200, response.text
    (ticket,) = response.json()["items"]
    assert ticket["task_id"] == mine
    assert ticket["subject"] == "Lost my phone"
    assert ticket["state"] == "received"


async def test_with_nothing_filed_the_list_is_empty(client, acting_user, desk):
    filer = await acting_user("member")
    response = await client.get(TICKETS, headers=filer.headers)
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_a_filer_reads_what_is_said_to_them_and_not_the_staff_notes(
    client, acting_user, desk
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    assert (
        await _say(client, desk, task_id, "Internal.", "members")
    ).status_code == 201
    assert (
        await _say(client, desk, task_id, "Try a recovery code.")
    ).status_code == 201

    response = await client.get(f"{TICKETS}/{task_id}", headers=filer.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert [(m["mine"], m["content"]) for m in body["messages"]] == [
        (True, "Help."),
        (False, "Try a recovery code."),
    ]
    assert body["conversation"] == "open"
    assert body["can_reply"] is True


async def test_someone_elses_ticket_reads_as_missing(client, acting_user, desk):
    filer = await acting_user("member")
    other = await acting_user("member")
    theirs = await _file(other.user)

    for response in (
        await client.get(f"{TICKETS}/{theirs}", headers=filer.headers),
        await client.post(
            f"{TICKETS}/{theirs}/replies", data={"body": "Hi"}, headers=filer.headers
        ),
    ):
        assert response.status_code == 404
        assert response.json()["detail"] == TicketMessages.NOT_FOUND


async def test_answering_a_case_that_waits_on_you_moves_it_back(
    client, session, acting_user, desk
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await _move(session, desk, task_id, desk["awaiting"])

    listed = (await client.get(TICKETS, headers=filer.headers)).json()["items"]
    assert listed[0]["state"] == "waiting_on_you"

    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "It was in my other bag."},
        headers=filer.headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "in_progress"
    assert body["messages"][-1] == {
        **body["messages"][-1],
        "mine": True,
        "content": "It was in my other bag.",
    }

    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    assert task.task_status_id == desk["active"]
    reply = (
        await session.exec(
            select(Comment)
            .where(Comment.task_id == task_id)
            .order_by(Comment.id.desc())
        )
    ).first()
    assert reply.created_by == filer.user.id
    assert reply.audience == CommentAudience.filer


async def test_a_closed_case_takes_no_answer(client, session, acting_user, desk):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await _move(session, desk, task_id, desk["done"])

    detail = (await client.get(f"{TICKETS}/{task_id}", headers=filer.headers)).json()
    assert detail["state"] == "closed"
    assert detail["can_reply"] is False
    response = await client.post(
        f"{TICKETS}/{task_id}/replies", data={"body": "Hello?"}, headers=filer.headers
    )
    assert response.status_code == 409
    assert response.json()["detail"] == TicketMessages.REPLY_NOT_TAKEN


async def test_feedback_waits_for_the_team_to_speak_first(client, acting_user, desk):
    filer = await acting_user("member")
    task_id = await _file(filer.user, IntakeStream.feedback, subject="Dark mode")

    detail = (await client.get(f"{TICKETS}/{task_id}", headers=filer.headers)).json()
    assert detail["conversation"] == "staff_first"
    assert detail["can_reply"] is False
    refused = await client.post(
        f"{TICKETS}/{task_id}/replies", data={"body": "Also..."}, headers=filer.headers
    )
    assert refused.status_code == 409

    assert (await _say(client, desk, task_id, "Which screens?")).status_code == 201
    detail = (await client.get(f"{TICKETS}/{task_id}", headers=filer.headers)).json()
    assert detail["can_reply"] is True


# ── The team's side ──────────────────────────────────────────────────────────


async def test_staff_read_how_a_case_was_filed(client, acting_user, desk):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    staff = desk["staff"]

    response = await client.get(
        staff.g(f"/tasks/{task_id}/case"), headers=staff.headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["stream"] == "support"
    assert body["filer"]["id"] == filer.user.id
    assert body["filer_subject"] == "Lost my phone"
    assert body["conversation"] == "open"
    assert body["awaiting_filer_status_id"] == desk["awaiting"]
    assert body["active_status_id"] == desk["active"]


async def test_the_case_carries_the_conversation_apart_from_the_thread(
    client, acting_user, desk
):
    """What is said with the requester is read on the case, oldest first, and
    the task's own thread and its count carry only what the team said among
    themselves."""
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    staff = desk["staff"]
    assert (
        await _say(client, desk, task_id, "Internal.", "members")
    ).status_code == 201
    assert (
        await _say(client, desk, task_id, "Try a recovery code.")
    ).status_code == 201

    case = (
        await client.get(staff.g(f"/tasks/{task_id}/case"), headers=staff.headers)
    ).json()
    assert [
        (m["from_requester"], m["content"], m["author"]["id"]) for m in case["messages"]
    ] == [
        (True, "Help.", filer.user.id),
        (False, "Try a recovery code.", staff.user.id),
    ]

    thread = await client.get(
        staff.g("/comments/"), headers=staff.headers, params={"task_id": task_id}
    )
    assert thread.status_code == 200, thread.text
    assert [c["content"] for c in thread.json()["comments"]] == ["Internal."]

    task = (
        await client.get(staff.g(f"/tasks/{task_id}"), headers=staff.headers)
    ).json()
    assert task["comment_count"] == 1


async def test_an_ordinary_task_is_not_a_case(client, desk):
    staff = desk["staff"]
    created = await client.post(
        staff.g("/tasks/"),
        json={"title": "Plain", "project_id": desk["project_id"]},
        headers=staff.headers,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    response = await client.get(
        staff.g(f"/tasks/{task_id}/case"), headers=staff.headers
    )
    assert response.status_code == 404
    assert response.json()["detail"] == TaskMessages.NOT_A_CASE

    said = await _say(client, desk, task_id, "To nobody.")
    assert said.status_code == 400
    assert said.json()["detail"] == CommentMessages.NOT_SAID_TO_A_FILER


async def test_a_case_nobody_filed_takes_nothing_said_to_a_filer(client, desk):
    outcome = await open_case(IntakeStream.support, title="Claimed claim values")
    assert outcome is not None

    said = await _say(client, desk, outcome.task_id, "To nobody.")
    assert said.status_code == 400
    assert said.json()["detail"] == CommentMessages.NOT_SAID_TO_A_FILER


async def test_what_is_said_to_the_filer_is_marked_so(client, acting_user, desk):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    said = await _say(client, desk, task_id, "On it.")
    assert said.status_code == 201, said.text
    assert said.json()["audience"] == "filer"


async def _assign(session, desk, task_id: int, user_id: int) -> None:
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    session.add(TaskAssignee(task_id=task_id, user_id=user_id))
    await session.commit()
    await set_rls_context(session, Unattributed())


async def _comment_notices(session, user_id: int) -> list[dict]:
    await set_rls_context(session, Unattributed())
    rows = (
        await session.exec(
            select(NoticeOutboxItem)
            .where(NoticeOutboxItem.user_id == user_id)
            .where(NoticeOutboxItem.type == NotificationType.comment_on_task.value)
        )
    ).all()
    return [row.data for row in rows]


async def test_the_cases_assignees_hear_when_the_filer_answers(
    client, session, acting_user, desk
):
    """An answer from whoever filed the case reaches the people working it,
    as any comment on the task would."""
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await _assign(session, desk, task_id, desk["staff"].user.id)

    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "It was in my other bag."},
        headers=filer.headers,
    )
    assert response.status_code == 201, response.text

    (told,) = await _comment_notices(session, desk["staff"].user.id)
    assert told["task_id"] == task_id
    assert told["commenter_id"] == filer.user.id
    assert await _comment_notices(session, filer.user.id) == []


async def test_an_unassigned_case_tells_nobody_of_the_answer(
    client, session, acting_user, desk
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)

    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "Anyone there?"},
        headers=filer.headers,
    )
    assert response.status_code == 201, response.text
    assert await _comment_notices(session, desk["staff"].user.id) == []


@pytest.fixture
def bus_off(monkeypatch):
    """Only this worker's sockets: the cross-process half is additive."""

    async def _unavailable(_channel: str, _payload: str) -> None:
        raise RuntimeError("bus not connected")

    from app.services.platform import notify_bus

    monkeypatch.setattr(notify_bus, "notify", _unavailable)


def _ticket_frames(tab) -> list[dict]:
    return [frame for frame in tab.sent if frame.get("resource") == "tickets"]


async def test_an_open_ticket_hears_when_the_conversation_moves(
    client, acting_user, desk, account_socket, bus_off
):
    """The requester's own socket says their tickets changed when the team
    answers them, and says nothing for what the team says among themselves.
    The frame names nothing; the page reads the ticket again."""
    from app.testing.sockets import settle

    filer = await acting_user("member")
    task_id = await _file(filer.user)
    tab = account_socket(filer.user.id)

    assert (
        await _say(client, desk, task_id, "Internal.", "members")
    ).status_code == 201
    await settle()
    assert _ticket_frames(tab) == []

    assert (
        await _say(client, desk, task_id, "Try a recovery code.")
    ).status_code == 201
    await settle()
    (frame,) = _ticket_frames(tab)
    assert frame["ids"] == {}
    assert "recovery" not in str(frame)


async def test_the_requesters_other_tabs_hear_their_own_answer(
    client, acting_user, desk, account_socket, bus_off
):
    from app.testing.sockets import settle

    filer = await acting_user("member")
    task_id = await _file(filer.user)
    tab = account_socket(filer.user.id)

    response = await client.post(
        f"{TICKETS}/{task_id}/replies",
        data={"body": "It was in my other bag."},
        headers=filer.headers,
    )
    assert response.status_code == 201, response.text
    await settle()
    assert len(_ticket_frames(tab)) == 1


# ── Being told ───────────────────────────────────────────────────────────────


async def test_a_filer_is_told_when_their_case_moves_and_only_then(
    client, session, acting_user, desk
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)

    # The first pass records where the case starts; they filed it and know.
    await notify_filers()
    assert await _notices(session, filer.user.id) == []

    assert (
        await _say(client, desk, task_id, "Try a recovery code.")
    ).status_code == 201
    await _move(session, desk, task_id, desk["awaiting"])
    await notify_filers()
    (told,) = await _notices(session, filer.user.id)
    assert told["task_id"] == task_id
    assert told["state"] == "waiting_on_you"
    assert told["replied"] is True
    assert told["subject"] == "Lost my phone"
    assert told["target_path"] == f"/my-tickets/{task_id}"
    assert "Try a recovery code." not in str(told)

    # Nothing moved since: nothing more to say.
    await notify_filers()
    assert len(await _notices(session, filer.user.id)) == 1

    await _move(session, desk, task_id, desk["done"])
    await notify_filers()
    notices = await _notices(session, filer.user.id)
    assert [n["state"] for n in notices] == ["waiting_on_you", "closed"]
    assert notices[-1]["replied"] is False


async def test_a_filer_is_not_told_about_their_own_answer_or_staff_notes(
    client, session, acting_user, desk
):
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await notify_filers()

    assert (
        await _say(client, desk, task_id, "Internal.", "members")
    ).status_code == 201
    await notify_filers()
    assert await _notices(session, filer.user.id) == []

    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    case = (
        await session.exec(select(IntakeCase).where(IntakeCase.task_id == task_id))
    ).one()
    assert case.filer_notified_state == "received"


async def test_an_open_ticket_hears_when_the_case_moves(
    client, session, acting_user, desk, account_socket, bus_off
):
    """A status change is the team's own write; the sweep that notices it is
    what tells the requester's socket."""
    from app.testing.sockets import settle

    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await notify_filers()
    tab = account_socket(filer.user.id)

    await _move(session, desk, task_id, desk["awaiting"])
    await notify_filers()
    await settle()
    assert len(_ticket_frames(tab)) == 1

    await notify_filers()
    await settle()
    assert len(_ticket_frames(tab)) == 1


async def test_a_move_before_the_first_sweep_is_still_news(session, acting_user, desk):
    """A filed case records where it starts, so a move made before the sweep
    first sees it is told like any other."""
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await _move(session, desk, task_id, desk["awaiting"])

    await notify_filers()
    (told,) = await _notices(session, filer.user.id)
    assert told["state"] == "waiting_on_you"


async def test_an_answer_to_a_case_closed_since_it_was_read_is_refused(
    session, acting_user, desk
):
    """The page said it took an answer; the case closed before it was sent.
    The answer is refused and the case stays closed."""
    from app.services.platform import tickets as tickets_service

    filer = await acting_user("member")
    task_id = await _file(filer.user)
    await _move(session, desk, task_id, desk["awaiting"])
    detail = await tickets_service.read_filed(filer.user, task_id)
    assert detail.can_reply
    await _move(session, desk, task_id, desk["done"])

    with pytest.raises(tickets_service.ReplyRefused):
        await tickets_service.reply(filer.user, detail, "Still there?")

    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    task = (await session.exec(select(Task).where(Task.id == task_id))).one()
    assert task.task_status_id == desk["done"]
    said = (
        await session.exec(select(Comment.content).where(Comment.task_id == task_id))
    ).all()
    assert "Still there?" not in said


async def test_an_answer_lands_only_on_the_filers_own_case(session, acting_user, desk):
    """The writer reads the case again rather than trusting the id it was
    handed: a task that is not this person's case takes nothing."""
    from app.services.platform.intake import add_filer_reply

    filer = await acting_user("member")
    other = await acting_user("member")
    theirs = await _file(other.user, subject="Not yours")

    taken = await add_filer_reply(
        guild_id=desk["guild_id"],
        task_id=theirs,
        filer=filer.user,
        words="Hello",
        stream=IntakeStream.support,
    )
    assert taken is False
    await set_rls_context(session, SystemGuild(desk["guild_id"]))
    said = (
        await session.exec(select(Comment.content).where(Comment.task_id == theirs))
    ).all()
    assert "Hello" not in said


async def test_a_reply_keeps_the_audience_of_what_it_answers(client, acting_user, desk):
    """A note among the team cannot hang under something said to the
    requester, where neither the thread nor the conversation would show it."""
    filer = await acting_user("member")
    task_id = await _file(filer.user)
    said = await _say(client, desk, task_id, "Try a recovery code.")
    staff = desk["staff"]

    response = await client.post(
        staff.g("/comments/"),
        json={
            "content": "Internal aside.",
            "task_id": task_id,
            "parent_comment_id": said.json()["id"],
        },
        headers=staff.headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == CommentMessages.AUDIENCE_MISMATCH
