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
from app.models.tenant.document import (
    Document,
    DocumentType,
)
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
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


async def _create_native_document(
    session: AsyncSession,
    *,
    initiative,
    owner,
) -> Document:
    """Create a native (Lexical) document with owner write permission."""
    doc = Document(
        title="Sync Target",
        initiative_id=initiative.id,
        guild_id=initiative.guild_id,
        created_by_id=owner.id,
        updated_by_id=owner.id,
        document_type=DocumentType.native,
        content={"root": {"children": []}},
    )
    session.add(doc)
    await session.flush()

    perm = ResourceGrant(
        resource_type="document",
        resource_id=doc.id,
        user_id=owner.id,
        level=ResourceAccessLevel.owner,
        guild_id=initiative.guild_id,
        initiative_id=doc.initiative_id,
    )
    session.add(perm)
    await session.commit()
    return doc


def _sync_url(guild_id: int, document_id: int) -> str:
    return f"/api/v1/g/{guild_id}/collaboration/documents/{document_id}/sync-content"


@pytest.mark.integration
async def test_collaboration_guild_admin_gets_full_access(
    session: AsyncSession,
) -> None:
    """A guild admin must get full collaboration access to a restricted document
    they hold no grant on and aren't an initiative member of — mirroring the REST
    guild-admin bypass. The collaboration paths resolve access straight through
    the shared DAC engine (``compute_document_permission``), whose
    ``is_request_guild_admin`` check reads the active guild-role context that
    ``establish_guild_access`` records. Without that context the admin is wrongly
    denied — the original "access denied" bug."""
    owner = await create_user(session, email="owner@example.com")
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    # admin is deliberately NOT a member of this initiative and holds no grant.
    initiative = await create_initiative(session, guild, owner)
    doc = await _create_native_document(session, initiative=initiative, owner=owner)
    document = await _get_document_with_permissions(session, doc.id, guild.id)

    set_active_grant(None, None)

    # No active guild-role context (what a hand-rolled handler that forgot to set
    # it would leave): the admin holds no grant and isn't an initiative member, so
    # the engine resolves no access.
    set_active_role(None, None)
    assert permissions_service.compute_document_permission(document, admin.id) is None

    # With the guild-admin role recorded — as establish_guild_access now does for
    # every transport — the engine's guild-admin bypass returns full ("owner")
    # access.
    set_active_role(guild.id, GuildRole.admin.value)
    try:
        assert (
            permissions_service.compute_document_permission(document, admin.id)
            == "owner"
        )
    finally:
        set_active_role(None, None)


@pytest.mark.integration
async def test_sync_content_scoped_upload_token_persists(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A short-lived, uploads-scoped ?token= authenticates the sync (the
    credential native WebViews carry in the URL) and the content is written."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    doc = await _create_native_document(session, initiative=initiative, owner=owner)

    token, _ = create_upload_token(user_id=owner.id)
    new_content = {"root": {"children": [{"type": "paragraph"}]}}
    response = await client.post(
        f"{_sync_url(guild.id, doc.id)}?token={token}",
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
    client: AsyncClient, session: AsyncSession
) -> None:
    """The long-lived session JWT must NOT authenticate the sync via ?token=
    (it would leak a full-API credential through the URL). SEC-12."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    doc = await _create_native_document(session, initiative=initiative, owner=owner)

    session_jwt = get_auth_token(owner)
    response = await client.post(
        f"{_sync_url(guild.id, doc.id)}?token={session_jwt}",
        json={"root": {"children": []}},
    )

    assert response.status_code == 401


@pytest.mark.integration
async def test_sync_content_rejects_non_member(
    client: AsyncClient, session: AsyncSession
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
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    doc = await _create_native_document(session, initiative=initiative, owner=owner)

    outsider = await create_user(session)
    token, _ = create_upload_token(user_id=outsider.id)
    response = await client.post(
        f"{_sync_url(guild.id, doc.id)}?token={token}",
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
    client: AsyncClient, session: AsyncSession
) -> None:
    """A platform admin (``data.bypass``) who is NOT a guild member but holds a
    live ``read_write`` break-glass grant can sync — ``establish_guild_access``
    elevates them to a full guild admin for the grant's window. The
    pre-consolidation handler did a membership-only check and would have rejected
    this; routing through the single entry point gains break-glass for free."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    doc = await _create_native_document(session, initiative=initiative, owner=owner)

    # data.bypass platform admin, deliberately NOT a member of this guild —
    # reaches it only through the break-glass grant.
    bg_admin = await create_user(session, role=UserRole.admin)
    await _approved_grant(
        session, user=bg_admin, guild=guild, owner=owner, level="read_write"
    )

    token, _ = create_upload_token(user_id=bg_admin.id)
    new_content = {"root": {"children": [{"type": "paragraph"}]}}
    response = await client.post(
        f"{_sync_url(guild.id, doc.id)}?token={token}",
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
    client: AsyncClient, session: AsyncSession
) -> None:
    """A scoped PAM *read* grantee (no ``data.bypass``, not a member) can reach
    the guild but not edit it: sync returns the soft ``No write access`` error,
    distinct from ``No guild access``. Confirms the grant's read/write scope
    flows through the single entry point to the per-document check — the handler
    no longer rejects non-members outright (it used to be membership-only)."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    doc = await _create_native_document(session, initiative=initiative, owner=owner)

    # Platform member (no data.bypass) → a read grant is a scoped PAM grant.
    grantee = await create_user(session)
    await _approved_grant(session, user=grantee, guild=guild, owner=owner, level="read")

    token, _ = create_upload_token(user_id=grantee.id)
    response = await client.post(
        f"{_sync_url(guild.id, doc.id)}?token={token}",
        json={"root": {"children": [{"type": "paragraph"}]}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "No write access"}
