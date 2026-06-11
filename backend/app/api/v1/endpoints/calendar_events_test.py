"""Integration tests for calendar-event tag serialization on the list summary.

The list endpoints return ``CalendarEventSummary``; these assert that tags
assigned to an event are eager-loaded and embedded in the summary (not just
the full ``CalendarEventRead`` detail response).
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.models.notification import Notification, NotificationType
from app.models.tag import Tag
from app.testing import (
    create_calendar_event,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    get_guild_headers,
)


async def _notifications_for(
    session: AsyncSession, user_id: int, ntype: NotificationType
) -> list[Notification]:
    result = await session.exec(
        select(Notification).where(
            Notification.user_id == user_id,
            Notification.type == ntype,
        )
    )
    return list(result.all())


async def _setup_organizer_and_attendee(session: AsyncSession):
    """Events-enabled initiative with an admin organizer and a member attendee."""
    organizer = await create_user(session, email="organizer@example.com")
    attendee = await create_user(session, email="attendee@example.com")
    guild = await create_guild(session)
    await create_guild_membership(
        session, user=organizer, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=attendee, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild, organizer, name="Events")
    initiative.events_enabled = True
    session.add(initiative)
    await create_initiative_member(session, initiative, attendee, role_name="member")
    await session.commit()
    await session.refresh(initiative)
    return organizer, attendee, guild, initiative


async def _setup_event(session: AsyncSession, *, initiative_name: str = "Init"):
    """admin user, guild, events-enabled initiative, event."""
    user = await create_user(session, email=f"u-{initiative_name}@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=user, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, user, name=initiative_name)
    initiative.events_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    event = await create_calendar_event(session, initiative, user, title="E")
    return user, guild, initiative, event


@pytest.mark.integration
async def test_list_events_summary_includes_tags(
    client: AsyncClient, session: AsyncSession
):
    user, guild, initiative, event = await _setup_event(session)
    headers = get_guild_headers(guild, user)

    tag = Tag(name="Priority", guild_id=guild.id, color="#ff0000")
    session.add(tag)
    await session.commit()
    await session.refresh(tag)

    # Assign the tag to the event.
    assign = await client.put(
        f"/api/v1/calendar-events/{event.id}/tags",
        headers=headers,
        json=[tag.id],
    )
    assert assign.status_code == 200

    # The list summary should embed the tag.
    response = await client.get(
        f"/api/v1/calendar-events/?initiative_id={initiative.id}", headers=headers
    )
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert event.id in items
    tags = items[event.id]["tags"]
    assert [t["id"] for t in tags] == [tag.id]
    assert tags[0]["name"] == "Priority"


@pytest.mark.integration
async def test_list_events_summary_tags_default_empty(
    client: AsyncClient, session: AsyncSession
):
    """An event with no tags still serializes ``tags: []`` in the summary."""
    user, guild, initiative, event = await _setup_event(session)
    headers = get_guild_headers(guild, user)

    response = await client.get(
        f"/api/v1/calendar-events/?initiative_id={initiative.id}", headers=headers
    )
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[event.id]["tags"] == []


@pytest.mark.integration
async def test_create_event_notifies_attendees_not_creator(
    client: AsyncClient, session: AsyncSession
):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    headers = get_guild_headers(guild, organizer)

    response = await client.post(
        "/api/v1/calendar-events/",
        headers=headers,
        json={
            "initiative_id": initiative.id,
            "title": "Kickoff",
            "start_at": "2026-07-01T15:00:00Z",
            "end_at": "2026-07-01T16:00:00Z",
            "all_day": False,
            "attendee_ids": [attendee.id],
        },
    )
    assert response.status_code == 201

    invites = await _notifications_for(
        session, attendee.id, NotificationType.event_invitation
    )
    assert len(invites) == 1
    assert invites[0].data["event_title"] == "Kickoff"
    assert invites[0].data["event_id"] == response.json()["id"]
    # The creator should not be notified about their own event.
    assert (
        await _notifications_for(
            session, organizer.id, NotificationType.event_invitation
        )
        == []
    )


@pytest.mark.integration
async def test_create_multi_day_timed_event_is_allowed(
    client: AsyncClient, session: AsyncSession
):
    """A timed (non-all-day) event may now span more than 24 hours / cross days."""
    organizer, _attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    headers = get_guild_headers(guild, organizer)

    response = await client.post(
        "/api/v1/calendar-events/",
        headers=headers,
        json={
            "initiative_id": initiative.id,
            "title": "Conference",
            "start_at": "2026-07-01T14:00:00Z",
            "end_at": "2026-07-03T16:00:00Z",
            "all_day": False,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["start_at"].startswith("2026-07-01")
    assert body["end_at"].startswith("2026-07-03")


@pytest.mark.integration
async def test_create_event_rejects_end_before_start(
    client: AsyncClient, session: AsyncSession
):
    """end_at before start_at is still rejected."""
    organizer, _attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    headers = get_guild_headers(guild, organizer)

    response = await client.post(
        "/api/v1/calendar-events/",
        headers=headers,
        json={
            "initiative_id": initiative.id,
            "title": "Backwards",
            "start_at": "2026-07-03T16:00:00Z",
            "end_at": "2026-07-01T14:00:00Z",
            "all_day": False,
        },
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_update_event_time_notifies_attendees_as_rescheduled(
    client: AsyncClient, session: AsyncSession
):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    headers = get_guild_headers(guild, organizer)
    event = await create_calendar_event(session, initiative, organizer, title="Review")
    await client.put(
        f"/api/v1/calendar-events/{event.id}/attendees",
        headers=headers,
        json=[attendee.id],
    )

    response = await client.patch(
        f"/api/v1/calendar-events/{event.id}",
        headers=headers,
        json={"start_at": "2026-08-01T15:00:00Z", "end_at": "2026-08-01T16:00:00Z"},
    )
    assert response.status_code == 200

    updates = await _notifications_for(
        session, attendee.id, NotificationType.event_updated
    )
    assert len(updates) == 1
    assert updates[0].data["time_changed"] is True


@pytest.mark.integration
async def test_delete_event_notifies_attendees(
    client: AsyncClient, session: AsyncSession
):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    headers = get_guild_headers(guild, organizer)
    event = await create_calendar_event(session, initiative, organizer, title="Retro")
    await client.put(
        f"/api/v1/calendar-events/{event.id}/attendees",
        headers=headers,
        json=[attendee.id],
    )

    response = await client.delete(
        f"/api/v1/calendar-events/{event.id}", headers=headers
    )
    assert response.status_code == 204

    cancels = await _notifications_for(
        session, attendee.id, NotificationType.event_cancelled
    )
    assert len(cancels) == 1


@pytest.mark.integration
async def test_update_event_skips_declined_attendees(
    client: AsyncClient, session: AsyncSession
):
    """An attendee who declined doesn't get reschedule/update notifications."""
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    headers = get_guild_headers(guild, organizer)
    event = await create_calendar_event(session, initiative, organizer, title="Review")
    await client.put(
        f"/api/v1/calendar-events/{event.id}/attendees",
        headers=headers,
        json=[attendee.id],
    )
    declined = await client.patch(
        f"/api/v1/calendar-events/{event.id}/rsvp",
        headers=get_guild_headers(guild, attendee),
        json={"rsvp_status": "declined"},
    )
    assert declined.status_code == 200

    response = await client.patch(
        f"/api/v1/calendar-events/{event.id}",
        headers=headers,
        json={"start_at": "2026-08-01T15:00:00Z", "end_at": "2026-08-01T16:00:00Z"},
    )
    assert response.status_code == 200

    updates = await _notifications_for(
        session, attendee.id, NotificationType.event_updated
    )
    assert updates == []


