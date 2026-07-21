"""
Integration tests for document endpoints — create with permissions.
"""

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.tenant_endpoints.documents import MAX_DOCUMENT_IDS
from app.core.config import settings
from app.core.security import create_upload_token
from app.models.tenant.document import (
    Document,
    DocumentType,
)
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.testing import (
    create_document,
    create_initiative,
    create_user,
    get_auth_headers,
    get_auth_token,
)


def _uploads_dir() -> Path:
    path = Path(settings.UPLOADS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def _isolated_uploads_dir(tmp_path, monkeypatch):
    """Point UPLOADS_DIR at a throwaway dir so staged blobs (now in per-guild
    subdirs) don't litter the repo and never leak across tests."""
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path / "uploads"))


async def _create_file_document(
    session: AsyncSession,
    *,
    initiative,
    owner,
    filename: str,
) -> Document:
    """Create a file-type Document with a dummy file on disk and owner permission."""
    # Stage the blob via the real resolver so it lands where the serve path reads
    # it (UPLOADS_DIR/guild_<id>/), and use the canonical guild-scoped URL.
    from app.services.storage import get_guild_storage

    get_guild_storage(initiative.guild_id).write(filename, b"%PDF-1.4 test")

    doc = Document(
        title="Test File Doc",
        initiative_id=initiative.id,
        guild_id=initiative.guild_id,
        created_by_id=owner.id,
        updated_by_id=owner.id,
        document_type=DocumentType.file,
        file_url=f"/uploads/{initiative.guild_id}/{filename}",
        original_filename=filename,
        file_content_type="application/pdf",
        file_size=13,
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


@pytest.mark.integration
async def test_create_document_with_permissions(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Test creating a document with both role and user permissions."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    initiative = admin.initiative

    # Find the member role
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative.id,
            InitiativeRoleModel.name == "member",
        )
    )
    member_role = result.one()

    payload = {
        "title": "Doc With Permissions",
        "initiative_id": initiative.id,
        "grants": [
            {"role_id": member_role.id, "level": "read"},
            {"user_id": member.user.id, "level": "write"},
        ],
    }

    response = await client.post(
        admin.g("/documents/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Doc With Permissions"

    grants = data["grants"]
    # Owner grant + member's write user grant.
    user_grants = {g["user_id"]: g["level"] for g in grants if g["user_id"]}
    assert user_grants.get(admin.user.id) == "owner"
    assert user_grants.get(member.user.id) == "write"
    # Role grant for the member role at read.
    role_grants = [g for g in grants if g["role_id"] is not None]
    assert len(role_grants) == 1
    assert role_grants[0]["role_id"] == member_role.id
    assert role_grants[0]["level"] == "read"


@pytest.mark.integration
async def test_create_document_defaults_to_all_members_viewer(
    client: AsyncClient, acting_user
):
    """Omitting `grants` defaults to Viewer for all initiative members (+ owner)."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)

    payload = {
        "title": "Doc Default Share",
        "initiative_id": admin.initiative.id,
    }

    response = await client.post(
        admin.g("/documents/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    assert any(
        g["user_id"] == admin.user.id and g["level"] == "owner" for g in data["grants"]
    )
    assert any(
        g["all_initiative_members"] and g["level"] == "read" for g in data["grants"]
    )


@pytest.mark.integration
async def test_create_document_rejects_foreign_initiative_role(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Role from a different initiative must be silently dropped."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    initiative_a = admin.initiative
    initiative_b = await create_initiative(
        session, admin.guild, admin.user, name="Initiative B"
    )

    # Get a role that belongs to initiative_b, not initiative_a
    result = await session.exec(
        select(InitiativeRoleModel).where(
            InitiativeRoleModel.initiative_id == initiative_b.id,
            InitiativeRoleModel.name == "member",
        )
    )
    foreign_role = result.one()

    payload = {
        "title": "Doc Cross Initiative",
        "initiative_id": initiative_a.id,
        "grants": [
            {"role_id": foreign_role.id, "level": "read"},
        ],
    }

    response = await client.post(
        admin.g("/documents/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    data = response.json()
    # Foreign role must have been silently dropped
    assert len([g for g in data["grants"] if g["role_id"] is not None]) == 0


@pytest.mark.integration
async def test_create_document_skips_owner_level_grants(
    client: AsyncClient, acting_user
):
    """Owner-level grants in user_permissions must be silently ignored."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )

    payload = {
        "title": "Doc Owner Skip",
        "initiative_id": admin.initiative.id,
        "grants": [{"user_id": member.user.id, "level": "owner"}],
    }

    response = await client.post(
        admin.g("/documents/"), headers=admin.headers, json=payload
    )

    assert response.status_code == 201
    member_grants = [
        g for g in response.json()["grants"] if g["user_id"] == member.user.id
    ]
    assert len(member_grants) == 0


# ---------------------------------------------------------------------------
# Copy / create-from-template tests
# ---------------------------------------------------------------------------


async def _make_native_doc(
    session: AsyncSession,
    *,
    initiative,
    creator,
    title: str,
    is_template: bool,
) -> Document:
    """Create a native document with creator as owner, optionally a template."""
    return await create_document(
        session,
        initiative,
        creator,
        title=title,
        content={"root": {"type": "root", "children": []}},
        is_template=is_template,
    )


@pytest.mark.integration
async def test_copy_template_with_read_only_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A user with only read on a template can still copy it into a new document."""
    template_owner = await acting_user(guild_role=GuildRole.admin, initiative=True)
    # Reader needs create_documents in the target initiative; PM role grants it by default.
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=template_owner.guild,
        initiative=template_owner.initiative,
        initiative_role="project_manager",
    )
    guild = template_owner.guild
    initiative = template_owner.initiative

    template = await _make_native_doc(
        session,
        initiative=initiative,
        creator=template_owner.user,
        title="Project Kickoff Template",
        is_template=True,
    )
    # Grant reader explicit read-only access on the template.
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=template.id,
            user_id=reader.user.id,
            level=ResourceAccessLevel.read,
            guild_id=guild.id,
            initiative_id=template.initiative_id,
        )
    )
    await session.commit()

    response = await client.post(
        reader.g(f"/documents/{template.id}/copy"),
        headers=reader.headers,
        json={"target_initiative_id": initiative.id, "title": "My Kickoff"},
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["title"] == "My Kickoff"
    assert data["is_template"] is False
    assert data["created_by_id"] == reader.user.id

    # Reader is owner of the new doc.
    new_grant_levels = {
        g["user_id"]: g["level"] for g in data["grants"] if g["user_id"]
    }
    assert new_grant_levels.get(reader.user.id) == "owner"

    # Source template is unchanged.
    await session.refresh(template)
    assert template.is_template is True
    assert template.title == "Project Kickoff Template"


@pytest.mark.integration
async def test_copy_non_template_still_requires_write_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Read-only access on a non-template document is still rejected by /copy."""
    owner = await acting_user(guild_role=GuildRole.admin, initiative=True)
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="project_manager",
    )
    guild = owner.guild
    initiative = owner.initiative

    doc = await _make_native_doc(
        session,
        initiative=initiative,
        creator=owner.user,
        title="Confidential Notes",
        is_template=False,
    )
    session.add(
        ResourceGrant(
            resource_type="document",
            resource_id=doc.id,
            user_id=reader.user.id,
            level=ResourceAccessLevel.read,
            guild_id=guild.id,
            initiative_id=doc.initiative_id,
        )
    )
    await session.commit()

    response = await client.post(
        reader.g(f"/documents/{doc.id}/copy"),
        headers=reader.headers,
        json={"target_initiative_id": initiative.id, "title": "My Copy"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "DOCUMENT_WRITE_ACCESS_REQUIRED"


# ---------------------------------------------------------------------------
# Download endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_download_owner_can_download(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Document owner can download their file document."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_owner.pdf"
    )
    try:
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download"), headers=owner.headers
        )
        assert response.status_code == 200
        assert "attachment" in response.headers.get("content-disposition", "")
        assert response.headers.get("x-content-type-options") == "nosniff"
    finally:
        (_uploads_dir() / "dl_owner.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_unauthenticated_returns_401(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Unauthenticated request returns 401."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_unauth.pdf"
    )
    try:
        response = await client.get(owner.g(f"/documents/{doc.id}/download"))
        assert response.status_code == 401
    finally:
        (_uploads_dir() / "dl_unauth.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_guild_member_without_permission_returns_403(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Guild member with no document permission gets 403."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    other = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    doc = await _create_file_document(
        session,
        initiative=owner.initiative,
        owner=owner.user,
        filename="dl_no_perm.pdf",
    )
    try:
        response = await client.get(
            other.g(f"/documents/{doc.id}/download"), headers=other.headers
        )
        assert response.status_code == 403
    finally:
        (_uploads_dir() / "dl_no_perm.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_non_guild_member_returns_404(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """User from a different guild gets 404 (document not visible)."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    outsider = await create_user(session)

    doc = await _create_file_document(
        session,
        initiative=owner.initiative,
        owner=owner.user,
        filename="dl_outsider.pdf",
    )
    try:
        headers = get_auth_headers(outsider)
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download"), headers=headers
        )
        assert response.status_code == 404
    finally:
        (_uploads_dir() / "dl_outsider.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_read_permission_grants_access(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """User with explicit read permission can download."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    guild = owner.guild

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_reader.pdf"
    )
    read_perm = ResourceGrant(
        resource_type="document",
        resource_id=doc.id,
        user_id=reader.user.id,
        level=ResourceAccessLevel.read,
        guild_id=guild.id,
        initiative_id=doc.initiative_id,
    )
    session.add(read_perm)
    await session.commit()

    try:
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download"), headers=reader.headers
        )
        assert response.status_code == 200
    finally:
        (_uploads_dir() / "dl_reader.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_inline_returns_no_attachment_header(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """?inline=1 serves the file without Content-Disposition: attachment."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_inline.pdf"
    )
    try:
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download?inline=1"),
            headers=owner.headers,
        )
        assert response.status_code == 200
        assert "attachment" not in response.headers.get("content-disposition", "")
    finally:
        (_uploads_dir() / "dl_inline.pdf").unlink(missing_ok=True)


