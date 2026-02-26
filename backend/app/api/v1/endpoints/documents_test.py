"""
Integration tests for document endpoints — create with permissions.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.document import Document, DocumentPermission, DocumentPermissionLevel, DocumentType
from app.models.guild import GuildRole
from app.models.initiative import InitiativeRoleModel
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    get_auth_headers,
    get_auth_token,
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
) -> Document:
    """Create a file-type Document with a dummy file on disk and owner permission."""
    file_path = _uploads_dir() / filename
    file_path.write_bytes(b"%PDF-1.4 test")

    doc = Document(
        title="Test File Doc",
        initiative_id=initiative.id,
        guild_id=initiative.guild_id,
        created_by_id=owner.id,
        updated_by_id=owner.id,
        document_type=DocumentType.file,
        file_url=f"/uploads/{filename}",
        original_filename=filename,
        file_content_type="application/pdf",
        file_size=13,
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


@pytest.mark.integration
async def test_create_document_with_permissions(
    client: AsyncClient, session: AsyncSession
):
    """Test creating a document with both role and user permissions."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)

    initiative = await create_initiative(session, guild, admin, name="Test Initiative")
    await create_initiative_member(session, initiative, member, role_name="member")

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc With Permissions",
        "initiative_id": initiative.id,
        "role_permissions": [
            {"initiative_role_id": member_role.id, "level": "read"},
        ],
        "user_permissions": [
            {"user_id": member.id, "level": "write"},
        ],
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Doc With Permissions"

    # Owner permission exists
    perm_user_ids = {p["user_id"] for p in data["permissions"]}
    assert admin.id in perm_user_ids
    assert member.id in perm_user_ids

    # Role permission exists
    assert len(data["role_permissions"]) == 1
    assert data["role_permissions"][0]["initiative_role_id"] == member_role.id
    assert data["role_permissions"][0]["level"] == "read"

    # Member's user permission is write
    member_perm = next(p for p in data["permissions"] if p["user_id"] == member.id)
    assert member_perm["level"] == "write"


