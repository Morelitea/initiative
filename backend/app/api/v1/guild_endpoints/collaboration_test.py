"""Integration tests for the document collaboration HTTP endpoints.

Focused on ``POST /g/{guild_id}/collaboration/documents/{id}/sync-content``,
which the editor fires via a ``keepalive`` fetch on page unload. It shares the
header-less auth of ``/uploads/*`` and downloads (``UploadUserDep``): the
HttpOnly session cookie on web, a short-lived uploads-scoped ``?token=`` on
native. The long-lived session JWT must never authenticate via the URL (SEC-12).
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_upload_token
from app.models.document import (
    Document,
    DocumentPermission,
    DocumentPermissionLevel,
    DocumentType,
)
from app.testing import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
    get_auth_token,
)


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

    perm = DocumentPermission(
        document_id=doc.id,
        user_id=owner.id,
        level=DocumentPermissionLevel.owner,
        guild_id=initiative.guild_id,
    )
    session.add(perm)
    await session.commit()
    return doc


def _sync_url(guild_id: int, document_id: int) -> str:
    return f"/api/v1/g/{guild_id}/collaboration/documents/{document_id}/sync-content"


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
