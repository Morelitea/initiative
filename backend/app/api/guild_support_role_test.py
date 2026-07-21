"""Tests for the ``support`` guild role — the first-class identity a scoped
PAM grantee assumes inside a guild it isn't a member of.

Covers:
- the resolver synthesizes ``support`` for a scoped grant and ``admin`` for a
  break-glass grant (identity);
- the guild settings surface (guild AI settings) is reachable by ``support``,
  bound by the grant's read/write level at the Postgres role layer (carve-out);
- ``support`` is never an assignable stored membership role.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import _load_guild_context
from app.core.messages import GuildMessages
from app.models.platform.access_grant import AccessGrant
from app.models.platform.guild import GuildMembership, GuildRole
from app.models.platform.user import UserRole
from app.testing import (
    create_guild,
    create_user,
    get_auth_headers,
)

pytestmark = pytest.mark.integration

AI_SETTINGS = "/ai/guild"


async def _live_grant(
    session: AsyncSession, *, user, guild, level: str = "read"
) -> AccessGrant:
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


def _ai_url(guild_id: int) -> str:
    return f"/api/v1/g/{guild_id}/settings{AI_SETTINGS}"


async def _materialize_ai_settings(client: AsyncClient, guild_id: int, admin) -> None:
    """The AI-settings row is lazily created on first read. Production seeds it
    at guild creation; the test factory doesn't, so a read grant (routed into
    the SELECT-only role) can't create it. Materialize it via an admin read
    first so the support-read path is a pure SELECT."""
    resp = await client.get(_ai_url(guild_id), headers=get_auth_headers(admin))
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# identity: which role the resolver synthesizes
# ---------------------------------------------------------------------------


async def test_scoped_grant_synthesizes_support_role(session: AsyncSession):
    """A scoped PAM grant (support/moderator's request→approve flow, no
    data.bypass) resolves to the ``support`` role, not a ``member`` masquerade."""
    owner = await create_user(session, role=UserRole.owner)
    guild = await create_guild(session, creator=owner)
    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=guild, level="read")

    ctx = await _load_guild_context(session, support, guild.id)
    assert ctx.role == GuildRole.support
    assert ctx.is_pam is True
    assert ctx.break_glass is False


async def test_break_glass_stays_admin_not_support(session: AsyncSession):
    """A read_write break-glass grant (data.bypass holder) still resolves to the
    full ``admin`` role — break-glass is deliberately unlimited."""
    admin = await create_user(session, role=UserRole.operator)
    other = await create_user(session, role=UserRole.owner)
    guild2 = await create_guild(session, creator=other)  # admin is NOT a member
    await _live_grant(session, user=admin, guild=guild2, level="read_write")

    ctx = await _load_guild_context(session, admin, guild2.id)
    assert ctx.role == GuildRole.admin
    assert ctx.break_glass is True


# ---------------------------------------------------------------------------
# settings carve-out: support reaches guild settings, bound by read/write
# ---------------------------------------------------------------------------


async def test_support_read_grant_reads_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A support (read) grantee can READ the guild settings surface."""
    admin = await acting_user(guild_role=GuildRole.admin)
    await _materialize_ai_settings(client, admin.guild.id, admin.user)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read")

    resp = await client.get(_ai_url(admin.guild.id), headers=get_auth_headers(support))
    assert resp.status_code == 200, resp.text


async def test_support_read_grant_cannot_write_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A support (read) grantee is routed into the SELECT-only role, so a
    settings WRITE is denied at the database layer → generic 403."""
    admin = await acting_user(guild_role=GuildRole.admin)
    await _materialize_ai_settings(client, admin.guild.id, admin.user)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read")

    resp = await client.put(
        _ai_url(admin.guild.id),
        headers=get_auth_headers(support),
        json={"enabled": True},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == GuildMessages.GUILD_ACCESS_DENIED


async def test_support_read_write_grant_writes_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A support (read_write) grantee — held by a non-bypass user, so NOT
    break-glass — can WRITE the guild settings surface (the guild_<id>_support
    role has UPDATE on guild_settings; a read grant on _ro does not)."""
    admin = await acting_user(guild_role=GuildRole.admin)
    await _materialize_ai_settings(client, admin.guild.id, admin.user)

    support = await create_user(session, role=UserRole.support)
    await _live_grant(session, user=support, guild=admin.guild, level="read_write")

    resp = await client.put(
        _ai_url(admin.guild.id),
        headers=get_auth_headers(support),
        json={"enabled": True},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["enabled"] is True


async def test_plain_member_still_denied_guild_settings(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The widened gate is (admin, support) — a plain member is still denied,
    so the carve-out didn't loosen the surface for ordinary members."""
    a = await acting_user(guild_role=GuildRole.member)
    resp = await client.get(_ai_url(a.guild.id), headers=a.headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == GuildMessages.GUILD_PERMISSION_REQUIRED


# ---------------------------------------------------------------------------
# support is synthesized-only: never an assignable stored role
# ---------------------------------------------------------------------------


async def test_guild_admin_cannot_assign_support_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The member-facing role endpoint rejects ``support`` (it would otherwise
    hit the guild_role enum, which has only admin/member)."""
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    resp = await client.patch(
        f"/api/v1/guilds/{admin.guild.id}/members/{member.user.id}",
        headers=admin.headers,
        json={"role": "support"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == GuildMessages.GUILD_ROLE_NOT_ASSIGNABLE


async def test_platform_admin_cannot_assign_support_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The platform-admin role endpoint rejects ``support`` too."""
    owner = await create_user(session, role=UserRole.owner)
    target = await acting_user(guild_role=GuildRole.member)

    resp = await client.patch(
        f"/api/v1/admin/guilds/{target.guild.id}/members/{target.user.id}/role",
        headers=get_auth_headers(owner),
        json={"role": "support"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == GuildMessages.GUILD_ROLE_NOT_ASSIGNABLE


# ---------------------------------------------------------------------------
# guild role changes: admin-only, and the write runs on the system engine
# ---------------------------------------------------------------------------


async def test_guild_admin_can_promote_member_to_admin(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A guild admin still promotes a member — the role write now runs on the
    system engine (the guild role holds no UPDATE on guild_memberships)."""
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    guild_id = admin.guild.id
    member_user_id = member.user.id

    resp = await client.patch(
        f"/api/v1/guilds/{guild_id}/members/{member_user_id}",
        headers=admin.headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 204

    session.expire_all()
    updated = (
        await session.exec(
            select(GuildMembership).where(
                GuildMembership.guild_id == guild_id,
                GuildMembership.user_id == member_user_id,
            )
        )
    ).one()
    assert updated.role == GuildRole.admin


async def test_plain_member_cannot_change_guild_roles(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A plain member cannot promote anyone — the guild-admin gate holds, and the
    shared guild role no longer has a DB write to fall back on."""
    admin = await acting_user(guild_role=GuildRole.admin)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)
    other = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    resp = await client.patch(
        f"/api/v1/guilds/{admin.guild.id}/members/{other.user.id}",
        headers=member.headers,
        json={"role": "admin"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == GuildMessages.GUILD_ADMIN_REQUIRED