@pytest.mark.integration
async def test_create_document_without_permissions(
    client: AsyncClient, session: AsyncSession
):
    """Test creating a document without extra permissions yields only owner."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative = await create_initiative(session, guild, admin, name="Test Initiative")

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc No Perms",
        "initiative_id": initiative.id,
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    # Only the owner permission should exist
    assert len(data["permissions"]) == 1
    assert data["permissions"][0]["user_id"] == admin.id
    assert data["permissions"][0]["level"] == "owner"
    assert len(data["role_permissions"]) == 0


@pytest.mark.integration
async def test_create_document_rejects_foreign_initiative_role(
    client: AsyncClient, session: AsyncSession
):
    """Role from a different initiative must be silently dropped."""
    admin = await create_user(session, email="admin@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)

    initiative_a = await create_initiative(session, guild, admin, name="Initiative A")
    initiative_b = await create_initiative(session, guild, admin, name="Initiative B")

    # Get a role that belongs to initiative_b, not initiative_a
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative_b.id,
            InitiativeRoleModel.name == "member",
        )
    )
    foreign_role = result.one()

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc Cross Initiative",
        "initiative_id": initiative_a.id,
        "role_permissions": [
            {"initiative_role_id": foreign_role.id, "level": "read"},
        ],
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    # Foreign role must have been silently dropped
    assert len(data["role_permissions"]) == 0


@pytest.mark.integration
async def test_create_document_skips_owner_level_grants(
    client: AsyncClient, session: AsyncSession
):
    """Owner-level grants in user_permissions must be silently ignored."""
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session)
    await create_guild_membership(session, user=admin, guild=guild, role=GuildRole.admin)
    await create_guild_membership(session, user=member, guild=guild)
    initiative = await create_initiative(session, guild, admin, name="Test Initiative")
    await create_initiative_member(session, initiative, member, role_name="member")

    headers = get_guild_headers(guild, admin)
    payload = {
        "title": "Doc Owner Skip",
        "initiative_id": initiative.id,
        "user_permissions": [{"user_id": member.id, "level": "owner"}],
    }

    response = await client.post("/api/v1/documents/", headers=headers, json=payload)

    assert response.status_code == 201
    member_perms = [p for p in response.json()["permissions"] if p["user_id"] == member.id]
    assert len(member_perms) == 0


# ---------------------------------------------------------------------------
# Download endpoint tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_download_owner_can_download(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Document owner can download their file document."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)

    doc = await _create_file_document(session, initiative=initiative, owner=owner, filename="dl_owner.pdf")
    try:
        headers = get_auth_headers(owner)
        response = await client.get(f"/api/v1/documents/{doc.id}/download", headers=headers)
        assert response.status_code == 200
        assert "attachment" in response.headers.get("content-disposition", "")
        assert response.headers.get("x-content-type-options") == "nosniff"
    finally:
        (_uploads_dir() / "dl_owner.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_unauthenticated_returns_401(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Unauthenticated request returns 401."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)

    doc = await _create_file_document(session, initiative=initiative, owner=owner, filename="dl_unauth.pdf")
    try:
        response = await client.get(f"/api/v1/documents/{doc.id}/download")
        assert response.status_code == 401
    finally:
        (_uploads_dir() / "dl_unauth.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_guild_member_without_permission_returns_403(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Guild member with no document permission gets 403."""
    owner = await create_user(session)
    other = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=other, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, other)

    doc = await _create_file_document(session, initiative=initiative, owner=owner, filename="dl_no_perm.pdf")
    try:
        headers = get_auth_headers(other)
        response = await client.get(f"/api/v1/documents/{doc.id}/download", headers=headers)
        assert response.status_code == 403
    finally:
        (_uploads_dir() / "dl_no_perm.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_non_guild_member_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """User from a different guild gets 404 (document not visible)."""
    owner = await create_user(session)
    outsider = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)

    doc = await _create_file_document(session, initiative=initiative, owner=owner, filename="dl_outsider.pdf")
    try:
        headers = get_auth_headers(outsider)
        response = await client.get(f"/api/v1/documents/{doc.id}/download", headers=headers)
        assert response.status_code == 404
    finally:
        (_uploads_dir() / "dl_outsider.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_read_permission_grants_access(
    client: AsyncClient, session: AsyncSession
) -> None:
    """User with explicit read permission can download."""
    owner = await create_user(session)
    reader = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    await create_guild_membership(session, user=reader, guild=guild)
    initiative = await create_initiative(session, guild, owner)
    await create_initiative_member(session, initiative, reader)

    doc = await _create_file_document(session, initiative=initiative, owner=owner, filename="dl_reader.pdf")
    read_perm = DocumentPermission(
        document_id=doc.id,
        user_id=reader.id,
        level=DocumentPermissionLevel.read,
        guild_id=guild.id,
    )
    session.add(read_perm)
    await session.commit()

    try:
        headers = get_auth_headers(reader)
        response = await client.get(f"/api/v1/documents/{doc.id}/download", headers=headers)
        assert response.status_code == 200
    finally:
        (_uploads_dir() / "dl_reader.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_inline_returns_no_attachment_header(
    client: AsyncClient, session: AsyncSession
) -> None:
    """?inline=1 serves the file without Content-Disposition: attachment."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)

    doc = await _create_file_document(session, initiative=initiative, owner=owner, filename="dl_inline.pdf")
    try:
        headers = get_auth_headers(owner)
        response = await client.get(f"/api/v1/documents/{doc.id}/download?inline=1", headers=headers)
        assert response.status_code == 200
        assert "attachment" not in response.headers.get("content-disposition", "")
    finally:
        (_uploads_dir() / "dl_inline.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_query_token_auth(
    client: AsyncClient, session: AsyncSession
) -> None:
    """?token= query param auth works (for native WebViews)."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)

    doc = await _create_file_document(session, initiative=initiative, owner=owner, filename="dl_token.pdf")
    try:
        token = get_auth_token(owner)
        response = await client.get(f"/api/v1/documents/{doc.id}/download?token={token}")
        assert response.status_code == 200
    finally:
        (_uploads_dir() / "dl_token.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_native_document_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Native (non-file) document returns 404 from the download endpoint."""
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild)
    initiative = await create_initiative(session, guild, owner)

    headers = get_guild_headers(guild, owner)
    response = await client.post(
        "/api/v1/documents/",
        headers=headers,
        json={"title": "Native Doc", "initiative_id": initiative.id},
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    response = await client.get(f"/api/v1/documents/{doc_id}/download", headers=get_auth_headers(owner))
    assert response.status_code == 404
