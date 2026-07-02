"""Integration tests for calendar-event tag serialization on the list summary.

The list endpoints return ``CalendarEventSummary``; these assert that tags
assigned to an event are eager-loaded and embedded in the summary (not just
the full ``CalendarEventRead`` detail response).
"""

import pytest
from httpx import AsyncClient
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text

from app.db.schema_provisioning import guild_schema_name
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.resource_grant import ResourceGrant
from app.testing import (
    create_calendar_event,
    create_tag,
    get_auth_headers,
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


async def _enable_events(session: AsyncSession, initiative):
    """Toggle the events feature flag on and persist it."""
    initiative.events_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _setup_organizer_and_attendee(session, acting_user):
    """Events-enabled initiative with an admin organizer and a member attendee.

    Returns ``(organizer, attendee, guild, initiative)`` where organizer and
    attendee are ``Actor`` instances (``.user``/``.headers``)."""
    organizer = await acting_user(guild_role=GuildRole.admin, initiative=True)
    attendee = await acting_user(
        guild_role=GuildRole.member,
        guild=organizer.guild,
        initiative=organizer.initiative,
        initiative_role="member",
    )
    await _enable_events(session, organizer.initiative)
    return organizer, attendee, organizer.guild, organizer.initiative


async def _setup_event(session, acting_user):
    """admin user, guild, events-enabled initiative, event.

    Returns ``(actor, guild, initiative, event)``."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_events(session, a.initiative)
    event = await create_calendar_event(session, a.initiative, a.user, title="E")
    return a, a.guild, a.initiative, event


@pytest.mark.integration
async def test_list_events_summary_includes_tags(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, guild, initiative, event = await _setup_event(session, acting_user)

    tag = await create_tag(session, guild, name="Priority", color="#ff0000")

    # Assign the tag to the event.
    assign = await client.put(
        a.g(f"/calendar-events/{event.id}/tags"),
        headers=a.headers,
        json=[tag.id],
    )
    assert assign.status_code == 200

    # The list summary should embed the tag.
    response = await client.get(
        a.g(f"/calendar-events/?initiative_id={initiative.id}"),
        headers=a.headers,
    )
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert event.id in items
    tags = items[event.id]["tags"]
    assert [t["id"] for t in tags] == [tag.id]
    assert tags[0]["name"] == "Priority"


@pytest.mark.integration
async def test_list_events_summary_tags_default_empty(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An event with no tags still serializes ``tags: []`` in the summary."""
    a, guild, initiative, event = await _setup_event(session, acting_user)

    response = await client.get(
        a.g(f"/calendar-events/?initiative_id={initiative.id}"),
        headers=a.headers,
    )
    assert response.status_code == 200
    items = {item["id"]: item for item in response.json()["items"]}
    assert items[event.id]["tags"] == []


@pytest.mark.integration
async def test_create_event_notifies_attendees_not_creator(
    client: AsyncClient, session: AsyncSession, acting_user
):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "initiative_id": initiative.id,
            "title": "Kickoff",
            "start_at": "2026-07-01T15:00:00Z",
            "end_at": "2026-07-01T16:00:00Z",
            "all_day": False,
            "attendee_ids": [attendee.user.id],
        },
    )
    assert response.status_code == 201

    invites = await _notifications_for(
        session, attendee.user.id, NotificationType.event_invitation
    )
    assert len(invites) == 1
    assert invites[0].data["event_title"] == "Kickoff"
    assert invites[0].data["event_id"] == response.json()["id"]
    # The creator should not be notified about their own event.
    assert (
        await _notifications_for(
            session, organizer.user.id, NotificationType.event_invitation
        )
        == []
    )


@pytest.mark.integration
async def test_create_multi_day_timed_event_is_allowed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A timed (non-all-day) event may now span more than 24 hours / cross days."""
    organizer, _attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
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
    client: AsyncClient, session: AsyncSession, acting_user
):
    """end_at before start_at is still rejected."""
    organizer, _attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
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
    client: AsyncClient, session: AsyncSession, acting_user
):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )
    event = await create_calendar_event(
        session, initiative, organizer.user, title="Review"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )

    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}"),
        headers=organizer.headers,
        json={"start_at": "2026-08-01T15:00:00Z", "end_at": "2026-08-01T16:00:00Z"},
    )
    assert response.status_code == 200

    updates = await _notifications_for(
        session, attendee.user.id, NotificationType.event_updated
    )
    assert len(updates) == 1
    assert updates[0].data["time_changed"] is True


@pytest.mark.integration
async def test_delete_event_notifies_attendees(
    client: AsyncClient, session: AsyncSession, acting_user
):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )
    event = await create_calendar_event(
        session, initiative, organizer.user, title="Retro"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )

    response = await client.delete(
        organizer.g(f"/calendar-events/{event.id}"), headers=organizer.headers
    )
    assert response.status_code == 204

    cancels = await _notifications_for(
        session, attendee.user.id, NotificationType.event_cancelled
    )
    assert len(cancels) == 1


@pytest.mark.integration
async def test_update_event_skips_declined_attendees(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An attendee who declined doesn't get reschedule/update notifications."""
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )
    event = await create_calendar_event(
        session, initiative, organizer.user, title="Review"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )
    declined = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "declined"},
    )
    assert declined.status_code == 200

    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}"),
        headers=organizer.headers,
        json={"start_at": "2026-08-01T15:00:00Z", "end_at": "2026-08-01T16:00:00Z"},
    )
    assert response.status_code == 200

    updates = await _notifications_for(
        session, attendee.user.id, NotificationType.event_updated
    )
    assert updates == []


