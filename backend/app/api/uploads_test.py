"""Integration tests for authenticated /uploads/* file serving."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.testing.factories import create_user, get_auth_headers, get_auth_token


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
