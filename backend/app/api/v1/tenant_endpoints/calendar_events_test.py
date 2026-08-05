"""Integration tests for calendar-event endpoints.

Events live inside a calendar (the shareable container) and carry no grants of
their own — read/write access is inherited from the parent calendar, the way
tasks inherit project access. These tests cover event creation (which requires
write on the target calendar), the attendee/RSVP notification flows, tag
serialization on the list summary, and the cross-guild ``/me`` calendar list's
DAC filter (which now keys off calendar sharing, not per-event grants).
"""

import pytest
from httpx import AsyncClient
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text

from app.db.schema_provisioning import guild_schema_name
from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.resource_grant import ResourceGrant
from app.testing import (
    create_calendar,
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


async def _enable_calendars(session: AsyncSession, initiative, creator):
    """Turn the calendars tool on and return a calendar owned by ``creator``.

    ``create_calendar`` seeds the creator-owner grant + an all-initiative-members
    read grant, mirroring the create endpoint's default sharing."""
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return await create_calendar(session, initiative, creator)


async def _setup_organizer_and_attendee(session, acting_user):
    """Calendars-enabled initiative with an admin organizer and a member
    attendee, plus a calendar owned by the organizer.

    Returns ``(organizer, attendee, guild, initiative, calendar)`` where
    organizer and attendee are ``Actor`` instances (``.user``/``.headers``)."""
    organizer = await acting_user(guild_role=GuildRole.admin, initiative=True)
    attendee = await acting_user(
        guild_role=GuildRole.member,
        guild=organizer.guild,
        initiative=organizer.initiative,
        initiative_role="member",
    )
    calendar = await _enable_calendars(session, organizer.initiative, organizer.user)
    return organizer, attendee, organizer.guild, organizer.initiative, calendar


async def _setup_event(session, acting_user):
    """admin user, guild, calendars-enabled initiative, calendar, event.

    Returns ``(actor, guild, initiative, calendar, event)``."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    calendar = await _enable_calendars(session, a.initiative, a.user)
    event = await create_calendar_event(session, calendar, a.user, title="E")
    return a, a.guild, a.initiative, calendar, event


@pytest.mark.integration
async def test_list_events_summary_includes_tags(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, guild, initiative, calendar, event = await _setup_event(session, acting_user)

    tag = await create_tag(session, guild, name="Priority", color="#ff0000")

    # Assign the tag to the event (via the generic tool tags route). Events stay
    # taggable even though they are no longer a first-class Tool.
    assign = await client.put(
        a.g(f"/tools/calendar_event/{event.id}/tags"),
        headers=a.headers,
        json={"tag_ids": [tag.id]},
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
    a, guild, initiative, calendar, event = await _setup_event(session, acting_user)

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
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
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
    (
        organizer,
        _attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
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
    (
        organizer,
        _attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    response = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Backwards",
            "start_at": "2026-07-03T16:00:00Z",
            "end_at": "2026-07-01T14:00:00Z",
            "all_day": False,
        },
    )
    assert response.status_code == 422


@pytest.mark.integration
async def test_create_event_requires_calendar_write(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member with only read on the calendar can't create events in it."""
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)

    # The default all-members grant is read-only, so the member attendee has
    # read but not write.
    response = await client.post(
        attendee.g("/calendar-events/"),
        headers=attendee.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Sneaky",
            "start_at": "2026-07-01T15:00:00Z",
            "end_at": "2026-07-01T16:00:00Z",
            "all_day": False,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "CALENDAR_WRITE_ACCESS_REQUIRED"


@pytest.mark.integration
async def test_move_event_between_calendars_requires_write_on_both(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Moving an event to another calendar (PATCH calendar_id) needs write on
    the destination too — a member with read-only there is refused."""
    a, guild, initiative, source, event = await _setup_event(session, acting_user)

    # A second calendar the actor (guild admin) owns → the move succeeds.
    dest = await create_calendar(session, initiative, a.user, name="Dest")
    moved = await client.patch(
        a.g(f"/calendar-events/{event.id}"),
        headers=a.headers,
        json={"calendar_id": dest.id},
    )
    assert moved.status_code == 200
    assert moved.json()["calendar_id"] == dest.id

    # A member with only read on the destination cannot move an event into it.
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=guild,
        initiative=initiative,
        initiative_role="member",
    )
    # Give the member write on the source so the block is clearly the
    # destination gate, not the source.
    grant = await client.put(
        a.g(f"/calendars/{source.id}/grants"),
        headers=a.headers,
        json=[
            {"all_initiative_members": True, "level": "read"},
            {"user_id": member.user.id, "level": "write"},
        ],
    )
    assert grant.status_code == 200
    member_event = await create_calendar_event(session, source, a.user, title="Mine")

    denied = await client.patch(
        member.g(f"/calendar-events/{member_event.id}"),
        headers=member.headers,
        json={"calendar_id": dest.id},
    )
    assert denied.status_code == 403


@pytest.mark.integration
async def test_update_event_time_notifies_attendees_as_rescheduled(
    client: AsyncClient, session: AsyncSession, acting_user
):
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Review"
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
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Retro"
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
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Review"
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
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(
        session, calendar, organizer.user, title="Retro"
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
    (
        organizer,
        attendee,
        guild,
        initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    event = await create_calendar_event(session, calendar, organizer.user, title="Demo")
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
    """The cross-guild /me list must read events from the per-guild schema
    (schema-per-guild), not the frozen public backup. The factory writes the
    event into guild_<id>; /me aggregates per guild and must surface it."""
    a, guild, initiative, calendar, event = await _setup_event(session, acting_user)
    response = await client.get(
        "/api/v1/me/calendar-events", headers=get_auth_headers(a.user)
    )
    assert response.status_code == 200
    body = response.json()
    assert event.id in {item["id"] for item in body["items"]}


@pytest.mark.integration
async def test_my_calendar_events_filters_events_without_calendar_grant(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cross-guild /me list applies the same calendar DAC filter as the
    per-guild list: a non-admin member doesn't see an event in a calendar they
    hold no grant for (even though they're an initiative member and RLS shows
    the row). Events inherit calendar access; they carry no grants of their own."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    guild = admin.guild
    initiative = admin.initiative
    calendar = await _enable_calendars(session, initiative, admin.user)
    event = await create_calendar_event(session, calendar, admin.user, title="NoGrant")

    # Strip the all-initiative-members read grant so the member has no path to
    # this calendar (only the creator-owner grant remains).
    schema = guild_schema_name(guild.id)
    await session.exec(text(f'SET search_path TO "{schema}", public'))
    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == "calendar",
            ResourceGrant.resource_id == calendar.id,
            ResourceGrant.all_initiative_members == True,  # noqa: E712
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
    calendar = await _enable_calendars(session, initiative, other.user)
    event = await create_calendar_event(session, calendar, other.user, title="Foreign")

    resp = await client.get(
        "/api/v1/me/calendar-events", headers=get_auth_headers(admin.user)
    )
    assert resp.status_code == 200
    assert event.id in {item["id"] for item in resp.json()["items"]}
