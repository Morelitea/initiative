"""Integration tests for the document collaboration HTTP endpoints.

Focused on ``POST /g/{guild_id}/collaboration/documents/{id}/sync-content``,
which the editor fires via a ``keepalive`` fetch on page unload. It shares the
header-less auth of ``/uploads/*`` and downloads (``UploadUserDep``): the
HttpOnly session cookie on web, a short-lived uploads-scoped ``?token=`` on
native. The long-lived session JWT must never authenticate via the URL (SEC-12).
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_upload_token
from app.models.platform.access_grant import AccessGrant
from app.models.tenant.document import Document
from app.testing import (
    create_document,
    create_user,
    get_auth_token,
)
from app.api.v1.tenant_endpoints.collaboration import (
    _get_document_with_permissions,
)
from app.core.pam_context import set_active_grant
from app.core.role_context import set_active_role
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.services import permissions as permissions_service


def _sync_url(guild_id: int, document_id: int) -> str:
    return f"/api/v1/g/{guild_id}/collaboration/documents/{document_id}/sync-content"


@pytest.mark.integration
async def test_collaboration_guild_admin_gets_full_access(
    session: AsyncSession, acting_user
) -> None:
    """A guild admin must get full collaboration access to a restricted document
    they hold no grant on and aren't an initiative member of — mirroring the REST
    guild-admin bypass. The collaboration paths resolve access straight through
    the shared DAC engine (``compute_document_permission``), whose
    ``is_request_guild_admin`` check reads the active guild-role context that
    ``establish_guild_access`` records. Without that context the admin is wrongly
    denied — the original "access denied" bug."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    # admin is deliberately NOT a member of this initiative and holds no grant.
    admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)
    doc = await create_document(session, owner.initiative, owner.user)
    document = await _get_document_with_permissions(session, doc.id, owner.guild.id)

    set_active_grant(None, None)

    # No active guild-role context (what a hand-rolled handler that forgot to set
    # it would leave): the admin holds no grant and isn't an initiative member, so
    # the engine resolves no access.
    set_active_role(None, None)
    assert (
        permissions_service.compute_document_permission(document, admin.user.id) is None
    )

    # With the guild-admin role recorded — as establish_guild_access now does for
    # every transport — the engine's guild-admin bypass returns full ("owner")
    # access.
    set_active_role(owner.guild.id, GuildRole.admin.value)
    try:
        assert (
            permissions_service.compute_document_permission(document, admin.user.id)
            == "owner"
        )
    finally:
        set_active_role(None, None)


@pytest.mark.integration
async def test_sync_content_scoped_upload_token_persists(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A short-lived, uploads-scoped ?token= authenticates the sync (the
    credential native WebViews carry in the URL) and the content is written."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    token, _ = create_upload_token(user_id=owner.user.id)
    new_content = {"root": {"children": [{"type": "paragraph"}]}}
    response = await client.post(
        f"{_sync_url(owner.guild.id, doc.id)}?token={token}",
        json=new_content,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    refreshed = (
        await session.exec(select(Document).where(Document.id == doc.id))
    ).one()
    assert refreshed.content == new_content


@pytest.mark.integration
async def test_sync_content_session_jwt_rejected_in_query_param(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """The long-lived session JWT must NOT authenticate the sync via ?token=
    (it would leak a full-API credential through the URL). SEC-12."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    session_jwt = get_auth_token(owner.user)
    response = await client.post(
        f"{_sync_url(owner.guild.id, doc.id)}?token={session_jwt}",
        json={"root": {"children": []}},
    )

    assert response.status_code == 401


@pytest.mark.integration
async def test_sync_content_rejects_non_member(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A validly-authenticated user who is not a member of the path guild can't
    sync into it — the guild boundary holds independent of how auth arrived.

    Note the 200-with-error-body (not a 403): this endpoint fires from a
    page-unload ``keepalive`` fetch whose response the client never reads, so
    every app-level failure (bad JSON, no guild access, not found, no write
    access) reports a soft ``{"status": "error"}`` rather than an HTTP error.
    That contract predates this change and is deliberately preserved. Only
    *authentication* now hard-fails (401), because that is enforced by the
    ``UploadUserDep`` dependency before the handler runs.
    """
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    outsider = await create_user(session)
    token, _ = create_upload_token(user_id=outsider.id)
    response = await client.post(
        f"{_sync_url(owner.guild.id, doc.id)}?token={token}",
        json={"root": {"children": []}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "No guild access"}


async def _approved_grant(session, *, user, guild, owner, level: str) -> AccessGrant:
    """An approved, currently-live access grant for ``user`` on ``guild``."""
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=level,
        status="approved",
        reason="test",
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
async def test_sync_content_break_glass_admin_can_write(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A platform admin (``data.bypass``) who is NOT a guild member but holds a
    live ``read_write`` break-glass grant can sync — ``establish_guild_access``
    elevates them to a full guild admin for the grant's window. The
    pre-consolidation handler did a membership-only check and would have rejected
    this; routing through the single entry point gains break-glass for free."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    # data.bypass platform admin, deliberately NOT a member of this guild —
    # reaches it only through the break-glass grant.
    bg_admin = await create_user(session, role=UserRole.operator)
    await _approved_grant(
        session, user=bg_admin, guild=owner.guild, owner=owner.user, level="read_write"
    )

    token, _ = create_upload_token(user_id=bg_admin.id)
    new_content = {"root": {"children": [{"type": "paragraph"}]}}
    response = await client.post(
        f"{_sync_url(owner.guild.id, doc.id)}?token={token}",
        json=new_content,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    refreshed = (
        await session.exec(select(Document).where(Document.id == doc.id))
    ).one()
    assert refreshed.content == new_content


@pytest.mark.integration
async def test_sync_content_pam_read_grant_cannot_write(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A scoped PAM *read* grantee (no ``data.bypass``, not a member) can reach
    the guild but not edit it: sync returns the soft ``No write access`` error,
    distinct from ``No guild access``. Confirms the grant's read/write scope
    flows through the single entry point to the per-document check — the handler
    no longer rejects non-members outright (it used to be membership-only)."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    # Platform member (no data.bypass) → a read grant is a scoped PAM grant.
    grantee = await create_user(session)
    await _approved_grant(
        session, user=grantee, guild=owner.guild, owner=owner.user, level="read"
    )

    token, _ = create_upload_token(user_id=grantee.id)
    response = await client.post(
        f"{_sync_url(owner.guild.id, doc.id)}?token={token}",
        json={"root": {"children": [{"type": "paragraph"}]}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "No write access"}
