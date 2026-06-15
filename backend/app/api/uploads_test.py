"""Integration tests for authenticated /uploads/* file serving."""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.security import create_upload_token
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_user,
    get_auth_headers,
    get_auth_token,
    get_guild_headers,
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
        response = await client.get("/uploads/1/test_security_unauth.txt")
        assert response.status_code == 401
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_accessible_with_auth_header(
    client: AsyncClient, session: AsyncSession
) -> None:
    """GET /uploads/<file> with Authorization Bearer header returns 200."""
    from app.models.upload import Upload

    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_auth_header.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)
        session.add(
            Upload(
                filename="test_auth_header.txt",
                guild_id=guild.id,
                uploader_user_id=user.id,
                size_bytes=5,
            )
        )
        await session.commit()

        headers = await get_guild_headers(session, guild, user)
        response = await client.get(
            f"/uploads/{guild.id}/test_auth_header.txt", headers=headers
        )
        assert response.status_code == 200
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_session_jwt_rejected_in_query_param(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The long-lived session JWT must NOT be accepted via ?token= (it would
    leak a full-API credential through logs/history/Referer). SEC-12."""
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_query_session_jwt.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        token = get_auth_token(user)  # full 7-day session JWT
        response = await client.get(
            f"/uploads/1/test_query_session_jwt.txt?token={token}"
        )
        assert response.status_code == 401
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_accessible_with_scoped_upload_token(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A short-lived, uploads-scoped token IS accepted via ?token=. SEC-12."""
    from app.models.upload import Upload

    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_query_upload_token.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        # SEC-6 (merged): files are only served with a matching Upload row and
        # guild membership — the scoped token answers "who", not "may".
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)
        session.add(
            Upload(
                filename="test_query_upload_token.txt",
                guild_id=guild.id,
                uploader_user_id=user.id,
                size_bytes=5,
            )
        )
        await session.commit()
        token, _ = create_upload_token(user_id=user.id)
        response = await client.get(
            f"/uploads/{guild.id}/test_query_upload_token.txt?token={token}",
        )
        assert response.status_code == 200
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_scoped_upload_token_rejected_as_general_api_credential(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A scoped upload token must not authenticate general API calls. SEC-12."""
    user = await create_user(session)
    token, _ = create_upload_token(user_id=user.id)
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.integration
async def test_issue_upload_token_endpoint(
    client: AsyncClient, session: AsyncSession
) -> None:
    """POST /auth/upload-token mints a token that opens /uploads. SEC-12."""
    from app.models.upload import Upload

    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_minted_token.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        # SEC-6 (merged): serving requires a matching Upload row + membership.
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)
        session.add(
            Upload(
                filename="test_minted_token.txt",
                guild_id=guild.id,
                uploader_user_id=user.id,
                size_bytes=5,
            )
        )
        await session.commit()
        mint = await client.post(
            "/api/v1/auth/upload-token", headers=get_auth_headers(user)
        )
        assert mint.status_code == 200
        body = mint.json()
        assert body["token_type"] == "upload_token"
        assert body["expires_in"] > 0
        token = body["upload_token"]
        response = await client.get(
            f"/uploads/{guild.id}/test_minted_token.txt?token={token}"
        )
        assert response.status_code == 200
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_issue_upload_token_requires_auth(client: AsyncClient) -> None:
    """The mint endpoint itself requires an authenticated session. SEC-12."""
    response = await client.post("/api/v1/auth/upload-token")
    assert response.status_code == 401


@pytest.mark.integration
async def test_upload_missing_file_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """GET /uploads/<nonexistent> with valid auth returns 404."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    response = await client.get("/uploads/1/does_not_exist_xyz.txt", headers=headers)
    assert response.status_code == 404


@pytest.mark.integration
async def test_upload_path_traversal_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Path traversal via ../ is rejected with 404."""
    user = await create_user(session)
    headers = get_auth_headers(user)
    response = await client.get("/uploads/1/../app/core/config.py", headers=headers)
    # The client collapses ``1/..``, so the guild segment becomes a non-int (422);
    # a ``..`` that did reach the handler would fail the uploads-dir containment
    # check (404). Either way the escape is rejected and the file is never served.
    assert response.status_code in (404, 422)


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

        headers = await get_guild_headers(session, guild, user)
        response = await client.get(
            f"/uploads/{guild.id}/test_guild_access.png", headers=headers
        )
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

        # A second user not in that guild — addressing the guild's upload
        # path is still rejected, since membership is validated per request
        # against the path-addressed guild.
        outsider = await create_user(session)
        headers = await get_guild_headers(session, guild, outsider)
        response = await client.get(
            f"/uploads/{guild.id}/test_guild_forbidden.png", headers=headers
        )
        # 404, not 403: existence is never confirmed to non-members,
        # matching the guild-schema lookup path.
        assert response.status_code == 404
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_without_db_record_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A blob on disk with no Upload row fails closed (404), not the bytes.

    Without an Upload row there is no owning guild to authorize against, so
    serving the file would leak it to any authenticated user cross-guild.
    """
    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_orphan_file.txt"
    test_file.write_text("orphan content")
    try:
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)
        headers = await get_guild_headers(session, guild, user)
        response = await client.get(
            f"/uploads/{guild.id}/test_orphan_file.txt", headers=headers
        )
        assert response.status_code == 404
        assert b"orphan content" not in response.content
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_security_headers_on_api_response(client: AsyncClient):
    """Every API response must carry baseline security headers."""
    response = await client.get("/api/v1/auth/bootstrap")
    assert response.status_code == 200
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("x-frame-options") == "DENY"
    assert response.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