@pytest.mark.integration
@pytest.mark.parametrize("filename", ["dl_inline.html", "dl_inline.svg"])
async def test_download_inline_html_svg_is_same_origin_framable_but_scriptless(
    client: AsyncClient, session: AsyncSession, acting_user, filename: str
) -> None:
    """Inline HTML/SVG can be framed by the same-origin viewer but cannot run scripts."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename=filename
    )
    try:
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download?inline=1"),
            headers=owner.headers,
        )
        assert response.status_code == 200
        # Same-origin framing allowed (overrides the global DENY middleware)
        assert response.headers.get("x-frame-options") == "SAMEORIGIN"
        csp = response.headers.get("content-security-policy", "")
        assert "frame-ancestors 'self'" in csp
        # Stored-XSS hardening preserved: scripts still disabled
        assert "script-src 'none'" in csp
        assert "attachment" not in response.headers.get("content-disposition", "")
    finally:
        (_uploads_dir() / filename).unlink(missing_ok=True)


@pytest.mark.integration
@pytest.mark.parametrize("filename", ["dl_attach.html", "dl_attach.svg"])
async def test_download_non_inline_html_svg_keeps_global_deny(
    client: AsyncClient, session: AsyncSession, acting_user, filename: str
) -> None:
    """Non-inline HTML/SVG downloads stay attachments and do not relax framing."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename=filename
    )
    try:
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download"), headers=owner.headers
        )
        assert response.status_code == 200
        # Served as an attachment; the framing relaxation must not apply here
        assert "attachment" in response.headers.get("content-disposition", "")
        assert response.headers.get("x-frame-options") != "SAMEORIGIN"
        csp = response.headers.get("content-security-policy", "")
        assert "script-src 'none'" in csp
        assert "frame-ancestors" not in csp
    finally:
        (_uploads_dir() / filename).unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_scoped_upload_token_auth(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A short-lived, uploads-scoped ?token= authenticates the download (the
    credential native WebViews carry in the URL). SEC-12."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_token.pdf"
    )
    try:
        token, _ = create_upload_token(user_id=owner.user.id)
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download?token={token}")
        )
        assert response.status_code == 200
    finally:
        (_uploads_dir() / "dl_token.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_session_jwt_rejected_in_query_param(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """The long-lived session JWT must NOT authenticate a download via ?token=
    (it would leak a full-API credential through the URL). SEC-12."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session,
        initiative=owner.initiative,
        owner=owner.user,
        filename="dl_session_jwt.pdf",
    )
    try:
        token = get_auth_token(owner.user)
        response = await client.get(
            owner.g(f"/documents/{doc.id}/download?token={token}")
        )
        assert response.status_code == 401
    finally:
        (_uploads_dir() / "dl_session_jwt.pdf").unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_native_document_returns_404(
    client: AsyncClient, acting_user
) -> None:
    """Native (non-file) document returns 404 from the download endpoint."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={"title": "Native Doc", "initiative_id": owner.initiative.id},
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    response = await client.get(
        owner.g(f"/documents/{doc_id}/download"),
        headers=get_auth_headers(owner.user),
    )
    assert response.status_code == 404


@pytest.mark.integration
async def test_update_content_clears_yjs_state(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """PATCH /documents/{id} with content should clear yjs_state.

    Regression: editing in non-collab mode used to leave a stale yjs_state,
    which then overwrote the freshly-saved content when the user re-enabled
    collaboration (the CollaborationPlugin synced from the old Yjs state).
    """
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    create_resp = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={"title": "Collab Doc", "initiative_id": owner.initiative.id},
    )
    assert create_resp.status_code == 201
    doc_id = create_resp.json()["id"]

    # Simulate a prior collaborative session by writing a stale yjs_state blob
    doc = await session.get(Document, doc_id)
    assert doc is not None
    doc.yjs_state = b"\x00\x01\x02 stale yjs blob"
    session.add(doc)
    await session.commit()

    # PATCH the content via the REST endpoint (the non-collab save path)
    patch_resp = await client.patch(
        owner.g(f"/documents/{doc_id}"),
        headers=owner.headers,
        json={
            "content": {
                "root": {
                    "children": [],
                    "direction": None,
                    "format": "",
                    "indent": 0,
                    "type": "root",
                    "version": 1,
                }
            }
        },
    )
    assert patch_resp.status_code == 200

    # Re-read the document to confirm yjs_state was cleared
    await session.refresh(doc)
    assert doc.yjs_state is None


@pytest.mark.integration
async def test_create_whiteboard_document(client: AsyncClient, acting_user) -> None:
    """POST /documents/ with document_type='whiteboard' creates a whiteboard doc.

    The response's content should be the empty Excalidraw scene shape
    ({elements, appState, files}) rather than the Lexical root shape. This
    guards against normalize_document_content corrupting whiteboard payloads.
    """
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={
            "title": "My Whiteboard",
            "initiative_id": owner.initiative.id,
            "document_type": "whiteboard",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["document_type"] == "whiteboard"
    assert body["content"] == {"elements": [], "appState": {}, "files": {}}
    # Ensure the Lexical shape was NOT force-injected
    assert "root" not in body["content"]


def test_normalize_whiteboard_preserves_shape() -> None:
    """normalize_document_content must not inject Lexical root into whiteboards."""
    from app.services.tenant.documents import normalize_document_content

    scene = {
        "elements": [{"id": "el1", "type": "rectangle"}],
        "appState": {"viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    result = normalize_document_content(scene, document_type=DocumentType.whiteboard)
    assert result["elements"] == scene["elements"]
    assert result["appState"] == scene["appState"]
    assert result["files"] == scene["files"]
    assert "root" not in result


def test_normalize_native_still_injects_root() -> None:
    """Regression: native docs still get a root shape when content is empty."""
    from app.services.tenant.documents import normalize_document_content

    result = normalize_document_content({}, document_type=DocumentType.native)
    assert "root" in result
    assert isinstance(result["root"], dict)


@pytest.mark.integration
async def test_create_smart_link_document(client: AsyncClient, acting_user) -> None:
    """POST /documents/ with document_type='smart_link' stores only the URL."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={
            "title": "Design file",
            "initiative_id": owner.initiative.id,
            "document_type": "smart_link",
            "content": {"url": "https://www.figma.com/design/abc/Example"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["document_type"] == "smart_link"
    assert body["content"] == {"url": "https://www.figma.com/design/abc/Example"}


@pytest.mark.integration
async def test_create_smart_link_rejects_missing_url(
    client: AsyncClient, acting_user
) -> None:
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={
            "title": "Bad link",
            "initiative_id": owner.initiative.id,
            "document_type": "smart_link",
            "content": {},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SMART_LINK_URL_REQUIRED"


@pytest.mark.integration
async def test_create_smart_link_rejects_non_http_url(
    client: AsyncClient, acting_user
) -> None:
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={
            "title": "Bad scheme",
            "initiative_id": owner.initiative.id,
            "document_type": "smart_link",
            "content": {"url": "ftp://example.com/file"},
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_SMART_LINK_URL_INVALID"


def test_normalize_smart_link_returns_only_url() -> None:
    """normalize_document_content should strip any extra fields."""
    from app.services.tenant.documents import normalize_document_content

    result = normalize_document_content(
        {"url": "https://youtu.be/dQw4w9WgXcQ", "extra": "ignored"},
        document_type=DocumentType.smart_link,
    )
    assert result == {"url": "https://youtu.be/dQw4w9WgXcQ"}


def test_normalize_smart_link_raises_on_missing_url() -> None:
    """normalize_document_content should raise a domain error for missing URL,
    not an HTTPException (transport concern lives at the endpoint layer)."""
    from app.services.tenant.documents import (
        DocumentContentError,
        normalize_document_content,
    )

    with pytest.raises(DocumentContentError) as exc_info:
        normalize_document_content({}, document_type=DocumentType.smart_link)
    assert exc_info.value.code == "DOCUMENT_SMART_LINK_URL_REQUIRED"

    with pytest.raises(DocumentContentError) as exc_info:
        normalize_document_content(None, document_type=DocumentType.smart_link)
    assert exc_info.value.code == "DOCUMENT_SMART_LINK_URL_REQUIRED"


def test_normalize_smart_link_raises_on_bad_scheme() -> None:
    from app.services.tenant.documents import (
        DocumentContentError,
        normalize_document_content,
    )

    with pytest.raises(DocumentContentError) as exc_info:
        normalize_document_content(
            {"url": "ftp://example.com/file"},
            document_type=DocumentType.smart_link,
        )
    assert exc_info.value.code == "DOCUMENT_SMART_LINK_URL_INVALID"


def test_document_content_error_is_value_error() -> None:
    """DocumentContentError inherits from ValueError so generic
    ``except ValueError`` handlers still work."""
    from app.services.tenant.documents import DocumentContentError

    exc = DocumentContentError("SOME_CODE")
    assert isinstance(exc, ValueError)
    assert exc.code == "SOME_CODE"


@pytest.mark.integration
async def test_list_documents_filters_by_ids(client: AsyncClient, session, acting_user):
    """``ids`` narrows the listing to the requested documents so callers can
    hydrate a known set without walking the whole collection."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)

    wanted = await create_document(session, actor.initiative, actor.user)
    other = await create_document(session, actor.initiative, actor.user)

    response = await client.get(
        actor.g("/documents/"),
        headers=actor.headers,
        params={"ids": [wanted.id]},
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data["items"]] == [wanted.id]
    assert data["total_count"] == 1
    assert other.id not in {item["id"] for item in data["items"]}


@pytest.mark.integration
async def test_list_documents_ids_filter_respects_visibility(
    client: AsyncClient, session, acting_user
):
    """``ids`` is a filter, not a bypass — an id the caller cannot see stays
    invisible."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    private_doc = await create_document(session, owner.initiative, owner.user)

    other = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    response = await client.get(
        other.g("/documents/"),
        headers=other.headers,
        params={"ids": [private_doc.id]},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.integration
async def test_list_documents_filters_by_template_and_type(
    client: AsyncClient, session, acting_user
):
    """``is_template``/``document_type`` narrow the listing in SQL so the
    template picker doesn't walk the whole corpus."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)

    native_template = await create_document(
        session, actor.initiative, actor.user, is_template=True
    )
    whiteboard_template = await create_document(
        session,
        actor.initiative,
        actor.user,
        is_template=True,
        document_type=DocumentType.whiteboard,
    )
    plain = await create_document(session, actor.initiative, actor.user)

    response = await client.get(
        actor.g("/documents/"),
        headers=actor.headers,
        params={"is_template": True},
    )
    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {
        native_template.id,
        whiteboard_template.id,
    }

    response = await client.get(
        actor.g("/documents/"),
        headers=actor.headers,
        params={"is_template": True, "document_type": "native"},
    )
    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data["items"]] == [native_template.id]
    assert data["total_count"] == 1

    response = await client.get(
        actor.g("/documents/"),
        headers=actor.headers,
        params={"is_template": False},
    )
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [plain.id]


@pytest.mark.integration
async def test_list_documents_rejects_too_many_ids(client: AsyncClient, acting_user):
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(
        actor.g("/documents/"),
        headers=actor.headers,
        params={"ids": list(range(1, MAX_DOCUMENT_IDS + 2))},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_TOO_MANY_IDS"


@pytest.mark.integration
async def test_autocomplete_documents_empty_query_returns_recent(
    client: AsyncClient, session, acting_user
):
    """An empty ``q`` is the picker's opening state — it must list documents,
    not 422. Without this, a typeahead shows nothing until the user types."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_document(session, actor.initiative, actor.user, title="Alpha Handbook")
    await create_document(session, actor.initiative, actor.user, title="Beta Manual")

    response = await client.get(
        actor.g("/documents/autocomplete"),
        headers=actor.headers,
        params={"initiative_id": actor.initiative.id, "q": "", "limit": 20},
    )

    assert response.status_code == 200
    titles = {item["title"] for item in response.json()}
    assert titles == {"Alpha Handbook", "Beta Manual"}


@pytest.mark.integration
async def test_autocomplete_documents_filters_by_query(
    client: AsyncClient, session, acting_user
):
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await create_document(session, actor.initiative, actor.user, title="Alpha Handbook")
    await create_document(session, actor.initiative, actor.user, title="Beta Manual")

    response = await client.get(
        actor.g("/documents/autocomplete"),
        headers=actor.headers,
        params={"initiative_id": actor.initiative.id, "q": "beta", "limit": 20},
    )

    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["Beta Manual"]


@pytest.mark.integration
async def test_autocomplete_documents_honors_limit(
    client: AsyncClient, session, acting_user
):
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    for i in range(5):
        await create_document(session, actor.initiative, actor.user, title=f"Doc {i}")

    response = await client.get(
        actor.g("/documents/autocomplete"),
        headers=actor.headers,
        params={"initiative_id": actor.initiative.id, "q": "", "limit": 2},
    )

    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.integration
async def test_autocomplete_documents_rejects_non_positive_limit(
    client: AsyncClient, session, acting_user
):
    """``limit`` is bounded at 1 — a negative value is rejected at validation
    rather than reaching Postgres (which errors on a negative LIMIT)."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(
        actor.g("/documents/autocomplete"),
        headers=actor.headers,
        params={"initiative_id": actor.initiative.id, "q": "", "limit": -1},
    )

    assert response.status_code == 422


@pytest.mark.integration
async def test_autocomplete_documents_guild_wide_template_search(
    client: AsyncClient, session, acting_user
):
    """Templates are picked guild-wide, so omitting ``initiative_id`` searches
    every initiative the caller can see — narrowed to templates of one type."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)
    other_initiative = await create_initiative(session, actor.guild, actor.user)

    here = await create_document(
        session, actor.initiative, actor.user, title="Meeting Notes", is_template=True
    )
    there = await create_document(
        session, other_initiative, actor.user, title="Meeting Agenda", is_template=True
    )
    board = await create_document(
        session,
        other_initiative,
        actor.user,
        title="Meeting Board",
        is_template=True,
        document_type=DocumentType.whiteboard,
    )
    await create_document(session, actor.initiative, actor.user, title="Meeting Recap")

    response = await client.get(
        actor.g("/documents/autocomplete"),
        headers=actor.headers,
        params={"q": "meeting", "is_template": True, "limit": 20},
    )
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {here.id, there.id, board.id}

    response = await client.get(
        actor.g("/documents/autocomplete"),
        headers=actor.headers,
        params={"is_template": True, "document_type": "native", "limit": 20},
    )
    assert response.status_code == 200
    items = response.json()
    assert {item["id"] for item in items} == {here.id, there.id}
    assert all(item["document_type"] == "native" for item in items)


@pytest.mark.integration
async def test_autocomplete_guild_wide_respects_document_dac(
    client: AsyncClient, session, acting_user
):
    """A guild-wide search is a wider net, not a looser one — a template the
    caller holds no grant on stays invisible."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    private_template = await create_document(
        session,
        owner.initiative,
        owner.user,
        title="Private Template",
        is_template=True,
    )

    other = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )

    response = await client.get(
        other.g("/documents/autocomplete"),
        headers=other.headers,
        params={"is_template": True, "limit": 20},
    )

    assert response.status_code == 200
    assert private_template.id not in {item["id"] for item in response.json()}


@pytest.mark.integration
async def test_document_counts_by_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Grouped counts follow the same visibility rules as the document list."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    other_initiative = await create_initiative(session, admin.guild, admin.user)

    await create_document(session, admin.initiative, member.user)
    await create_document(session, admin.initiative, member.user)
    await create_document(session, admin.initiative, admin.user)
    await create_document(session, other_initiative, admin.user)

    # Guild admin sees every document, grouped by initiative.
    response = await client.get(
        admin.g("/documents/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {
        str(admin.initiative.id): 3,
        str(other_initiative.id): 1,
    }

    # A member counts only documents shared with them, and gets no entry
    # at all for initiatives they are not in.
    response = await client.get(
        member.g("/documents/counts/by-initiative"), headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {str(admin.initiative.id): 2}
