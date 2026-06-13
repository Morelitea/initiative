"""End-to-end tests for the Privileged Access Management (PAM) endpoints."""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from datetime import datetime, timedelta, timezone

from app.models.access_grant import AccessGrant
from app.models.user import UserRole
from app.testing import (
    create_guild,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
    get_guild_headers,
)


async def _approved_read_grant(session, *, user, guild, owner, level="read"):
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=level,
        status="approved",
        reason="ticket",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=owner.id,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()
    return grant


@pytest.mark.integration
async def test_support_can_request_and_owner_approves(
    client: AsyncClient, session: AsyncSession
):
    owner = await create_user(session, email="owner@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support@example.com", role=UserRole.support
    )
    # A guild the support user is NOT a member of.
    guild = await create_guild(session, creator=owner)

    # Support requests read access.
    resp = await client.post(
        "/api/v1/access-grants/",
        json={
            "guild_id": guild.id,
            "access_level": "read",
            "reason": "debugging a ticket",
        },
        headers=get_auth_headers(support),
    )
    assert resp.status_code == 201, resp.text
    grant = resp.json()
    assert grant["status"] == "pending"
    assert grant["is_live"] is False
    assert grant["guild_name"] == guild.name
    grant_id = grant["id"]

    # Owner sees it in the full queue (mine=false requires access.read).
    resp = await client.get(
        "/api/v1/access-grants/?mine=false&status=pending",
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 200
    assert any(g["id"] == grant_id for g in resp.json())

    # Owner approves.
    resp = await client.post(
        f"/api/v1/access-grants/{grant_id}/approve",
        json={},
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    approved = resp.json()
    assert approved["status"] == "approved"
    assert approved["is_live"] is True
    assert approved["expires_at"] is not None


@pytest.mark.integration
async def test_my_requests_respects_limit_and_order(
    client: AsyncClient, session: AsyncSession
):
    """``limit`` caps the my-requests history to the most recent N (newest
    first), so a churny requester's list can't grow unbounded."""
    owner = await create_user(
        session, email="owner-lim@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="support-lim@example.com", role=UserRole.support
    )

    # Five historical grants with strictly increasing requested_at.
    base = datetime.now(timezone.utc) - timedelta(days=5)
    for i in range(5):
        session.add(
            AccessGrant(
                user_id=support.id,
                guild_id=(await create_guild(session, creator=owner)).id,
                access_level="read",
                status="expired",
                reason=f"old {i}",
                requested_duration_minutes=60,
                requested_by_id=support.id,
                requested_at=base + timedelta(hours=i),
            )
        )
    await session.commit()

    resp = await client.get(
        "/api/v1/access-grants/?mine=true&limit=3", headers=get_auth_headers(support)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == 3, "limit must cap the result"
    # Newest-first: the three most-recently-requested ("old 4/3/2").
    assert [g["reason"] for g in body] == ["old 4", "old 3", "old 2"]

    # Second page via offset continues where the first left off.
    resp = await client.get(
        "/api/v1/access-grants/?mine=true&limit=3&offset=3",
        headers=get_auth_headers(support),
    )
    assert resp.status_code == 200, resp.text
    assert [g["reason"] for g in resp.json()] == ["old 1", "old 0"]


@pytest.mark.integration
async def test_queue_live_filter_excludes_expired(
    client: AsyncClient, session: AsyncSession
):
    """``live=true`` on the approver queue drops approved-but-expired grants so
    the active list pages accurately."""
    owner = await create_user(
        session, email="owner-live@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="support-live@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    now = datetime.now(timezone.utc)

    # One live grant, one approved-but-expired.
    session.add(
        AccessGrant(
            user_id=support.id,
            guild_id=guild.id,
            access_level="read",
            status="approved",
            reason="live one",
            requested_duration_minutes=60,
            requested_by_id=support.id,
            approved_by_id=owner.id,
            decided_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    session.add(
        AccessGrant(
            user_id=support.id,
            guild_id=guild.id,
            access_level="read",
            status="approved",
            reason="stale one",
            requested_duration_minutes=60,
            requested_by_id=support.id,
            approved_by_id=owner.id,
            decided_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
        )
    )
    await session.commit()

    resp = await client.get(
        "/api/v1/access-grants/?mine=false&status=approved&live=true",
        headers=get_auth_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    reasons = [g["reason"] for g in resp.json()]
    assert reasons == ["live one"], "live filter must exclude the expired grant"


@pytest.mark.integration
async def test_member_cannot_request_access(client: AsyncClient, session: AsyncSession):
    """A plain member lacks access.request and is forbidden."""
    owner = await create_user(session, email="owner2@example.com", role=UserRole.owner)
    member = await create_user(
        session, email="member2@example.com", role=UserRole.member
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.post(
        "/api/v1/access-grants/",
        json={"guild_id": guild.id, "reason": "no caps"},
        headers=get_auth_headers(member),
    )
    assert resp.status_code == 403


@pytest.mark.integration
async def test_requester_cannot_approve_own(client: AsyncClient, session: AsyncSession):
    """An admin can both request and approve, but never their own request."""
    owner = await create_user(session, email="owner3@example.com", role=UserRole.owner)
    admin = await create_user(session, email="admin3@example.com", role=UserRole.admin)
    guild = await create_guild(session, creator=owner)

    resp = await client.post(
        "/api/v1/access-grants/",
        json={"guild_id": guild.id, "reason": "self"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    grant_id = resp.json()["id"]

    resp = await client.post(
        f"/api/v1/access-grants/{grant_id}/approve",
        json={},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACCESS_GRANT_CANNOT_APPROVE_OWN"


@pytest.mark.integration
async def test_duration_over_cap_rejected(client: AsyncClient, session: AsyncSession):
    owner = await create_user(session, email="owner4@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support4@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.post(
        "/api/v1/access-grants/",
        json={
            "guild_id": guild.id,
            "reason": "too long",
            "requested_duration_minutes": 10_000,  # over the 24h ceiling
        },
        headers=get_auth_headers(support),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACCESS_GRANT_DURATION_TOO_LONG"


@pytest.mark.integration
async def test_duration_cap_is_per_role(client: AsyncClient, session: AsyncSession):
    """Lower-trust roles get shorter windows: support is capped at 4h, but a
    moderator may go to 8h."""
    owner = await create_user(session, email="owner6@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support6@example.com", role=UserRole.support
    )
    moderator = await create_user(
        session, email="mod6@example.com", role=UserRole.moderator
    )
    guild = await create_guild(session, creator=owner)

    # 8h is within the moderator cap...
    resp = await client.post(
        "/api/v1/access-grants/",
        json={"guild_id": guild.id, "reason": "8h", "requested_duration_minutes": 480},
        headers=get_auth_headers(moderator),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["requested_duration_minutes"] == 480

    # ...but exceeds support's 4h cap.
    resp = await client.post(
        "/api/v1/access-grants/",
        json={"guild_id": guild.id, "reason": "8h", "requested_duration_minutes": 480},
        headers=get_auth_headers(support),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "ACCESS_GRANT_DURATION_TOO_LONG"


@pytest.mark.integration
async def test_revoke_and_cancel(client: AsyncClient, session: AsyncSession):
    owner = await create_user(session, email="owner5@example.com", role=UserRole.owner)
    support = await create_user(
        session, email="support5@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)

    # Cancel own pending.
    resp = await client.post(
        "/api/v1/access-grants/",
        json={"guild_id": guild.id, "reason": "cancel me"},
        headers=get_auth_headers(support),
    )
    grant_id = resp.json()["id"]
    resp = await client.delete(
        f"/api/v1/access-grants/{grant_id}", headers=get_auth_headers(support)
    )
    assert resp.status_code == 204

    # Approve then revoke.
    resp = await client.post(
        "/api/v1/access-grants/",
        json={"guild_id": guild.id, "reason": "revoke me"},
        headers=get_auth_headers(support),
    )
    grant_id = resp.json()["id"]
    await client.post(
        f"/api/v1/access-grants/{grant_id}/approve",
        json={},
        headers=get_auth_headers(owner),
    )
    resp = await client.post(
        f"/api/v1/access-grants/{grant_id}/revoke", headers=get_auth_headers(owner)
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"
    assert resp.json()["is_live"] is False


@pytest.mark.integration
async def test_grant_cannot_manage_project_members(
    client: AsyncClient, session: AsyncSession
):
    """Even a read_write grant can't manage project members/permissions — a
    grant confers content read/write only. Must be a clean 403, not a 500 from
    the project_permissions write faulting under RLS."""
    owner = await create_user(
        session, email="owner-mm@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="support-mm@example.com", role=UserRole.support
    )
    target = await create_user(session, email="target-mm@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner, name="Ops")
    project = await create_project(session, init, owner, name="Site")
    await _approved_read_grant(
        session, user=support, guild=guild, owner=owner, level="read_write"
    )

    headers = await get_guild_headers(session, guild, support)
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/members",
        json={"user_id": target.id, "level": "write"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "PROJECT_GRANT_CANNOT_MANAGE_MEMBERS"


@pytest.mark.integration
async def test_grant_cannot_manage_counter_group_access(
    client: AsyncClient, session: AsyncSession
):
    """A read_write grant can't manage counter group access (writes
    counter_group_permissions, which RLS blocks) — clean 403, not 500."""
    from app.models.counter import CounterGroup

    owner = await create_user(
        session, email="owner-cg@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="support-cg@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner, name="Stats Wing")
    cg = CounterGroup(
        guild_id=guild.id, initiative_id=init.id, name="Stats", created_by_id=owner.id
    )
    session.add(cg)
    await session.commit()
    await session.refresh(cg)
    await _approved_read_grant(
        session, user=support, guild=guild, owner=owner, level="read_write"
    )

    headers = await get_guild_headers(session, guild, support)
    resp = await client.put(
        f"/api/v1/g/{guild.id}/counter-groups/{cg.id}/permissions",
        json=[],
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "COUNTER_GRANT_CANNOT_MANAGE"


@pytest.mark.integration
async def test_grantee_sees_guild_content(client: AsyncClient, session: AsyncSession):
    """A read grant exposes the guild's initiatives/projects in the list
    endpoints — not just RLS, but the app-layer membership filters too (the
    'empty guild' bug)."""
    owner = await create_user(
        session, email="owner-content@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="support-content@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner, name="Recon Wing")
    project = await create_project(session, init, owner, name="Alpha Site")
    await _approved_read_grant(session, user=support, guild=guild, owner=owner)

    headers = await get_guild_headers(session, guild, support)

    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 200, resp.text
    assert any(i["name"] == "Recon Wing" for i in resp.json()), (
        "grantee should see the initiative"
    )

    resp = await client.get(f"/api/v1/g/{guild.id}/projects/", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert any(p["name"] == "Alpha Site" for p in items), (
        "grantee should see the project"
    )

    # Initiative tool views: a grantee has no membership row, so these used to
    # 403. They should now succeed (read-only, never manager).
    resp = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/{init.id}/my-permissions", headers=headers
    )
    assert resp.status_code == 200, resp.text
    perms = resp.json()
    assert perms["is_manager"] is False, "a grant never confers initiative management"
    assert perms["permissions"]["create_projects"] is False, (
        "read grant must not create"
    )

    resp = await client.get(
        f"/api/v1/g/{guild.id}/initiatives/{init.id}/members", headers=headers
    )
    assert resp.status_code == 200, resp.text

    resp = await client.get(f"/api/v1/g/{guild.id}/calendar-events/", headers=headers)
    assert resp.status_code == 200, resp.text

    # Recording a recent view must not 500 (the recent_views guild policy would
    # reject a grantee's INSERT; we skip persistence instead).
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/{project.id}/view", headers=headers
    )
    assert resp.status_code == 200, resp.text
