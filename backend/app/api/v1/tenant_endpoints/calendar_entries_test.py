"""Integration tests for the calendar-entries aggregate endpoints.

``GET /g/{guild_id}/calendar-entries`` and ``GET /me/calendar-entries`` return a
union of calendar events + task markers over a date window. They must be a union
*under the existing gates* — the same events/tasks the separate list endpoints
would return for the same actor, never more.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.testing import (
    create_calendar_event,
    create_project,
    create_task,
    get_auth_headers,
)
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
WINDOW_START = (NOW - timedelta(days=30)).isoformat()
WINDOW_END = (NOW + timedelta(days=30)).isoformat()


async def _enable_events(session: AsyncSession, initiative) -> None:
    initiative.calendar_events_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


# ---------------------------------------------------------------------------
# Guild endpoint
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_guild_entries_unions_events_and_task_markers(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await _enable_events(session, a.initiative)

    event = await create_calendar_event(
        session, a.initiative, a.user, title="Standup", start_at=NOW
    )
    task = await create_task(
        session, a.project, title="Ship it", due_date=NOW, assignees=[a.user]
    )

    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert {e["id"] for e in body["events"]} == {event.id}
    assert {t["id"] for t in body["tasks"]} == {task.id}


@pytest.mark.integration
async def test_guild_entries_include_flags_skip_legs(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await _enable_events(session, a.initiative)
    await create_calendar_event(session, a.initiative, a.user, start_at=NOW)
    await create_task(session, a.project, due_date=NOW, assignees=[a.user])

    only_tasks = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "include_events": "false"},
    )
    assert only_tasks.status_code == 200
    assert only_tasks.json()["events"] == []
    assert len(only_tasks.json()["tasks"]) == 1

    only_events = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id, "include_tasks": "false"},
    )
    assert only_events.status_code == 200
    assert len(only_events.json()["events"]) == 1
    assert only_events.json()["tasks"] == []


@pytest.mark.integration
async def test_guild_entries_hidden_from_non_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild member who is not in the initiative sees neither its events
    (DAC: no grant) nor its tasks (initiative-member RLS) — the aggregate must
    not widen visibility beyond the per-resource list endpoints."""
    owner = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    await _enable_events(session, owner.initiative)
    event = await create_calendar_event(
        session, owner.initiative, owner.user, start_at=NOW
    )
    task = await create_task(
        session, owner.project, due_date=NOW, assignees=[owner.user]
    )

    # Second guild member, deliberately NOT added to the initiative.
    outsider = await acting_user(guild_role=GuildRole.member, guild=owner.guild)

    response = await client.get(
        outsider.g("/calendar-entries/"),
        headers=outsider.headers,
        params={"start_after": WINDOW_START, "start_before": WINDOW_END},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert event.id not in {e["id"] for e in body["events"]}
    assert task.id not in {t["id"] for t in body["tasks"]}


@pytest.mark.integration
async def test_guild_entries_guild_admin_sees_all(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin sees content of an initiative they are not a member of."""
    member = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    await _enable_events(session, member.initiative)
    event = await create_calendar_event(
        session, member.initiative, member.user, start_at=NOW
    )
    task = await create_task(
        session, member.project, due_date=NOW, assignees=[member.user]
    )

    admin = await acting_user(guild_role=GuildRole.admin, guild=member.guild)

    response = await client.get(
        admin.g("/calendar-entries/"),
        headers=admin.headers,
        params={"start_after": WINDOW_START, "start_before": WINDOW_END},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert event.id in {e["id"] for e in body["events"]}
    assert task.id in {t["id"] for t in body["tasks"]}


@pytest.mark.integration
async def test_guild_entries_windows_tasks_by_params(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """start_after/start_before bound the task leg even when the caller sends no
    matching date filter in `conditions` — the window is a first-class param, so
    an out-of-window task is excluded and the query never runs unbounded."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    in_window = await create_task(
        session, a.project, title="In window", due_date=NOW, assignees=[a.user]
    )
    out_window = await create_task(
        session,
        a.project,
        title="Out of window",
        due_date=NOW + timedelta(days=400),
        assignees=[a.user],
    )

    response = await client.get(
        a.g("/calendar-entries/"),
        headers=a.headers,
        params={
            "initiative_id": a.initiative.id,
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "include_events": "false",
        },
    )
    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["tasks"]}
    assert in_window.id in task_ids
    assert out_window.id not in task_ids


# ---------------------------------------------------------------------------
# Cross-guild /me endpoint
# ---------------------------------------------------------------------------


async def _guild_with_project(session, user, *, name):
    guild = await create_guild(session, creator=user, name=name)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name=f"{name} Init")
    await _enable_events(session, initiative)
    project = await create_project(session, initiative, user, name=f"{name} Project")
    return guild, initiative, project


@pytest.mark.integration
async def test_me_entries_aggregate_across_guilds(
    client: AsyncClient, session: AsyncSession
):
    user = await create_user(session, email="cal-me@example.com")
    g1, i1, p1 = await _guild_with_project(session, user, name="Alpha")
    g2, i2, p2 = await _guild_with_project(session, user, name="Beta")

    event1 = await create_calendar_event(session, i1, user, start_at=NOW)
    event2 = await create_calendar_event(session, i2, user, start_at=NOW)
    task1 = await create_task(session, p1, due_date=NOW, assignees=[user])
    task2 = await create_task(session, p2, due_date=NOW, assignees=[user])

    headers = get_auth_headers(user)
    response = await client.get(
        "/api/v1/me/calendar-entries",
        headers=headers,
        params={"start_after": WINDOW_START, "start_before": WINDOW_END},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    # IDs are per-guild-schema sequences, so a row is only unique as
    # (guild_id, id) once merged across guilds.
    event_keys = {(e["guild_id"], e["id"]) for e in body["events"]}
    task_keys = {(t["guild_id"], t["id"]) for t in body["tasks"]}
    assert {(g1.id, event1.id), (g2.id, event2.id)} <= event_keys
    assert {(g1.id, task1.id), (g2.id, task2.id)} <= task_keys

    # guild_ids narrows to a single guild.
    narrowed = await client.get(
        "/api/v1/me/calendar-entries",
        headers=headers,
        params={
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "guild_ids": [g1.id],
        },
    )
    assert narrowed.status_code == 200, narrowed.text
    nbody = narrowed.json()
    narrowed_event_keys = {(e["guild_id"], e["id"]) for e in nbody["events"]}
    assert (g1.id, event1.id) in narrowed_event_keys
    assert (g2.id, event2.id) not in narrowed_event_keys


@pytest.mark.integration
async def test_me_entries_windows_tasks_by_params(
    client: AsyncClient, session: AsyncSession
):
    """The cross-guild task path applies only extracted scalar filters, so the
    calendar window can only travel as start_after/start_before — assert it
    excludes an out-of-window task rather than returning every assigned task."""
    user = await create_user(session, email="cal-me-window@example.com")
    _g, _i, project = await _guild_with_project(session, user, name="Gamma")

    in_window = await create_task(session, project, due_date=NOW, assignees=[user])
    out_window = await create_task(
        session, project, due_date=NOW + timedelta(days=400), assignees=[user]
    )

    headers = get_auth_headers(user)
    response = await client.get(
        "/api/v1/me/calendar-entries",
        headers=headers,
        params={
            "start_after": WINDOW_START,
            "start_before": WINDOW_END,
            "include_events": "false",
        },
    )
    assert response.status_code == 200, response.text
    task_ids = {t["id"] for t in response.json()["tasks"]}
    assert in_window.id in task_ids
    assert out_window.id not in task_ids
