"""Access-matrix tests for guild lifecycle status (suspension).

The matrix under test (see history/guild-suspension-design.md):

- ``read_only``: members keep content READS but writes are denied at the
  Postgres role level (routed into ``guild_<id>_ro``); initiative isolation
  still holds.
- ``suspended``: members lose all content access (generic 403 — the status is
  never disclosed) and the guild vanishes from their guild list. Guild ADMINS
  keep the guild listed and keep the settings surface writable.
- PAM/break-glass grants override the status entirely: a grantee behaves
  byte-identically against a suspended guild and an active one.
- Joins (invite redemption) are refused for any non-active guild, reported as
  an ordinary expired invite.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import GuildMessages, ProjectMessages
from app.models.platform.access_grant import AccessGrant
from app.models.platform.guild import Guild, GuildInvite, GuildRole, GuildStatus
from app.models.platform.user import UserRole
from app.services.tenant import task_statuses as task_statuses_service
from app.testing import (
    create_guild,
    create_initiative,
    create_task,
    create_user,
    get_auth_headers,
)

pytestmark = pytest.mark.integration


async def _set_status(session: AsyncSession, guild: Guild, status: GuildStatus):
    """Flip a guild's lifecycle status the way the (future) operator endpoint
    will: status + timestamp on the shared row."""
    guild.status = status.value
    guild.status_changed_at = datetime.now(timezone.utc)
    session.add(guild)
    await session.commit()


async def _live_grant(
    session: AsyncSession, *, user, guild, level: str = "read"
) -> AccessGrant:
    """An approved, unexpired PAM grant (the access_grants_test pattern)."""
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=level,
        status="approved",
        reason="ticket",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=user.id,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()
    return grant


# ---------------------------------------------------------------------------
# suspended: members and admins lose content
# ---------------------------------------------------------------------------


async def test_member_gets_generic_403_on_suspended_guild(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A member's content requests fail closed with the same generic code a
    non-member gets — the lifecycle status is never disclosed."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)

    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 200

    await _set_status(session, a.guild, GuildStatus.suspended)

    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == GuildMessages.GUILD_ACCESS_DENIED


async def test_admin_suspended_content_blocked_settings_writable(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild ADMIN of a suspended guild loses content like anyone else but
    keeps the settings surface fully writable (billing / data ownership)."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _set_status(session, a.guild, GuildStatus.suspended)

    # Content: blocked, generic code.
    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == GuildMessages.GUILD_ACCESS_DENIED

    # Settings: still writable (this endpoint gates on real guild-admin
    # membership, deliberately outside the content choke point).
    resp = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"name": "Still Ours"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Still Ours"


async def test_suspended_guild_hidden_from_members_listed_for_admins(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The guild list drops a suspended guild for members but keeps it for
    guild admins. The status is serialized to the admin (for their settings-page
    chip) but never to a member — members don't even see the row here."""
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    await _set_status(session, admin.guild, GuildStatus.suspended)

    resp = await client.get("/api/v1/guilds/", headers=member.headers)
    assert resp.status_code == 200
    assert admin.guild.id not in [g["id"] for g in resp.json()]

    resp = await client.get("/api/v1/guilds/", headers=admin.headers)
    assert resp.status_code == 200
    listed = [g for g in resp.json() if g["id"] == admin.guild.id]
    assert listed, "admin must still see the suspended guild"
    assert listed[0]["status"] == "suspended", "admin sees the lifecycle status"