@pytest.mark.integration
async def test_delete_event_skips_declined_attendees(
    client: AsyncClient, session: AsyncSession
):
    """An attendee who declined doesn't get the cancellation notice."""
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    headers = get_guild_headers(guild, organizer)
    event = await create_calendar_event(session, initiative, organizer, title="Retro")
    await client.put(
        f"/api/v1/calendar-events/{event.id}/attendees",
        headers=headers,
        json=[attendee.id],
    )
    declined = await client.patch(
        f"/api/v1/calendar-events/{event.id}/rsvp",
        headers=get_guild_headers(guild, attendee),
        json={"rsvp_status": "declined"},
    )
    assert declined.status_code == 200

    response = await client.delete(
        f"/api/v1/calendar-events/{event.id}", headers=headers
    )
    assert response.status_code == 204

    cancels = await _notifications_for(
        session, attendee.id, NotificationType.event_cancelled
    )
    assert cancels == []


@pytest.mark.integration
async def test_rsvp_notifies_organizer(client: AsyncClient, session: AsyncSession):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session
    )
    organizer_headers = get_guild_headers(guild, organizer)
    event = await create_calendar_event(session, initiative, organizer, title="Demo")
    await client.put(
        f"/api/v1/calendar-events/{event.id}/attendees",
        headers=organizer_headers,
        json=[attendee.id],
    )

    attendee_headers = get_guild_headers(guild, attendee)
    response = await client.patch(
        f"/api/v1/calendar-events/{event.id}/rsvp",
        headers=attendee_headers,
        json={"rsvp_status": "accepted"},
    )
    assert response.status_code == 200

    rsvps = await _notifications_for(session, organizer.id, NotificationType.event_rsvp)
    assert len(rsvps) == 1
    assert rsvps[0].data["rsvp_status"] == "accepted"
