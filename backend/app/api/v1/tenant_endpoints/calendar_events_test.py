"""Integration tests for calendar-event endpoints.

Events live inside a calendar (the shareable container) and carry no grants of
their own — read/write access is inherited from the parent calendar, the way
tasks inherit project access. These tests cover event creation (which requires
write on the target calendar), the attendee/RSVP notification flows, tag
serialization on the list summary, and the cross-guild ``/me`` calendar list's
DAC filter (which now keys off calendar sharing, not per-event grants).
"""

from datetime import datetime, timezone

from httpx import AsyncClient
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import text

from app.db.schema_provisioning import guild_schema_name
from app.core.messages import CalendarEventMessages, CommonMessages
from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.resource_grant import ResourceGrant
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_document,
    create_guild_calendar,
    create_property_definition,
    create_tag,
    get_auth_headers,
    route_session_to_guild,
)


async def _drop_all_members_grant(session: AsyncSession, guild, calendar) -> None:
    """Strip the all-initiative-members read grant, leaving only the creator's
    owner grant — a calendar shared with nobody else."""
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


async def test_list_events_summary_includes_tags(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, guild, initiative, calendar, event = await _setup_event(session, acting_user)

    tag = await create_tag(session, guild, name="Priority", color="#ff0000")

    # Events are content-level extras (like tasks), not tools, so their tags
    # are set by the event's own PATCH rather than the generic /tools route.
    assign = await client.patch(
        a.g(f"/calendar-events/{event.id}"),
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
    # The line carries the reference, not the title: the bell reads the
    # title back from the calendar when it renders.
    assert "event_title" not in invites[0].data
    assert invites[0].data["event_id"] == response.json()["id"]
    # The creator should not be notified about their own event.
    assert (
        await _notifications_for(
            session, organizer.user.id, NotificationType.event_invitation
        )
        == []
    )


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


async def test_one_occurrence_changes_alone(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Mondays at 09:00 UTC from 5 October. One occurrence is moved and
    renamed, and still follows the series where it didn't change; one is
    skipped and brought back; an attendee who can't edit the calendar declines
    one; and the series is renamed from a later one on, then deleted."""
    (
        organizer,
        attendee,
        _guild,
        _initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    created = await client.post(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        json={
            "calendar_id": calendar.id,
            "title": "Standup",
            "start_at": "2026-10-05T09:00:00Z",
            "end_at": "2026-10-05T09:30:00Z",
            "recurrence": "FREQ=WEEKLY;BYDAY=MO",
            "attendee_ids": [attendee.user.id],
        },
    )
    assert created.status_code == 201, created.text
    series = created.json()["id"]
    second, third, fourth = (
        "2026-10-12T09:00:00Z",
        "2026-10-19T09:00:00Z",
        "2026-10-26T09:00:00Z",
    )

    def at(path: str) -> str:
        return organizer.g(f"/calendar-events/{series}{path}")

    async def month() -> list[tuple[str, str, str | None]]:
        entries = await client.get(
            organizer.g("/calendar-entries/"),
            headers=organizer.headers,
            params={
                "start_after": "2026-10-01T00:00:00Z",
                "start_before": "2026-11-01T00:00:00Z",
                "include_tasks": "false",
            },
        )
        assert entries.status_code == 200, entries.text
        return [
            (e["title"], e["start_at"], e["location"]) for e in entries.json()["events"]
        ]

    moved = await client.patch(
        at(""),
        headers=organizer.headers,
        json={
            "scope": "this",
            "occurrence": second,
            "title": "Standup (moved)",
            "start_at": "2026-10-12T10:00:00Z",
            "end_at": "2026-10-12T10:30:00Z",
        },
    )
    assert moved.status_code == 200, moved.text
    assert (
        moved.json()["series_id"],
        moved.json()["original_start"],
        moved.json()["overridden_fields"],
    ) == (series, second, ["all_day", "end_at", "start_at", "title"])
    override = moved.json()["id"]
    # A change to the series reaches the occurrence where it didn't change,
    # and saving it again with that value doesn't make the value its own.
    await client.patch(at(""), headers=organizer.headers, json={"location": "Room 2"})
    resaved = await client.patch(
        organizer.g(f"/calendar-events/{override}"),
        headers=organizer.headers,
        json={"title": "Standup (moved)", "location": "Room 2"},
    )
    assert resaved.json()["overridden_fields"] == [
        "all_day",
        "end_at",
        "start_at",
        "title",
    ]
    assert await month() == [
        ("Standup", "2026-10-05T09:00:00Z", "Room 2"),
        ("Standup (moved)", "2026-10-12T10:00:00Z", "Room 2"),
        ("Standup", third, "Room 2"),
        ("Standup", fourth, "Room 2"),
    ]

    # Deleting the moved one skips it, and tells its attendees; bringing it
    # back brings back what it changed.
    skipped = await client.delete(
        organizer.g(f"/calendar-events/{override}"), headers=organizer.headers
    )
    assert skipped.status_code == 204
    read = await client.get(at(""), headers=organizer.headers)
    assert read.json()["skipped_starts"] == [second]
    cancels = await _notifications_for(
        session, attendee.user.id, NotificationType.event_cancelled
    )
    assert [notice.data["start_at"] for notice in cancels] == [
        "2026-10-12T09:00:00+00:00"
    ]
    restored = await client.post(
        at("/occurrences/restore"), headers=organizer.headers, json={"start": second}
    )
    assert restored.json()["skipped_starts"] == []
    assert "Standup (moved)" in [title for title, _start, _location in await month()]

    # Answering takes read access, so one occurrence's answer needs no row.
    declined = await client.patch(
        attendee.g(f"/calendar-events/{series}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "declined", "occurrence": fourth},
    )
    assert declined.status_code == 200, declined.text
    # An answer is for one event, so a repeating one names its occurrence.
    unnamed = await client.patch(
        attendee.g(f"/calendar-events/{series}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "accepted"},
    )
    assert unnamed.json()["detail"] == "CALENDAR_EVENT_OCCURRENCE_REQUIRED"

    async def answer(event_id: int, occurrence: str | None = None) -> str:
        read = await client.get(
            organizer.g(f"/calendar-events/{event_id}"),
            headers=organizer.headers,
            params={"occurrence": occurrence} if occurrence else {},
        )
        return read.json()["attendees"][0]["rsvp_status"]

    assert (await answer(series, fourth), await answer(series)) == (
        "declined",
        "pending",
    )
    # One with a row of its own is answered, and read back, on that row.
    await client.patch(
        attendee.g(f"/calendar-events/{series}/rsvp"),
        headers=attendee.headers,
        json={"rsvp_status": "tentative", "occurrence": second},
    )
    assert (await answer(series, second), await answer(override)) == (
        "tentative",
        "tentative",
    )

    retro = await client.patch(
        at(""),
        headers=organizer.headers,
        json={"scope": "following", "occurrence": fourth, "title": "Retro"},
    )
    assert retro.status_code == 200, retro.text
    rest = retro.json()["id"]
    assert rest != series
    assert (await client.get(at(""), headers=organizer.headers)).json()[
        "recurrence"
    ] == "RRULE:FREQ=WEEKLY;UNTIL=20261026T085959Z;BYDAY=MO"
    assert [title for title, _start, _location in await month()] == [
        "Standup",
        "Standup (moved)",
        "Standup",
        "Retro",
    ]
    # The answer went with its occurrence.
    assert await answer(rest, fourth) == "declined"

    deleted = await client.delete(
        at(""), headers=organizer.headers, params={"scope": "all"}
    )
    assert deleted.status_code == 204
    assert [title for title, _start, _location in await month()] == ["Retro"]


async def test_an_event_repeat_is_stored_as_picked(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A repeat is stored as picked, with the shift from the zone it was picked
    in and the latest start it can have; an all-day event's days are UTC dates,
    so its shift is none. The repeat moves with a start that moves, and an
    all-day event is found by its date."""
    (
        organizer,
        _attendee,
        guild,
        _initiative,
        calendar,
    ) = await _setup_organizer_and_attendee(session, acting_user)
    created = {}
    for title, extra, rule in (
        # Mondays at 00:30 in Berlin, which are Sundays in UTC.
        (
            "Standup",
            {"start_at": "2026-10-04T22:30:00Z"},
            "FREQ=WEEKLY;BYDAY=MO;COUNT=3",
        ),
        (
            "Market day",
            {"start_at": "2026-10-05T00:00:00Z", "all_day": True},
            "FREQ=WEEKLY;BYDAY=MO;COUNT=3",
        ),
    ):
        response = await client.post(
            organizer.g("/calendar-events/"),
            headers=organizer.headers,
            json={
                "calendar_id": calendar.id,
                "title": title,
                "end_at": "2026-10-05T23:59:59Z",
                "recurrence": rule,
                "tz": "Europe/Berlin",
                **extra,
            },
        )
        assert response.status_code == 201
        created[title] = response.json()
    weekly = "RRULE:FREQ=WEEKLY;COUNT=3;BYDAY=MO"
    assert {
        title: (event["recurrence"], event["recurrence_shift"])
        for title, event in created.items()
    } == {"Standup": (weekly, 1440), "Market day": (weekly, 0)}

    await route_session_to_guild(session, guild.id)
    standup = await session.get(CalendarEvent, created["Standup"]["id"])
    assert standup is not None
    assert standup.recurrence_until == datetime(
        2026, 10, 18, 22, 30, tzinfo=timezone.utc
    )

    # Moved to noon, still Mondays in Berlin, and now Mondays in UTC too.
    moved = await client.patch(
        organizer.g(f"/calendar-events/{created['Standup']['id']}"),
        headers=organizer.headers,
        json={
            "start_at": "2026-10-05T10:00:00Z",
            "end_at": "2026-10-05T11:00:00Z",
            "tz": "Europe/Berlin",
        },
    )
    assert (moved.json()["recurrence"], moved.json()["recurrence_shift"]) == (
        weekly,
        0,
    )

    # Monday asked for from Los Angeles begins after the all-day event's UTC
    # midnight, and from Auckland it ends before noon UTC; either way the event
    # is Monday's.
    listing = await client.get(
        organizer.g("/calendar-events/"),
        headers=organizer.headers,
        params={
            "start_after": "2026-10-05T07:00:00Z",
            "start_before": "2026-10-06T06:59:59Z",
        },
    )
    assert "Market day" in {event["title"] for event in listing.json()["items"]}
    entries = await client.get(
        organizer.g("/calendar-entries/"),
        headers=organizer.headers,
        params={
            "start_after": "2026-10-04T11:00:00Z",
            "start_before": "2026-10-05T10:59:59Z",
            "tz": "Pacific/Auckland",
            "include_events": True,
            "include_tasks": False,
        },
    )
    assert "Market day" in {event["title"] for event in entries.json()["events"]}


async def test_create_event_rejects_end_before_start(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """end_at before start_at is still rejected, on create and on an update
    that moves only one end."""
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

    event = await create_calendar_event(session, calendar, organizer.user)
    response = await client.patch(
        organizer.g(f"/calendar-events/{event.id}"),
        headers=organizer.headers,
        json={"end_at": "2000-01-01T00:00:00Z"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == CalendarEventMessages.ENDS_BEFORE_START


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


async def test_global_calendar_events_reads_guild_schema(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The cross-guild /me list must read events from the per-guild schema
    (schema-per-guild). The factory writes the event into guild_<id>; /me
    aggregates per guild and must surface it."""
    a, guild, initiative, calendar, event = await _setup_event(session, acting_user)
    headers = get_auth_headers(a.user)
    response = await client.get("/api/v1/me/calendar-events", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert event.id in {item["id"] for item in body["items"]}


async def test_list_events_filters_events_without_calendar_grant(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The per-guild list resolves an event through its calendar's sharing.

    Events carry no grants of their own, so calendar sharing is what decides.
    ``calendar_ids`` narrows the result; it is not how access is resolved.
    """
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    calendar = await _enable_calendars(session, admin.initiative, admin.user)
    event = await create_calendar_event(session, calendar, admin.user, title="NoGrant")
    await _drop_all_members_grant(session, admin.guild, calendar)

    path = admin.g("/calendar-events/")
    resp = await client.get(path, headers=get_auth_headers(member.user))
    assert resp.status_code == 200
    assert event.id not in {item["id"] for item in resp.json()["items"]}

    # Naming the calendar narrows the result; it does not change the answer.
    resp = await client.get(
        path,
        params={"calendar_ids": [calendar.id]},
        headers=get_auth_headers(member.user),
    )
    assert resp.status_code == 200
    assert resp.json()["items"] == []

    # The admin reaches it, as they do every calendar in their guild.
    resp = await client.get(path, headers=get_auth_headers(admin.user))
    assert resp.status_code == 200
    assert event.id in {item["id"] for item in resp.json()["items"]}


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

    await _drop_all_members_grant(session, guild, calendar)

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


async def test_my_calendar_events_leaves_out_what_was_never_shared(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin's own calendar is what has been shared with them.

    The /me aggregate spans initiatives, so it answers what reaches the reader
    rather than what their standing could reach — an admin's authority over the
    initiative is untouched, and asking for it by name still returns the event.
    """
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
    assert event.id not in {item["id"] for item in resp.json()["items"]}

    # Named directly, the initiative answers in full — this moved navigation,
    # not authority.
    within = await client.get(
        f"/api/v1/c/{admin.guild.id}/calendar-events/?initiative_id={initiative.id}",
        headers=get_auth_headers(admin.user),
    )
    assert within.status_code == 200, within.text
    assert event.id in {item["id"] for item in within.json()["items"]}


async def _switch_calendars_on(session: AsyncSession, initiative) -> None:
    """Switch the calendar tool on for an initiative, without creating one.

    Off by default — and a guild calendar answers to this switch not at all,
    which is part of what the tests below check."""
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


class TestGuildCalendarEvents:
    """A guild calendar holds its own events and reaches into no initiative.

    Two questions, and they pull in opposite directions. Its events have to be
    *visible* — the app's page and a member's own calendar are where they show,
    and until now every one of those queries required an initiative, so they
    showed nowhere at all. And its events must stay *out* of anything belonging
    to an initiative, which is the same NULL read the other way.

    The rest is what an event borrows from an initiative — its member list, its
    property definitions. A guild calendar has no initiative to borrow from, so
    those refuse rather than resolve to something else.
    """

    async def test_events_are_listed(self, client: AsyncClient, acting_user, session):
        a = await acting_user(guild_role=GuildRole.admin)
        calendar = await create_guild_calendar(session, a.guild, a.user)
        await create_calendar_event(session, calendar, a.user, title="Club night")

        response = await client.get(a.g("/calendar-events/"), headers=a.headers)
        assert response.status_code == 200, response.text
        assert [e["title"] for e in response.json()["items"]] == ["Club night"]

    async def test_a_member_in_no_initiative_sees_them(
        self, client: AsyncClient, acting_user, session
    ):
        """The point of the app: someone in none of the guild's initiatives
        still has the guild's own calendar."""
        a = await acting_user(guild_role=GuildRole.admin)
        calendar = await create_guild_calendar(session, a.guild, a.user)
        await create_calendar_event(session, calendar, a.user, title="Club night")
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)

        response = await client.get(
            member.g("/calendar-events/"), headers=member.headers
        )
        assert response.status_code == 200, response.text
        assert [e["title"] for e in response.json()["items"]] == ["Club night"]

    async def test_they_stay_out_of_an_initiative(
        self, client: AsyncClient, acting_user, session
    ):
        """Asked for one initiative's events, a guild calendar has nothing to
        contribute — it belongs to no initiative."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await _switch_calendars_on(session, a.initiative)
        guild_calendar = await create_guild_calendar(session, a.guild, a.user)
        await create_calendar_event(session, guild_calendar, a.user, title="Club night")
        own = await create_calendar(session, a.initiative, a.user)
        await create_calendar_event(session, own, a.user, title="Sprint review")

        response = await client.get(
            a.g("/calendar-events/"),
            headers=a.headers,
            params={"initiative_id": a.initiative.id},
        )
        assert response.status_code == 200, response.text
        assert [e["title"] for e in response.json()["items"]] == ["Sprint review"]

    async def test_the_calendar_is_listed_but_not_under_an_initiative(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await _switch_calendars_on(session, a.initiative)
        await create_guild_calendar(session, a.guild, a.user, name="Community calendar")
        await create_calendar(session, a.initiative, a.user, name="Team calendar")

        every = await client.get(a.g("/calendars/"), headers=a.headers)
        assert sorted(c["name"] for c in every.json()["items"]) == [
            "Community calendar",
            "Team calendar",
        ]

        scoped = await client.get(
            a.g("/calendars/"),
            headers=a.headers,
            params={"initiative_id": a.initiative.id},
        )
        assert [c["name"] for c in scoped.json()["items"]] == ["Team calendar"]

    async def test_anyone_in_the_guild_can_attend(
        self, client: AsyncClient, acting_user, session
    ):
        """An initiative calendar draws attendees from its initiative; a guild
        calendar has none, so the guild is who can attend — including a member
        who belongs to no initiative at all."""
        a = await acting_user(guild_role=GuildRole.admin)
        member = await acting_user(guild_role=GuildRole.member, guild=a.guild)
        calendar = await create_guild_calendar(session, a.guild, a.user)

        response = await client.post(
            a.g("/calendar-events/"),
            headers=a.headers,
            json={
                "calendar_id": calendar.id,
                "title": "Club night",
                "start_at": "2026-09-01T18:00:00Z",
                "end_at": "2026-09-01T20:00:00Z",
                "attendee_ids": [member.user.id],
            },
        )
        assert response.status_code == 201, response.text
        assert [at["user"]["id"] for at in response.json()["attendees"]] == [
            member.user.id
        ]

    async def test_someone_outside_the_guild_cannot_attend(
        self, client: AsyncClient, acting_user, session
    ):
        a = await acting_user(guild_role=GuildRole.admin)
        stranger = await acting_user(guild_role=GuildRole.admin)
        calendar = await create_guild_calendar(session, a.guild, a.user)

        response = await client.post(
            a.g("/calendar-events/"),
            headers=a.headers,
            json={
                "calendar_id": calendar.id,
                "title": "Club night",
                "start_at": "2026-09-01T18:00:00Z",
                "end_at": "2026-09-01T20:00:00Z",
                "attendee_ids": [stranger.user.id],
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == CommonMessages.PERSON_CANNOT_READ

    async def test_properties_are_refused(
        self, client: AsyncClient, acting_user, session
    ):
        """Property definitions belong to an initiative too."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        definition = await create_property_definition(session, a.initiative)
        calendar = await create_guild_calendar(session, a.guild, a.user)
        event = await create_calendar_event(session, calendar, a.user)

        response = await client.put(
            a.g(f"/calendar-events/{event.id}/properties"),
            headers=a.headers,
            json={"values": [{"property_id": definition.id, "value": "anything"}]},
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == CalendarEventMessages.GUILD_CALENDAR_NO_PROPERTIES
        )

    async def test_documents_cannot_be_linked(
        self, client: AsyncClient, acting_user, session
    ):
        """Documents belong to an initiative; a guild calendar holds guild-level
        content only, so an event there cannot link one."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        document = await create_document(session, a.initiative, a.user)
        calendar = await create_guild_calendar(session, a.guild, a.user)

        # Asked of the create path, which is where an event names its documents
        # now that the per-tool attach route is one generic one. The generic
        # surface refuses the same pairing — see ``relationships_test``.
        response = await client.post(
            a.g("/calendar-events/"),
            headers=a.headers,
            json={
                "title": "Guild night",
                "calendar_id": calendar.id,
                "start_at": "2026-10-01T18:00:00Z",
                "end_at": "2026-10-01T20:00:00Z",
                "document_ids": [document.id],
            },
        )
        assert response.status_code == 400
        assert (
            response.json()["detail"]
            == CalendarEventMessages.GUILD_CALENDAR_NO_DOCUMENTS
        )

    async def test_an_event_cannot_move_across_the_scope_line(
        self, client: AsyncClient, acting_user, session
    ):
        """Both directions: an event carries its initiative attachments, so a
        move between a guild calendar and an initiative calendar is refused."""
        a = await acting_user(guild_role=GuildRole.admin, initiative=True)
        await _switch_calendars_on(session, a.initiative)
        guild_calendar = await create_guild_calendar(session, a.guild, a.user)
        team_calendar = await create_calendar(session, a.initiative, a.user)
        guild_event = await create_calendar_event(session, guild_calendar, a.user)
        team_event = await create_calendar_event(session, team_calendar, a.user)

        out = await client.patch(
            a.g(f"/calendar-events/{guild_event.id}"),
            headers=a.headers,
            json={"calendar_id": team_calendar.id},
        )
        assert out.status_code == 400
        assert out.json()["detail"] == CalendarEventMessages.CANNOT_CROSS_SCOPE

        into = await client.patch(
            a.g(f"/calendar-events/{team_event.id}"),
            headers=a.headers,
            json={"calendar_id": guild_calendar.id},
        )
        assert into.status_code == 400
        assert into.json()["detail"] == CalendarEventMessages.CANNOT_CROSS_SCOPE