@pytest.mark.integration
async def test_delete_event_skips_declined_attendees(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """An attendee who declined doesn't get the cancellation notice."""
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )
    event = await create_calendar_event(
        session, initiative, organizer.user, title="Retro"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )
    declined = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "declined"},
    )
    assert declined.status_code == 200

    response = await client.delete(
        organizer.g(f"/calendar-events/{event.id}"), headers=organizer.headers
    )
    assert response.status_code == 204

    cancels = await _notifications_for(
        session, attendee.user.id, NotificationType.event_cancelled
    )
    assert cancels == []


@pytest.mark.integration
async def test_rsvp_notifies_organizer(
    client: AsyncClient, session: AsyncSession, acting_user
):
    organizer, attendee, guild, initiative = await _setup_organizer_and_attendee(
        session, acting_user
    )
    event = await create_calendar_event(
        session, initiative, organizer.user, title="Demo"
    )
    await client.put(
        organizer.g(f"/calendar-events/{event.id}/attendees"),
        headers=organizer.headers,
        json=[attendee.user.id],
    )

    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "accepted"},
    )
    assert response.status_code == 200

    rsvps = await _notifications_for(
        session, organizer.user.id, NotificationType.event_rsvp
    )
    assert len(rsvps) == 1
    assert rsvps[0].data["rsvp_status"] == "accepted"


@pytest.mark.integration
async def test_global_calendar_events_reads_guild_schema(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cross-guild /global list must read events from the per-guild schema
    (schema-per-guild), not the frozen public backup. The factory writes the
    event into guild_<id>; /global aggregates per guild and must surface it."""
    a, guild, initiative, event = await _setup_event(session, acting_user)
    response = await client.get(
        "/api/v1/me/calendar-events", headers=get_auth_headers(a.user)
    )
    assert response.status_code == 200
    body = response.json()
    assert event.id in {item["id"] for item in body["items"]}


@pytest.mark.integration
async def test_my_calendar_events_filters_events_without_member_grant(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cross-guild /me list applies the same per-event DAC filter as the
    per-guild list: a non-admin member doesn't see an event they hold no grant
    for (even though they're an initiative member and RLS shows the row)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    guild = admin.guild
    initiative = admin.initiative
    await _enable_events(session, initiative)
    event = await create_calendar_event(
        session, initiative, admin.user, title="NoGrant"
    )

    # Strip the member-role grant so the member has no path to this event.
    schema = guild_schema_name(guild.id)
    member_role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    ).one()
    await session.exec(text(f'SET search_path TO "{schema}", public'))
    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == "calendar_event",
            ResourceGrant.resource_id == event.id,
            ResourceGrant.role_id == member_role.id,
        )
    )
    await session.exec(text("SET search_path TO public"))
    await session.commit()

    # Member: the ungranted event is hidden on /me.
    resp = await client.get(
        "/api/v1/me/calendar-events", headers=get_auth_headers(member.user)
    )
    assert resp.status_code == 200
    assert event.id not in {item["id"] for item in resp.json()["items"]}

    # Admin: sees it via the guild-admin bypass.
    resp = await client.get(
        "/api/v1/me/calendar-events", headers=get_auth_headers(admin.user)
    )
    assert resp.status_code == 200
    assert event.id in {item["id"] for item in resp.json()["items"]}


@pytest.mark.integration
async def test_my_calendar_events_admin_sees_events_outside_their_initiatives(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin sees events in initiatives they were never added to (the
    admin leg of initiative_access fires under their guild role). The /me DAC
    filter must not re-hide them."""
    admin = await acting_user(guild_role=GuildRole.admin)
    # `other` owns the initiative; the admin is NOT a member of it.
    other = await acting_user(
        guild_role=GuildRole.member, guild=admin.guild, initiative=True
    )
    initiative = other.initiative
    await _enable_events(session, initiative)
    event = await create_calendar_event(
        session, initiative, other.user, title="Foreign"
    )

    resp = await client.get(
        "/api/v1/me/calendar-events", headers=get_auth_headers(admin.user)
    )
    assert resp.status_code == 200
    assert event.id in {item["id"] for item in resp.json()["items"]}