@pytest.mark.integration
async def test_upload_row_in_guild_schema_is_served(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Regression: under schema-per-guild, Upload rows written through a guild
    request live in guild_<id>.uploads — NOT public.uploads. The serve route
    runs on the admin session (search_path=public) and must still find the row
    by routing into the requester's ACTIVE guild schema (server-held context),
    otherwise every newly uploaded image 404s (fail-closed SEC-6 turned the
    old silent fail-open into a visible regression)."""
    from sqlalchemy import text

    from app.db.schema_provisioning import guild_schema_name

    uploads_dir = _uploads_dir()
    test_file = uploads_dir / "test_guild_schema_row.txt"
    test_file.write_text("hello")
    try:
        user = await create_user(session)
        guild = await create_guild(session, creator=user)
        await create_guild_membership(session, user=user, guild=guild)
        schema = guild_schema_name(guild.id)
        # Insert the row into the guild schema ONLY (mimicking the production
        # request path, where set_rls_context routes search_path there).
        await session.execute(
            text(
                f'INSERT INTO "{schema}".uploads'
                " (filename, guild_id, uploader_user_id, size_bytes, created_at)"
                " VALUES (:fn, :gid, :uid, 5, now())"
            ),
            {"fn": "test_guild_schema_row.txt", "gid": guild.id, "uid": user.id},
        )
        await session.commit()
        # Prove the row is invisible from public.uploads.
        public_hit = (
            await session.execute(
                text("SELECT 1 FROM public.uploads WHERE filename = :fn"),
                {"fn": "test_guild_schema_row.txt"},
            )
        ).first()
        assert public_hit is None

        response = await client.get(
            f"/uploads/{guild.id}/test_guild_schema_row.txt",
            headers=await get_guild_headers(session, guild, user),
        )
        assert response.status_code == 200
        assert response.text == "hello"

        # A user outside the guild fails membership validation → 404
        # (existence not confirmed), not the file — even with their flag
        # pointed at the guild.
        outsider = await create_user(session, email="outsider-schema@example.com")
        response = await client.get(
            f"/uploads/{guild.id}/test_guild_schema_row.txt",
            headers=await get_guild_headers(session, guild, outsider),
        )
        assert response.status_code == 404
    finally:
        test_file.unlink(missing_ok=True)


@pytest.mark.integration
async def test_app_admin_needs_set_role_for_guild_schema(session, role_session):
    """Regression for the uploads 500 (schema-per-guild grant boundary).

    The serve route runs as ``app_admin``, which has NO grants on a guild
    schema — reading it requires ``SET ROLE`` into the guild role (what
    ``set_rls_context`` does). A raw cross-schema ``SELECT`` as ``app_admin``
    is permission-denied. The default superuser-backed ``session`` fixture
    hides this (it bypasses grants), so this test runs as the REAL role via
    ``role_session``.
    """
    from sqlalchemy import text

    from app.db.schema_provisioning import guild_schema_name
    from app.db.session import set_rls_context
    from app.models.upload import Upload

    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    session.add(
        Upload(
            filename="grant_probe.jpg",
            guild_id=guild.id,
            uploader_user_id=user.id,
            size_bytes=1,
        )
    )
    await session.commit()

    admin = await role_session("app_admin")
    schema = guild_schema_name(guild.id)

    # Raw cross-schema read as app_admin → permission denied (the old bug).
    with pytest.raises(Exception) as exc:  # asyncpg InsufficientPrivilegeError
        await admin.execute(
            text(f'SELECT 1 FROM "{schema}".uploads LIMIT 1')  # noqa: S608
        )
    assert "permission denied" in str(exc.value).lower()
    await admin.rollback()

    # The production pattern (SET ROLE via set_rls_context) succeeds.
    await set_rls_context(admin, guild_id=guild.id, is_superadmin=True)
    row = (
        await admin.execute(
            text("SELECT filename FROM uploads WHERE filename = 'grant_probe.jpg'")
        )
    ).first()
    assert row is not None