async def test_read_only_status_visible_to_admin_not_member(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """For a read_only guild (listed for everyone), the status reaches the guild
    admin but is null for a plain member — the hold isn't disclosed to members."""
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    await _set_status(session, admin.guild, GuildStatus.read_only)

    admin_row = [
        g
        for g in (await client.get("/api/v1/guilds/", headers=admin.headers)).json()
        if g["id"] == admin.guild.id
    ][0]
    member_row = [
        g
        for g in (await client.get("/api/v1/guilds/", headers=member.headers)).json()
        if g["id"] == admin.guild.id
    ][0]
    assert admin_row["status"] == "read_only"
    assert member_row["status"] is None


async def test_establish_guild_access_refuses_suspended(
    session: AsyncSession, acting_user
):
    """The WS/keepalive entry point shares the resolver, so a suspended guild
    refuses the socket path identically (GuildAccessError → 1008)."""
    from app.api.deps import GuildAccessError, establish_guild_access

    a = await acting_user(guild_role=GuildRole.member)
    await _set_status(session, a.guild, GuildStatus.suspended)

    with pytest.raises(GuildAccessError):
        await establish_guild_access(session, a.user, a.guild.id)


# ---------------------------------------------------------------------------
# read_only: reads survive, writes die in Postgres
# ---------------------------------------------------------------------------


async def test_read_only_member_reads_but_writes_denied_at_role_level(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Under ``read_only`` a member still reads content (initiative RLS legs
    intact) but writes are refused: the DAC engine caps the request at read
    (clean app-layer 403), and even without it the INSERT would die in
    Postgres (``guild_<id>_ro`` has no write privileges)."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await task_statuses_service.ensure_default_statuses(session, a.project.id)
    status = await task_statuses_service.get_default_status(session, a.project.id)
    await session.commit()

    await _set_status(session, a.guild, GuildStatus.read_only)

    # Reads: fine.
    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 200
    assert any(i["id"] == a.initiative.id for i in resp.json())

    # Writes: refused with the ordinary write-denied code (NOT a
    # status-specific one — the lifecycle status is not disclosed to members).
    resp = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "frozen",
            "project_id": a.project.id,
            "task_status_id": status.id,
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == ProjectMessages.WRITE_ACCESS_REQUIRED


async def test_read_only_guild_admin_writes_denied_too(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """``read_only`` freezes GUILD ADMINS exactly like members: the request is
    routed into ``guild_<id>_ro`` regardless of the membership role, so the
    admin RLS leg can read everything but no content write survives."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await task_statuses_service.ensure_default_statuses(session, a.project.id)
    status = await task_statuses_service.get_default_status(session, a.project.id)
    task = await create_task(session, a.project, title="before")
    await session.commit()

    await _set_status(session, a.guild, GuildStatus.read_only)

    resp = await client.post(
        a.g("/tasks/"),
        headers=a.headers,
        json={
            "title": "frozen-admin",
            "project_id": a.project.id,
            "task_status_id": status.id,
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == ProjectMessages.WRITE_ACCESS_REQUIRED

    resp = await client.patch(
        a.g(f"/tasks/{task.id}"), headers=a.headers, json={"title": "after"}
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == ProjectMessages.WRITE_ACCESS_REQUIRED


async def test_read_only_establishes_content_read_only_context(
    session: AsyncSession, acting_user
):
    """The WS/keepalive entry point resolves ``content_read_only`` for real
    members of a read_only guild — the collaboration socket derives its
    ``can_write`` from this, so a frozen guild can't be edited over Yjs."""
    from app.api.deps import establish_guild_access
    from app.db.session import set_rls_context

    a = await acting_user(guild_role=GuildRole.admin)
    ctx = await establish_guild_access(session, a.user, a.guild.id)
    assert ctx.content_read_only is False

    # establish_guild_access left the session routed as the guild role, whose
    # column-scoped grant can't write status — reset to the setup baseline.
    await set_rls_context(session)
    await _set_status(session, a.guild, GuildStatus.read_only)
    ctx = await establish_guild_access(session, a.user, a.guild.id)
    assert ctx.content_read_only is True


async def test_read_only_caps_serialized_permission_level(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The DAC engine caps ``my_permission_level`` at read while the guild is
    frozen — ONE server-side flag drives every client write affordance (and
    the collaboration socket's ``can_write``), so the UI can't drift into
    showing editors the backend will refuse. Writable-project filters dry up
    the create pickers the same way."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    resp = await client.get(a.g(f"/projects/{a.project.id}"), headers=a.headers)
    assert resp.json()["my_permission_level"] == "owner"

    await _set_status(session, a.guild, GuildStatus.read_only)

    resp = await client.get(a.g(f"/projects/{a.project.id}"), headers=a.headers)
    assert resp.status_code == 200
    assert resp.json()["my_permission_level"] == "read"

    resp = await client.get(a.g("/projects/writable"), headers=a.headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_read_only_keeps_initiative_isolation(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The read-only route keeps the membership GUCs, so gate 2 (initiative
    isolation) still filters: a member sees only their own initiatives."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    b = await acting_user(guild_role=GuildRole.member, guild=a.guild, initiative=True)
    await _set_status(session, a.guild, GuildStatus.read_only)

    resp = await client.get(a.g("/initiatives/"), headers=a.headers)
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()]
    assert a.initiative.id in ids
    assert b.initiative.id not in ids


async def test_read_only_admin_settings_still_writable(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Settings stay writable for guild admins under read_only too."""
    a = await acting_user(guild_role=GuildRole.admin)
    await _set_status(session, a.guild, GuildStatus.read_only)

    resp = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={"description": "billing sorted soon"},
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# PAM / break-glass: the override
# ---------------------------------------------------------------------------


async def test_break_glass_full_admin_on_suspended_guild(
    client: AsyncClient, session: AsyncSession
):
    """A break-glass holder behaves as a full guild admin against a SUSPENDED
    guild — reads and writes — exactly as against an active one. This is the
    requirement that suspension can never lock operators out."""
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner, name="Frozen Wing")
    await _set_status(session, guild, GuildStatus.suspended)

    platform_admin = await create_user(session, role=UserRole.operator)
    headers = get_auth_headers(platform_admin)
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={
            "guild_id": guild.id,
            "reason": "billing hold review",
            "access_level": "read_write",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # Read.
    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 200, resp.text
    assert any(i["name"] == "Frozen Wing" for i in resp.json())

    # Write (full admin: edits guild content).
    resp = await client.patch(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}",
        headers=headers,
        json={"description": "reviewed under break-glass"},
    )
    assert resp.status_code == 200, resp.text


async def test_scoped_read_grant_reads_suspended_guild(
    client: AsyncClient, session: AsyncSession
):
    """A scoped PAM read grant (support's request→approve flow) still reads a
    suspended guild — the resolver's grant branch never consults the status."""
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Held Wing")
    await _set_status(session, guild, GuildStatus.suspended)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=guild, level="read")

    resp = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/", headers=get_auth_headers(support)
    )
    assert resp.status_code == 200, resp.text
    assert any(i["name"] == "Held Wing" for i in resp.json())


async def test_scoped_read_write_grant_edits_suspended_guild(
    client: AsyncClient, session: AsyncSession
):
    """A scoped read_write grant held by a NON-bypass user keeps its
    edit-existing power against a suspended guild (routed via pam_write, so
    neither the suspension gate nor the read-only role applies)."""
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    initiative = await create_initiative(session, guild, owner)
    from app.testing import create_project

    project = await create_project(session, initiative, owner)
    task = await create_task(session, project, title="held task")
    await _set_status(session, guild, GuildStatus.suspended)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=guild, level="read_write")

    resp = await client.patch(
        f"/api/v1/g/{guild.id}/tasks/{task.id}",
        headers=get_auth_headers(support),
        json={"title": "edited under grant"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "edited under grant"


# ---------------------------------------------------------------------------
# joins are frozen
# ---------------------------------------------------------------------------


async def _invite_for(session: AsyncSession, guild: Guild, code: str) -> GuildInvite:
    invite = GuildInvite(
        code=code,
        guild_id=guild.id,
        created_by_user_id=guild.created_by_user_id,
        max_uses=5,
    )
    session.add(invite)
    await session.commit()
    return invite


@pytest.mark.parametrize(
    "status", [GuildStatus.read_only, GuildStatus.suspended], ids=lambda s: s.value
)
async def test_invite_redemption_refused_on_non_active_guild(
    client: AsyncClient, session: AsyncSession, acting_user, status
):
    """Joining a non-active guild is refused, reported as a plain expired
    invite (never the guild's lifecycle status)."""
    admin = await acting_user(guild_role=GuildRole.admin)
    invite = await _invite_for(session, admin.guild, f"frozen-{status.value}")
    await _set_status(session, admin.guild, status)

    joiner = await acting_user()
    resp = await client.post(
        "/api/v1/guilds/invite/accept",
        headers=joiner.headers,
        json={"code": invite.code},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == GuildMessages.INVITE_EXPIRED_OR_USED

    # The describe endpoint reports it like any expired code.
    resp = await client.get(
        f"/api/v1/guilds/invite/{invite.code}", headers=joiner.headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_valid"] is False
    assert body["reason"] == GuildMessages.INVITE_EXPIRED


# ---------------------------------------------------------------------------
# cross-guild "/me" aggregates honor the status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role", [GuildRole.member, GuildRole.admin], ids=lambda r: r.value
)
async def test_suspended_guild_content_hidden_from_me_aggregates(
    client: AsyncClient, session: AsyncSession, acting_user, role
):
    """/me/* visits each member guild's schema directly (no ``/g/`` choke
    point), so it must apply the same suspension rule itself: a suspended
    guild's content vanishes from the aggregates — for admins too, who keep
    only the settings surface."""
    a = await acting_user(guild_role=role, initiative=True, project=True)
    await create_task(session, a.project, title="mine", assignees=[a.user])

    resp = await client.get("/api/v1/me/tasks", headers=a.headers)
    assert resp.status_code == 200
    assert any(t["title"] == "mine" for t in resp.json()["items"])

    await _set_status(session, a.guild, GuildStatus.suspended)

    resp = await client.get("/api/v1/me/tasks", headers=a.headers)
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_read_only_guild_content_still_in_me_aggregates(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """read_only keeps reads: the aggregate path routes that guild through the
    SELECT-only role but the content stays visible."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await create_task(session, a.project, title="mine", assignees=[a.user])
    await _set_status(session, a.guild, GuildStatus.read_only)

    resp = await client.get("/api/v1/me/tasks", headers=a.headers)
    assert resp.status_code == 200
    assert any(t["title"] == "mine" for t in resp.json()["items"])


# ---------------------------------------------------------------------------
# the member-facing read-only signal
# ---------------------------------------------------------------------------


async def test_content_read_only_flag_serialized_to_members(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Members never see the status itself, but they DO get the effect flag —
    the UI must drop write affordances when the guild is frozen."""
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    row = [
        g
        for g in (await client.get("/api/v1/guilds/", headers=member.headers)).json()
        if g["id"] == admin.guild.id
    ][0]
    assert row["content_read_only"] is False

    await _set_status(session, admin.guild, GuildStatus.read_only)

    row = [
        g
        for g in (await client.get("/api/v1/guilds/", headers=member.headers)).json()
        if g["id"] == admin.guild.id
    ][0]
    assert row["content_read_only"] is True
    assert row["status"] is None, "the status itself stays undisclosed to members"


# ---------------------------------------------------------------------------
# enforcement columns: operator/billing only, database-enforced
# ---------------------------------------------------------------------------


async def test_guild_admin_patch_cannot_touch_enforcement_fields(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The guild-facing PATCH no longer carries cap/status fields — a payload
    that smuggles them is ignored (unknown fields), never applied."""
    a = await acting_user(guild_role=GuildRole.admin)

    resp = await client.patch(
        f"/api/v1/guilds/{a.guild.id}",
        headers=a.headers,
        json={
            "name": "Renamed",
            "max_storage_bytes": 5,
            "max_users": 1,
            "status": "active",
            "tier_name": "Enterprise",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert body["max_storage_bytes"] is None
    assert body["max_users"] is None
    assert body["tier_name"] is None

    await session.refresh(a.guild)
    assert a.guild.max_storage_bytes is None
    assert a.guild.status == GuildStatus.active.value


async def test_guild_role_lacks_update_on_enforcement_columns(
    session: AsyncSession, acting_user, role_session
):
    """Column-scoped grants (migration 0138): the assumed ``guild_<id>`` role
    can rename its guild but a direct UPDATE of ``status`` / caps / tier dies
    with insufficient_privilege — the DB, not app code, is the boundary."""
    import sqlalchemy.exc
    from sqlalchemy import text as sa_text

    from app.db.session import set_rls_context

    a = await acting_user(guild_role=GuildRole.admin)

    s = await role_session("app_user")
    await set_rls_context(s, user_id=a.user.id, guild_id=a.guild.id, guild_role="admin")

    # Identity columns: allowed.
    await s.exec(
        sa_text("UPDATE public.guilds SET name = 'renamed-by-role' WHERE id = :gid"),
        params={"gid": a.guild.id},
    )
    await s.rollback()

    for column, value in [
        ("status", "'suspended'"),
        ("status_changed_at", "now()"),
        ("tier_name", "'Enterprise'"),
        ("max_storage_bytes", "5"),
        ("max_users", "1"),
    ]:
        await set_rls_context(
            s, user_id=a.user.id, guild_id=a.guild.id, guild_role="admin"
        )
        with pytest.raises(sqlalchemy.exc.ProgrammingError, match="permission denied"):
            await s.exec(
                sa_text(f"UPDATE public.guilds SET {column} = {value} WHERE id = :gid"),
                params={"gid": a.guild.id},
            )
        await s.rollback()


async def test_platform_guild_status_endpoint_requires_guilds_manage(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The operator endpoint stays capability-gated: a plain member (and the
    guild's own admin) get 403; a platform admin flips the status."""
    a = await acting_user(guild_role=GuildRole.admin)

    resp = await client.patch(
        f"/api/v1/settings/guilds/{a.guild.id}",
        headers=a.headers,
        json={"status": "suspended"},
    )
    assert resp.status_code == 403

    platform_admin = await create_user(session, role=UserRole.operator)
    resp = await client.patch(
        f"/api/v1/settings/guilds/{a.guild.id}",
        headers=get_auth_headers(platform_admin),
        json={"status": "suspended"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"
