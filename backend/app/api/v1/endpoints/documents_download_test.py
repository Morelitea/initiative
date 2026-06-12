"""
Integration tests for the document download endpoints under schema-per-guild.

Downloads are GUILD-ADDRESSED: per-schema serial ids mean the same document id
can exist in several of a user's guild schemas at once, so a bare id is not a
valid address — ``guild_id`` is a REQUIRED query parameter (the endpoints are
served via iframe/window.open and carry no ``X-Guild-ID`` header). The loader
resolves strictly within the addressed guild, pins ``Document.guild_id`` so the
frozen ``public`` copy can never be served, fails closed for non-members, and
raises 403 (never 404) for unreadable documents.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.document import (
    Document,
    DocumentFileVersion,
    DocumentPermission,
    DocumentPermissionLevel,
    DocumentType,
)
from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_user,
    get_auth_headers,
    get_guild_headers,
)


def _uploads_dir() -> Path:
    path = Path(settings.UPLOADS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _create_file_document(
    session: AsyncSession,
    *,
    initiative,
    owner,
    filename: str,
    content: bytes,
    grant_owner: bool = True,
) -> Document:
    """Create a file-type Document with a real blob on disk in the initiative's
    guild schema. The before_flush routing harness sends the write to
    ``guild_<id>`` because every row carries ``guild_id``.

    When ``grant_owner`` is True the owner gets an owner DocumentPermission; pass
    False to leave the document with no permissions (so a probing user is denied).
    """
    (_uploads_dir() / filename).write_bytes(content)

    doc = Document(
        title=f"File Doc {filename}",
        initiative_id=initiative.id,
        guild_id=initiative.guild_id,
        created_by_id=owner.id,
        updated_by_id=owner.id,
        document_type=DocumentType.file,
        file_url=f"/uploads/{filename}",
        original_filename=filename,
        file_content_type="application/pdf",
        file_size=len(content),
    )
    session.add(doc)
    await session.flush()

    if grant_owner:
        session.add(
            DocumentPermission(
                document_id=doc.id,
                user_id=owner.id,
                level=DocumentPermissionLevel.owner,
                guild_id=initiative.guild_id,
            )
        )
    await session.commit()
    return doc


async def _setup_member_in_two_guilds(session: AsyncSession):
    """Create a user who belongs to guilds A and B, plus a separate owner who
    owns guild A's document. Returns (user, owner_a, guild_a, init_a, guild_b,
    init_b)."""
    user = await create_user(session, email="member@example.com")
    owner_a = await create_user(session, email="ownera@example.com")

    guild_a = await create_guild(session, creator=owner_a, name="Guild A")
    await create_guild_membership(
        session, user=owner_a, guild=guild_a, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=user, guild=guild_a, role=GuildRole.member
    )
    init_a = await create_initiative(session, guild_a, owner_a, name="Init A")

    guild_b = await create_guild(session, creator=user, name="Guild B")
    await create_guild_membership(
        session, user=user, guild=guild_b, role=GuildRole.admin
    )
    init_b = await create_initiative(session, guild_b, user, name="Init B")

    return user, owner_a, guild_a, init_a, guild_b, init_b


A_BYTES = b"%PDF-1.4 guild A private body"
B_BYTES = b"%PDF-1.4 guild B readable body"


@pytest.mark.integration
async def test_download_collision_serves_addressed_guild(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Same doc id in guilds A and B; the user can read only B's doc.

    GET /documents/{id}/download?guild_id=B must serve B's bytes — A's same-id
    doc must play no part in resolution. A guild-less request is rejected
    outright (422): there is no legacy bare-id format.
    """
    user, owner_a, guild_a, init_a, guild_b, init_b = await _setup_member_in_two_guilds(
        session
    )

    # A's doc: owned by owner_a, user has NO permission on it.
    doc_a = await _create_file_document(
        session,
        initiative=init_a,
        owner=owner_a,
        filename="collide_a.pdf",
        content=A_BYTES,
        grant_owner=True,
    )
    # B's doc: owned by user (read/owner access).
    doc_b = await _create_file_document(
        session,
        initiative=init_b,
        owner=user,
        filename="collide_b.pdf",
        content=B_BYTES,
        grant_owner=True,
    )

    # The collision the bug hinges on: per-schema serials give both id 1.
    assert doc_a.id == doc_b.id, "test requires colliding ids across schemas"

    try:
        # No legacy format: a guild-less download URL is not a valid address.
        bare = await client.get(
            f"/api/v1/documents/{doc_b.id}/download", headers=get_auth_headers(user)
        )
        assert bare.status_code == 422

        response = await client.get(
            f"/api/v1/documents/{doc_b.id}/download?guild_id={guild_b.id}",
            headers=get_auth_headers(user),
        )
        assert response.status_code == 200, response.text
        assert response.content == B_BYTES
        assert "collide_b.pdf" in response.headers.get("content-disposition", "")
    finally:
        (_uploads_dir() / "collide_a.pdf").unlink(missing_ok=True)
        (_uploads_dir() / "collide_b.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_explicit_guild_id_inaccessible_forbidden(
    client: AsyncClient, session: AsyncSession
) -> None:
    """?guild_id=A disambiguates to A's doc, which the user cannot read → 403."""
    user, owner_a, guild_a, init_a, guild_b, init_b = await _setup_member_in_two_guilds(
        session
    )
    doc_a = await _create_file_document(
        session,
        initiative=init_a,
        owner=owner_a,
        filename="explicit_a.pdf",
        content=A_BYTES,
        grant_owner=True,
    )
    await _create_file_document(
        session,
        initiative=init_b,
        owner=user,
        filename="explicit_b.pdf",
        content=B_BYTES,
        grant_owner=True,
    )

    try:
        response = await client.get(
            f"/api/v1/documents/{doc_a.id}/download?guild_id={guild_a.id}",
            headers=get_auth_headers(user),
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "DOCUMENT_NO_ACCESS"
    finally:
        (_uploads_dir() / "explicit_a.pdf").unlink(missing_ok=True)
        (_uploads_dir() / "explicit_b.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_explicit_guild_id_accessible_ok(
    client: AsyncClient, session: AsyncSession
) -> None:
    """?guild_id=B disambiguates to B's doc, which the user can read → 200."""
    user, owner_a, guild_a, init_a, guild_b, init_b = await _setup_member_in_two_guilds(
        session
    )
    await _create_file_document(
        session,
        initiative=init_a,
        owner=owner_a,
        filename="ok_a.pdf",
        content=A_BYTES,
        grant_owner=True,
    )
    doc_b = await _create_file_document(
        session,
        initiative=init_b,
        owner=user,
        filename="ok_b.pdf",
        content=B_BYTES,
        grant_owner=True,
    )

    try:
        response = await client.get(
            f"/api/v1/documents/{doc_b.id}/download?guild_id={guild_b.id}",
            headers=get_auth_headers(user),
        )
        assert response.status_code == 200, response.text
        assert response.content == B_BYTES
    finally:
        (_uploads_dir() / "ok_a.pdf").unlink(missing_ok=True)
        (_uploads_dir() / "ok_b.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_explicit_guild_id_non_member_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """?guild_id of a guild the user is NOT a member of fails closed → 404."""
    user, owner_a, guild_a, init_a, guild_b, init_b = await _setup_member_in_two_guilds(
        session
    )
    doc_b = await _create_file_document(
        session,
        initiative=init_b,
        owner=user,
        filename="nonmember_b.pdf",
        content=B_BYTES,
        grant_owner=True,
    )

    # A guild the user has nothing to do with.
    stranger = await create_user(session, email="stranger@example.com")
    other_guild = await create_guild(session, creator=stranger, name="Other Guild")
    await create_guild_membership(
        session, user=stranger, guild=other_guild, role=GuildRole.admin
    )

    try:
        response = await client.get(
            f"/api/v1/documents/{doc_b.id}/download?guild_id={other_guild.id}",
            headers=get_auth_headers(user),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "DOCUMENT_NOT_FOUND"
    finally:
        (_uploads_dir() / "nonmember_b.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_version_download_follows_winner_schema(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A version download under id-collision serves the addressed guild's version.

    A and B both hold a doc with the same id; the request addresses B. The file
    version lives in B's schema — the follow-up DocumentFileVersion query must
    run in B's schema (the resolver leaves the session routed there), not A's.
    """
    user, owner_a, guild_a, init_a, guild_b, init_b = await _setup_member_in_two_guilds(
        session
    )

    # A's inaccessible doc (occupies the same id in A's schema).
    doc_a = await _create_file_document(
        session,
        initiative=init_a,
        owner=owner_a,
        filename="ver_a.pdf",
        content=A_BYTES,
        grant_owner=True,
    )

    # B's doc created through the real upload endpoint so it gets a v1 row + blob.
    upload_resp = await client.post(
        "/api/v1/documents/upload",
        headers=get_guild_headers(guild_b, user),
        data={"title": "B Versioned", "initiative_id": str(init_b.id)},
        files={"file": ("verb_v1.pdf", B_BYTES, "application/pdf")},
    )
    assert upload_resp.status_code == 201, upload_resp.text
    doc_b = upload_resp.json()
    assert doc_a.id == doc_b["id"], "test requires colliding ids across schemas"

    versions = (
        await client.get(
            f"/api/v1/documents/{doc_b['id']}/versions",
            headers=get_guild_headers(guild_b, user),
        )
    ).json()
    v1 = versions[0]

    try:
        response = await client.get(
            f"/api/v1/documents/{doc_b['id']}/versions/{v1['id']}/download"
            f"?guild_id={guild_b.id}",
            headers=get_auth_headers(user),
        )
        assert response.status_code == 200, response.text
        assert response.content == B_BYTES
    finally:
        (_uploads_dir() / "ver_a.pdf").unlink(missing_ok=True)
        for v in (
            await session.exec(
                select(DocumentFileVersion).where(
                    DocumentFileVersion.document_id == doc_b["id"]
                )
            )
        ).all():
            (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)
