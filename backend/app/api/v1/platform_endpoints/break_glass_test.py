"""End-to-end tests for the break-glass path (Phase 3).

``data.bypass`` is repurposed from a standing all-guild bypass into the right to
self-issue a scoped, time-bound, audited PAM grant. These tests prove:

* an admin/owner can self-issue a grant in one step (created + approved);
* a non-``data.bypass`` user cannot;
* the standing reach is gone — an admin reaches a guild's data ONLY after
  clicking through break-glass (the Phase 3 smoke test);
* the grant is the audit trail (requester == approver) and is read-only by
  default, short-lived, and non-stacking.
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_user,
    get_auth_headers,
)


@pytest.mark.integration
async def test_break_glass_self_issues_live_grant(
    client: AsyncClient, session: AsyncSession
):
    """An admin self-issues a read grant in one step: created AND approved,
    live immediately, with requester == approver as the audit record."""
    owner = await create_user(
        session, email="bg-owner@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)  # admin is NOT a member

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "prod incident #42"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    grant = resp.json()
    assert grant["status"] == "approved"
    assert grant["is_live"] is True
    assert grant["access_level"] == "read"  # read-only by default
    assert grant["expires_at"] is not None
    assert grant["user_id"] == admin.id
    assert grant["requested_by_id"] == admin.id
    assert grant["approved_by_id"] == admin.id  # self-approved = the audit trail


@pytest.mark.integration
async def test_break_glass_requires_data_bypass(
    client: AsyncClient, session: AsyncSession
):
    """Lower tiers (support/moderator) lack ``data.bypass`` and must go through
    the request→approve flow instead — break-glass is 403 for them."""
    owner = await create_user(
        session, email="bg-owner2@example.com", role=UserRole.owner
    )
    support = await create_user(
        session, email="bg-support2@example.com", role=UserRole.support
    )
    guild = await create_guild(session, creator=owner)

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "no bypass"},
        headers=get_auth_headers(support),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
async def test_admin_reaches_guild_only_after_clicking_through(
    client: AsyncClient, session: AsyncSession
):
    """THE Phase 3 smoke test: a platform admin with ``data.bypass`` has NO
    standing reach into a guild's data — they get 403 until they break glass,
    then the same request succeeds via the scoped PAM grant."""
    owner = await create_user(
        session, email="bg-owner3@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin3@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)
    await create_initiative(session, guild, owner, name="Recon Wing")

    headers = get_auth_headers(admin)

    # BEFORE: no membership, no grant — the standing bypass is gone, so 403.
    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 403, (
        "admin must NOT reach guild data without breaking glass"
    )

    # CLICK THROUGH: self-issue a break-glass grant.
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "investigate Recon Wing"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_live"] is True

    # AFTER: the same request now succeeds, scoped to this one guild.
    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 200, resp.text
    assert any(i["name"] == "Recon Wing" for i in resp.json()), (
        "after break-glass the admin should see the guild's initiatives"
    )


@pytest.mark.integration
async def test_break_glass_read_default_is_read_only(
    client: AsyncClient, session: AsyncSession
):
    """A default (read) break-glass grant cannot write the guild's content —
    RLS scopes it to the read-only guild role."""
    owner = await create_user(
        session, email="bg-owner4@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin4@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner, name="Ops")

    headers = get_auth_headers(admin)
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "read only look"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text

    # Can read...
    resp = await client.get(f"/api/v1/g/{guild.id}/initiatives/", headers=headers)
    assert resp.status_code == 200, resp.text

    # ...but cannot create a project (a write) under the read grant.
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/",
        json={"name": "Should Fail", "initiative_id": init.id},
        headers=headers,
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.integration
async def test_break_glass_read_write_is_full_guild_admin(
    client: AsyncClient, session: AsyncSession
):
    """A read_write break-glass grant is deliberately UNLIMITED: the holder acts
    as a full guild admin — authoring content (create projects) AND managing
    access (project members) — neither of which a regular PAM grant allows."""
    owner = await create_user(
        session, email="bg-owner8@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin8@example.com", role=UserRole.operator
    )
    target = await create_user(session, email="bg-target8@example.com")
    guild = await create_guild(session, creator=owner)
    init = await create_initiative(session, guild, owner, name="War Room")
    project = await create_project(session, init, owner, name="Existing")

    headers = get_auth_headers(admin)
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={
            "guild_id": guild.id,
            "access_level": "read_write",
            "reason": "full incident response",
        },
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["access_level"] == "read_write"

    # Authoring: create a new project (regular read_write PAM cannot do this).
    resp = await client.post(
        f"/api/v1/g/{guild.id}/projects/",
        json={"name": "New Front", "initiative_id": init.id},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    # Management: change project access (a regular grant is blocked with
    # PROJECT_GRANT_CANNOT_MANAGE_MEMBERS — break-glass has no limits).
    resp = await client.put(
        f"/api/v1/g/{guild.id}/projects/{project.id}/grants",
        json=[{"user_id": target.id, "level": "write"}],
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.integration
async def test_break_glass_already_member_rejected(
    client: AsyncClient, session: AsyncSession
):
    """An admin who is a real member of the guild already has standing access —
    break-glass is rejected as redundant."""
    owner = await create_user(
        session, email="bg-owner5@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin5@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)
    # The admin is a real member of this guild already.
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.member
    )

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "already in"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_ALREADY_MEMBER"


@pytest.mark.integration
async def test_break_glass_duration_capped(client: AsyncClient, session: AsyncSession):
    """A self-approved grant is capped at the (short) break-glass ceiling,
    below the role's request→approve maximum."""
    owner = await create_user(
        session, email="bg-owner6@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin6@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)

    # 24h is within the admin's request→approve cap but over break-glass (4h).
    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={
            "guild_id": guild.id,
            "reason": "too long",
            "requested_duration_minutes": 1440,
        },
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_DURATION_TOO_LONG"


@pytest.mark.integration
async def test_break_glass_overlapping_live_rejected(
    client: AsyncClient, session: AsyncSession
):
    """A second break-glass while one is still live is rejected (no stacking);
    re-trigger only after the current grant ends."""
    owner = await create_user(
        session, email="bg-owner7@example.com", role=UserRole.owner
    )
    admin = await create_user(
        session, email="bg-admin7@example.com", role=UserRole.operator
    )
    guild = await create_guild(session, creator=owner)

    body = {"guild_id": guild.id, "reason": "first"}
    resp = await client.post(
        "/api/v1/access-grants/break-glass", json=body, headers=get_auth_headers(admin)
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post(
        "/api/v1/access-grants/break-glass",
        json={"guild_id": guild.id, "reason": "second"},
        headers=get_auth_headers(admin),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "ACCESS_GRANT_ALREADY_LIVE"
