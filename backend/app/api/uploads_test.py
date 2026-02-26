"""Integration tests for authenticated /uploads/* file serving."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    get_auth_token,
)


def _uploads_dir() -> Path:
    path = Path(settings.UPLOADS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.integration
async def test_upload_unauthenticated_returns_401(client: AsyncClient) -> None:
    """GET /uploads/<file> without any auth token returns 401."""
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_security_unauth.txt"
    test_file.write_text("secret")
    try:
        response = await client.get("/uploads/test_security_unauth.txt")
        assert response.status_code == 401
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_accessible_with_auth_header(
    client: AsyncClient, session: AsyncSession
) -> None:
    """GET /uploads/<file> with Authorization Bearer header returns 200."""
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_auth_header.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        headers = get_auth_headers(user)
        response = await client.get("/uploads/test_auth_header.txt", headers=headers)
        assert response.status_code == 200
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_accessible_with_query_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    """GET /uploads/<file>?token=<jwt> returns 200."""
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_query_token.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        token = get_auth_token(user)
        response = await client.get(f"/uploads/test_query_token.txt?token={token}")
        assert response.status_code == 200
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_missing_file_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """GET /uploads/<nonexistent> with valid auth returns 404."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    response = await client.get("/uploads/does_not_exist_xyz.txt", headers=headers)
    assert response.status_code == 404


@pytest.mark.integration
async def test_upload_path_traversal_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Path traversal via ../ is rejected with 404."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    response = await client.get("/uploads/../app/core/config.py", headers=headers)
    assert response.status_code == 404


@pytest.mark.integration
async def test_upload_guild_member_can_access_file(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Authenticated guild member can access a file uploaded by that guild."""
    from app.models.upload import Upload

    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_guild_access.png"
    test_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)  # minimal PNG header
    try:
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)

        upload = Upload(
            filename="test_guild_access.png",
            guild_id=guild.id,
            uploader_user_id=user.id,
            size_bytes=16,
        )
        session.add(upload)
        await session.commit()

        headers = {**get_auth_headers(user), "X-Guild-ID": str(guild.id)}
        response = await client.get("/uploads/test_guild_access.png", headers=headers)
        assert response.status_code == 200
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_non_member_cannot_access_file(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Authenticated user NOT in the owning guild gets 403."""
    from app.models.upload import Upload

    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_guild_forbidden.png"
    test_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    try:
        owner = await create_user(session)
        guild = await create_guild(session, creator=owner)
        await create_guild_membership(session, user=owner, guild=guild)

        upload = Upload(
            filename="test_guild_forbidden.png",
            guild_id=guild.id,
            uploader_user_id=owner.id,
            size_bytes=16,
        )
        session.add(upload)
        await session.commit()

        # A second user not in that guild
        outsider = await create_user(session)
        headers = get_auth_headers(outsider)
        response = await client.get("/uploads/test_guild_forbidden.png", headers=headers)
        assert response.status_code == 403
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_legacy_file_accessible_to_any_authenticated_user(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A file with no DB record (legacy) is accessible to any authenticated user."""
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_legacy_file.txt"
    test_file.write_text("legacy content")
    try:
        user = await create_user(session)
        headers = get_auth_headers(user)
        response = await client.get("/uploads/test_legacy_file.txt", headers=headers)
        assert response.status_code == 200
    finally:
        test_file.unlink(missing_ok=True)
