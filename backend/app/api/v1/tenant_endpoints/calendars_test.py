"""Tests for the calendar container endpoints — CRUD, sharing, and the
authorization gates (initiative isolation, role create gate, feature gate,
DAC levels, guild-admin override)."""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete as sa_delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.calendar_event import CalendarEvent
from app.models.tenant.resource_grant import ResourceGrant
from app.testing import (
    create_calendar,
    create_calendar_event,
    create_guild_app,
    route_session_to_guild,
    create_initiative,
    create_guild_calendar,
)

CALENDAR_APP = {
    "app_kind": "tool_instance",
    "tool": "calendar",
    "default_name": "Guild calendar",
}


async def _install_calendar_app(session, guild, creator):
    """The guild calendar app, which is what holds a guild's calendars."""
    return await create_guild_app(
        session,
        guild,
        creator,
        definition=CALENDAR_APP,
        name="Guild calendar",
        app_kind="tool_instance",
    )


async def _calendars_enabled(session: AsyncSession, initiative) -> None:
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _strip_non_owner_grants(session, calendar, owner_id: int) -> None:
    """Remove every grant except the owner's own — the calendar becomes
    invisible to other members. (is_distinct_from: role grants carry a NULL
    user_id, which a plain ``!=`` would silently skip.)"""
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == "calendar",
            ResourceGrant.resource_id == calendar.id,
            ResourceGrant.user_id.is_distinct_from(owner_id),
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_calendar(client: AsyncClient, acting_user, session):
    """A PM creates a calendar: creator owner grant + the default
    all-initiative-members read grant."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)

    response = await client.post(
        a.g("/calendars/"),
        headers=a.headers,
        json={
            "name": "Raid Nights",
            "description": "Weekly schedule",
            "color": "#7c3aed",
            "initiative_id": a.initiative.id,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Raid Nights"
    assert data["description"] == "Weekly schedule"
    assert data["color"] == "#7c3aed"
    assert data["initiative_id"] == a.initiative.id
    assert data["created_by"] == a.user.id
    assert data["my_permission_level"] == "owner"
    grant_shapes = {
        (g["level"], g["all_initiative_members"], g["user_id"]) for g in data["grants"]
    }
    assert ("owner", False, a.user.id) in grant_shapes
    assert ("read", True, None) in grant_shapes


@pytest.mark.integration
async def test_create_calendar_requires_feature_enabled(
    client: AsyncClient, acting_user
):
    """calendars_enabled is the initiative's tool gate — off means 403 even
    for a guild admin."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.post(
        a.g("/calendars/"),
        headers=a.headers,
        json={"name": "Too Soon", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CALENDARS_NOT_ENABLED"


@pytest.mark.integration
async def test_create_calendar_non_pm_forbidden(
    client: AsyncClient, acting_user, session
):
    """A plain member lacks create_calendars — the role permission gate."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _calendars_enabled(session, admin.initiative)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    response = await client.post(
        member.g("/calendars/"),
        headers=member.headers,
        json={"name": "Forbidden", "initiative_id": admin.initiative.id},
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_get_calendar(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user, name="Mine")

    response = await client.get(a.g(f"/calendars/{calendar.id}"), headers=a.headers)

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == calendar.id
    assert data["my_permission_level"] == "owner"


@pytest.mark.integration
async def test_list_calendars_dac_filtered(client: AsyncClient, acting_user, session):
    """The list applies calendar sharing: a member sees shared calendars only,
    a guild admin sees everything (the admin override)."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)
    shared = await create_calendar(session, a.initiative, a.user, name="Shared")
    secret = await create_calendar(session, a.initiative, a.user, name="Secret")
    await _strip_non_owner_grants(session, secret, a.user.id)

    member_list = await client.get(member.g("/calendars/"), headers=member.headers)
    assert member_list.status_code == 200
    member_names = {c["name"] for c in member_list.json()["items"]}
    assert shared.name in member_names
    assert secret.name not in member_names

    admin_list = await client.get(admin.g("/calendars/"), headers=admin.headers)
    admin_names = {c["name"] for c in admin_list.json()["items"]}
    assert {shared.name, secret.name} <= admin_names


@pytest.mark.integration
async def test_calendar_404_outside_initiative(
    client: AsyncClient, acting_user, session
):
    """The hard isolation boundary: a guild member NOT in the initiative gets
    404 (RLS hides the row), not 403."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user, name="Cleared")
    outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)

    response = await client.get(
        outsider.g(f"/calendars/{calendar.id}"), headers=outsider.headers
    )

    assert response.status_code == 404


@pytest.mark.integration
async def test_update_calendar_requires_write(
    client: AsyncClient, acting_user, session
):
    """Rename needs write: the default all-members read grant is not enough."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    calendar = await create_calendar(session, a.initiative, a.user, name="Before")

    denied = await client.patch(
        reader.g(f"/calendars/{calendar.id}"),
        headers=reader.headers,
        json={"name": "Hijacked"},
    )
    assert denied.status_code == 403

    renamed = await client.patch(
        a.g(f"/calendars/{calendar.id}"),
        headers=a.headers,
        json={"name": "After", "color": "#16a34a"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "After"
    assert renamed.json()["color"] == "#16a34a"


@pytest.mark.integration
async def test_delete_calendar_owner_only_and_cascades(
    client: AsyncClient, acting_user, session
):
    """Delete is owner (or guild admin); the soft delete cascades to the
    calendar's events."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    writer = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    calendar = await create_calendar(session, a.initiative, a.user, name="Doomed")
    event = await create_calendar_event(session, calendar, a.user, title="Going too")
    # Upgrade the writer to write (still not owner).
    grants = await client.put(
        a.g(f"/calendars/{calendar.id}/grants"),
        headers=a.headers,
        json=[
            {"all_initiative_members": True, "level": "read"},
            {"user_id": writer.user.id, "level": "write"},
        ],
    )
    assert grants.status_code == 200

    denied = await client.delete(
        writer.g(f"/calendars/{calendar.id}"), headers=writer.headers
    )
    assert denied.status_code == 403

    deleted = await client.delete(a.g(f"/calendars/{calendar.id}"), headers=a.headers)
    assert deleted.status_code == 204

    gone = await client.get(a.g(f"/calendars/{calendar.id}"), headers=a.headers)
    assert gone.status_code == 404

    # The event is soft-deleted with its calendar.
    await route_session_to_guild(session, a.guild.id)
    row = (
        await session.exec(
            select(CalendarEvent)
            .where(CalendarEvent.id == event.id)
            .execution_options(include_deleted=True)
        )
    ).one()
    assert row.deleted_at is not None


@pytest.mark.integration
async def test_guild_admin_can_delete_any_calendar(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    calendar = await create_calendar(session, a.initiative, a.user, name="Anyone's")
    admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

    response = await client.delete(
        admin.g(f"/calendars/{calendar.id}"), headers=admin.headers
    )

    assert response.status_code == 204


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_set_calendar_grants_owner_only(
    client: AsyncClient, acting_user, session
):
    """PUT /grants is the owner's: a write-level member is refused; the owner's
    replacement list takes effect for other members."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    calendar = await create_calendar(session, a.initiative, a.user, name="Managed")

    denied = await client.put(
        member.g(f"/calendars/{calendar.id}/grants"),
        headers=member.headers,
        json=[{"all_initiative_members": True, "level": "write"}],
    )
    assert denied.status_code == 403

    # Owner grants the member write — the member can now rename.
    updated = await client.put(
        a.g(f"/calendars/{calendar.id}/grants"),
        headers=a.headers,
        json=[{"user_id": member.user.id, "level": "write"}],
    )
    assert updated.status_code == 200

    renamed = await client.patch(
        member.g(f"/calendars/{calendar.id}"),
        headers=member.headers,
        json={"name": "Renamed by member"},
    )
    assert renamed.status_code == 200

    # Revoking every non-owner grant locks the member out again (403, not
    # 404 — an initiative member still sees the row via RLS; DAC refuses).
    await _strip_non_owner_grants(session, calendar, a.user.id)
    hidden = await client.get(
        member.g(f"/calendars/{calendar.id}"), headers=member.headers
    )
    assert hidden.status_code == 403


# ---------------------------------------------------------------------------
# Cross-guild personal view
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_my_calendars_spans_guilds_and_applies_dac(
    client: AsyncClient, acting_user, session
):
    """GET /me/calendars merges the user's visible calendars across every
    guild they belong to, with calendar sharing applied per guild."""
    from app.testing import create_guild_membership, create_initiative_member

    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, a.initiative)
    shared = await create_calendar(session, a.initiative, a.user, name="Home Cal")
    secret = await create_calendar(session, a.initiative, a.user, name="Secret Cal")

    # Second guild the same user belongs to, with its own calendar.
    b = await acting_user(guild_role=GuildRole.member, initiative=True)
    await _calendars_enabled(session, b.initiative)
    await create_guild_membership(session, user=a.user, guild=b.guild)
    await create_initiative_member(session, b.initiative, a.user)
    away = await create_calendar(session, b.initiative, b.user, name="Away Cal")

    response = await client.get("/api/v1/me/calendars", headers=a.headers)
    assert response.status_code == 200
    names = {c["name"] for c in response.json()["items"]}
    assert {shared.name, secret.name, away.name} <= names

    # Strip the second actor's view of nothing — instead strip a's access to
    # the secret calendar via its grants and confirm it drops out for a
    # different member while a (the owner) keeps it.
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    await _strip_non_owner_grants(session, secret, a.user.id)
    member_resp = await client.get("/api/v1/me/calendars", headers=member.headers)
    assert member_resp.status_code == 200
    member_names = {c["name"] for c in member_resp.json()["items"]}
    assert shared.name in member_names
    assert secret.name not in member_names
    assert away.name not in member_names  # not a member of guild b


async def test_calendar_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts mirror the list: DAC-visible calendars in calendars-enabled
    initiatives, and never a guild calendar — the sidebar rows the counts sit on
    are initiative rows, and a guild calendar belongs to none of them."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _calendars_enabled(session, admin.initiative)
    disabled_initiative = await create_initiative(
        session, admin.guild, admin.user, calendars_enabled=False
    )

    await create_calendar(session, admin.initiative, admin.user, name="Team")
    await create_calendar(session, disabled_initiative, admin.user, name="Hidden")
    await create_guild_calendar(session, admin.guild, admin.user)

    response = await client.get(
        admin.g("/calendars/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {str(admin.initiative.id): 1}


# ---------------------------------------------------------------------------
# Guild calendars — the ones the calendar app holds
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_any_member_creates_a_guild_calendar(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """No initiative means no initiative gate: an ordinary member may add a
    calendar to the guild's own, and owns what they made."""
    admin = await acting_user(guild_role=GuildRole.admin)
    await _install_calendar_app(session, admin.guild, admin.user)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    response = await client.post(
        member.g("/calendars/"),
        headers=member.headers,
        json={"name": "Holidays", "color": "#22c55e"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["initiative_id"] is None
    assert body["my_permission_level"] == "owner"

    await route_session_to_guild(session, admin.guild.id)
    grants = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "calendar",
                ResourceGrant.resource_id == body["id"],
            )
        )
    ).all()
    # The creator owns it, and the default sharing reads as the whole guild.
    assert {(g.user_id, str(g.level), g.all_initiative_members) for g in grants} == {
        (member.user.id, "owner", False),
        (None, "read", True),
    }
    assert all(g.initiative_id is None for g in grants)


@pytest.mark.integration
async def test_a_guild_calendar_joins_the_app_s_artifacts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The app is the container: removing it walks its artifacts, so a calendar
    added later has to be among them."""
    a = await acting_user(guild_role=GuildRole.admin)
    app = await _install_calendar_app(session, a.guild, a.user)

    response = await client.post(
        a.g("/calendars/"), headers=a.headers, json={"name": "Holidays"}
    )
    assert response.status_code == 201, response.text

    await route_session_to_guild(session, a.guild.id)
    await session.refresh(app)
    assert app.artifacts == [{"type": "calendar", "id": response.json()["id"]}]


@pytest.mark.integration
async def test_a_calendar_joins_artifacts_it_never_saw(
    session: AsyncSession, acting_user
):
    """Any member may add a calendar, so two of them can be adding one at the
    same moment. The append is made against the stored list rather than against
    a copy of it, so an entry written since this one was read still survives —
    otherwise it would stop being something the app removes."""
    from sqlalchemy import update

    from app.models.tenant.guild_app import GuildApp
    from app.services.tenant import guild_apps as guild_apps_service

    a = await acting_user(guild_role=GuildRole.admin)
    app = await _install_calendar_app(session, a.guild, a.user)
    calendar = await create_guild_calendar(session, a.guild, a.user)

    # Someone else's calendar lands first; this copy of the row knows nothing
    # about it.
    await route_session_to_guild(session, a.guild.id)
    await session.exec(
        update(GuildApp)
        .where(GuildApp.id == app.id)
        .values(artifacts=[{"type": "calendar", "id": calendar.id}])
        .execution_options(synchronize_session=False)
    )
    await session.commit()

    await guild_apps_service.record_artifact(
        session, app, artifact_type="calendar", artifact_id=999
    )
    await session.commit()

    await session.refresh(app)
    assert app.artifacts == [
        {"type": "calendar", "id": calendar.id},
        {"type": "calendar", "id": 999},
    ]


@pytest.mark.integration
async def test_a_guild_calendar_needs_the_app(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Without the app there is no entry that reaches a guild calendar, so one
    is refused rather than created where nothing links to it."""
    a = await acting_user(guild_role=GuildRole.admin)

    response = await client.post(
        a.g("/calendars/"), headers=a.headers, json={"name": "Holidays"}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "CALENDAR_GUILD_APP_REQUIRED"


@pytest.mark.integration
async def test_guild_scope_lists_only_the_guild_s_own(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``scope=guild`` is the calendar app's own list: guild calendars, and no
    initiative's."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _calendars_enabled(session, a.initiative)
    await create_calendar(session, a.initiative, a.user, name="Team")
    guild_calendar = await create_guild_calendar(
        session, a.guild, a.user, name="Holidays"
    )

    response = await client.get(
        a.g("/calendars/"), headers=a.headers, params={"scope": "guild"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [c["id"] for c in body["items"]] == [guild_calendar.id]
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_a_guild_calendar_is_hidden_when_it_is_not_shared(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Guild scope clears the initiative gate, not the sharing one: what a
    member made privately stays theirs.

    A guild calendar is refused rather than hidden — the initiative gate, which
    is what turns a refusal into a 404 for initiative content, has nothing to
    say about a row belonging to no initiative. Sharing is the whole of the
    answer here.
    """
    a = await acting_user(guild_role=GuildRole.member)
    owner = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    calendar = await create_guild_calendar(
        session, a.guild, owner.user, name="Mine", shared_with_everyone=False
    )

    response = await client.get(
        a.g("/calendars/"), headers=a.headers, params={"scope": "guild"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []

    assert (
        await client.get(a.g(f"/calendars/{calendar.id}"), headers=a.headers)
    ).status_code == 403
