"""
Integration tests for document endpoints — create with permissions.
"""

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.tenant_endpoints.documents import MAX_DOCUMENT_IDS
from app.models.tenant.document import (
    Document,
    DocumentType,
)
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.testing import (
    guild_of,
    create_document,
    create_initiative,
    create_resource_grant,
)


async def _create_file_document(
    session: AsyncSession,
    *,
    initiative,
    owner,
    filename: str,
) -> Document:
    """A file-type document with a dummy file on disk, made the way every
    test document is made: through the factory, which routes by the
    initiative and writes the owner grant."""
    # Stage the blob via the real resolver so it lands where the serve path reads
    # it (UPLOADS_DIR/guild_<id>/), and use the canonical guild-scoped URL.
    from app.services.storage import get_guild_storage

    get_guild_storage(guild_of(initiative)).write(filename, b"%PDF-1.4 test")

    return await create_document(
        session,
        initiative,
        owner,
        name="Test File Doc",
        document_type=DocumentType.file,
        file_url=f"/uploads/{guild_of(initiative)}/{filename}",
        original_filename=filename,
        file_content_type="application/pdf",
        file_size=13,
    )


@pytest.mark.integration
async def test_create_refuses_when_documents_are_switched_off(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Documents are a tool like any other now: an initiative that has turned
    them off refuses to hold one, and names the reason instead of failing at
    the row."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.documents_enabled = False
    session.add(a.initiative)
    await session.commit()

    response = await client.post(
        a.g("/documents/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "DOCUMENTS_NOT_ENABLED"


@pytest.mark.integration
async def test_a_guild_admin_does_not_list_documents_of_a_switched_off_initiative(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The mirror of the projects case: the RLS leg keeps a guild admin and a
    PAM reader able to reach the rows for maintenance, and the list declines to
    be the place that shows them."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    doc = await create_document(session, a.initiative, a.user)

    listed = await client.get(a.g("/documents/"), headers=a.headers)
    assert listed.status_code == 200
    assert doc.id in [d["id"] for d in listed.json()["items"]]

    a.initiative.documents_enabled = False
    session.add(a.initiative)
    await session.commit()

    listed = await client.get(a.g("/documents/"), headers=a.headers)
    assert listed.status_code == 200
    assert listed.json()["items"] == []


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
        "name": "Doc With Permissions",
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
    assert data["name"] == "Doc With Permissions"

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
        "name": "Doc Default Share",
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


# ---------------------------------------------------------------------------
# Duplicate / copy / create-from-template tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_duplicate_is_held_to_create_and_keeps_the_sources_sharing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A duplicate is a new document: its maker needs the right to create
    documents, its name must be free, and it is shared with the same people
    as the document it copies."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    writer = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    doc = await create_document(session, owner.initiative, owner.user, name="Plan")
    await create_resource_grant(
        session, doc, user=writer.user, level=ResourceAccessLevel.write
    )
    await create_resource_grant(session, doc, all_initiative_members=True)

    refused = await client.post(
        writer.g(f"/documents/{doc.id}/duplicate"), headers=writer.headers
    )
    assert refused.status_code == 403
    assert refused.json()["detail"] == "DOCUMENT_CREATE_PERMISSION_REQUIRED"

    duplicated = await client.post(
        owner.g(f"/documents/{doc.id}/duplicate"), headers=owner.headers
    )
    assert duplicated.status_code == 201, duplicated.text
    assert duplicated.json()["name"] == "Plan (Copy)"
    assert {
        (g["user_id"], g["all_initiative_members"], g["level"])
        for g in duplicated.json()["grants"]
    } == {
        (owner.user.id, False, "owner"),
        (writer.user.id, False, "write"),
        (None, True, "read"),
    }

    again = await client.post(
        owner.g(f"/documents/{doc.id}/duplicate"), headers=owner.headers
    )
    assert again.status_code == 400
    assert again.json()["detail"] == "DOCUMENT_NAME_ALREADY_EXISTS"


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
    initiative = template_owner.initiative

    template = await create_document(
        session,
        initiative,
        template_owner.user,
        name="Project Kickoff Template",
        is_template=True,
    )
    # Grant reader explicit read-only access on the template.
    await create_resource_grant(session, template, user=reader.user)

    response = await client.post(
        reader.g(f"/documents/{template.id}/copy"),
        headers=reader.headers,
        json={"target_initiative_id": initiative.id, "name": "My Kickoff"},
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["name"] == "My Kickoff"
    assert data["is_template"] is False
    assert data["created_by"] == reader.user.id

    # Reader is owner of the new doc.
    new_grant_levels = {
        g["user_id"]: g["level"] for g in data["grants"] if g["user_id"]
    }
    assert new_grant_levels.get(reader.user.id) == "owner"

    # Source template is unchanged.
    await session.refresh(template)
    assert template.is_template is True
    assert template.name == "Project Kickoff Template"


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
    initiative = owner.initiative

    doc = await create_document(
        session, initiative, owner.user, name="Confidential Notes"
    )
    await create_resource_grant(session, doc, user=reader.user)

    response = await client.post(
        reader.g(f"/documents/{doc.id}/copy"),
        headers=reader.headers,
        json={"target_initiative_id": initiative.id, "name": "My Copy"},
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
    response = await client.get(
        owner.g(f"/documents/{doc.id}/download"), headers=owner.headers
    )
    assert response.status_code == 200
    assert "attachment" in response.headers.get("content-disposition", "")
    assert response.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.integration
async def test_download_unauthenticated_returns_401(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Unauthenticated request returns 401."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_unauth.pdf"
    )
    response = await client.get(owner.g(f"/documents/{doc.id}/download"))
    assert response.status_code == 401


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
    response = await client.get(
        other.g(f"/documents/{doc.id}/download"), headers=other.headers
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_version_download_answers_like_the_file_download(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Both download routes load the document the same way, so an initiative
    member the sharing does not reach is answered the same way by each."""
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
        filename="dl_version_no_perm.pdf",
    )
    current = await client.get(
        other.g(f"/documents/{doc.id}/download"), headers=other.headers
    )
    stored = await client.get(
        other.g(f"/documents/{doc.id}/versions/1/download"),
        headers=other.headers,
    )
    assert current.status_code == 403
    assert stored.status_code == current.status_code


@pytest.mark.integration
async def test_download_non_guild_member_returns_404(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """User from a different guild gets 404 (document not visible)."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    outsider = await acting_user("member")

    doc = await _create_file_document(
        session,
        initiative=owner.initiative,
        owner=owner.user,
        filename="dl_outsider.pdf",
    )
    response = await client.get(
        owner.g(f"/documents/{doc.id}/download"), headers=outsider.headers
    )
    assert response.status_code == 404


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

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_reader.pdf"
    )
    await create_resource_grant(session, doc, user=reader.user)

    response = await client.get(
        owner.g(f"/documents/{doc.id}/download"), headers=reader.headers
    )
    assert response.status_code == 200


@pytest.mark.integration
async def test_download_inline_returns_no_attachment_header(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """?inline=1 serves the file without Content-Disposition: attachment."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    doc = await _create_file_document(
        session, initiative=owner.initiative, owner=owner.user, filename="dl_inline.pdf"
    )
    response = await client.get(
        owner.g(f"/documents/{doc.id}/download?inline=1"),
        headers=owner.headers,
    )
    assert response.status_code == 200
    assert "attachment" not in response.headers.get("content-disposition", "")


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


@pytest.mark.integration
async def test_download_native_document_returns_404(
    client: AsyncClient, acting_user
) -> None:
    """Native (non-file) document returns 404 from the download endpoint."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={"name": "Native Doc", "initiative_id": owner.initiative.id},
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    response = await client.get(
        owner.g(f"/documents/{doc_id}/download"), headers=owner.headers
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
        json={"name": "Collab Doc", "initiative_id": owner.initiative.id},
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
    A file document is not made here: it comes from uploading its file.
    """
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)

    response = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={
            "name": "My Whiteboard",
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

    file_doc = await client.post(
        owner.g("/documents/"),
        headers=owner.headers,
        json={
            "name": "Not a file",
            "initiative_id": owner.initiative.id,
            "document_type": "file",
        },
    )
    assert file_doc.status_code == 422


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
            "name": "Design file",
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
            "name": "Bad link",
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
            "name": "Bad scheme",
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
async def test_document_counts_filter_by_template_and_type(
    client: AsyncClient, session, acting_user
):
    """The tag-sidebar counts honor the same template/type narrowing as the
    list, so the two never disagree."""
    actor = await acting_user(guild_role=GuildRole.admin, initiative=True)

    await create_document(session, actor.initiative, actor.user, is_template=True)
    await create_document(
        session,
        actor.initiative,
        actor.user,
        is_template=True,
        document_type=DocumentType.whiteboard,
    )
    await create_document(session, actor.initiative, actor.user)

    response = await client.get(actor.g("/documents/counts"), headers=actor.headers)
    assert response.status_code == 200
    assert response.json()["total_count"] == 3

    response = await client.get(
        actor.g("/documents/counts"),
        headers=actor.headers,
        params={"is_template": True},
    )
    assert response.status_code == 200
    assert response.json()["total_count"] == 2

    response = await client.get(
        actor.g("/documents/counts"),
        headers=actor.headers,
        params={"is_template": True, "document_type": "whiteboard"},
    )
    assert response.status_code == 200
    assert response.json()["total_count"] == 1

    response = await client.get(
        actor.g("/documents/counts"),
        headers=actor.headers,
        params={"document_type": "native"},
    )
    assert response.status_code == 200
    assert response.json()["total_count"] == 2


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

    # The counts span initiatives, so they answer what reaches the reader —
    # a guild admin included. Theirs is the one document they hold in each,
    # not the member's two alongside it.
    response = await client.get(
        admin.g("/documents/counts/by-initiative"), headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {
        str(admin.initiative.id): 1,
        str(other_initiative.id): 1,
    }

    # A member counts only documents shared with them, and gets no entry
    # at all for initiatives they are not in.
    response = await client.get(
        member.g("/documents/counts/by-initiative"), headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["counts"] == {str(admin.initiative.id): 2}


async def test_reading_a_document_can_leave_the_body_out(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A document's body is the largest thing this API returns, and a caller
    reacting to a change usually does not need it. Everything else is
    unchanged, so one request still answers "what is this document now"."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    document = await create_document(session, a.initiative, a.user)
    document.content = {"root": {"children": [{"type": "paragraph"}]}}
    session.add(document)
    await session.commit()
    document_id = document.id

    full = await client.get(a.g(f"/documents/{document_id}"), headers=a.headers)
    assert full.status_code == 200, full.text
    assert full.json()["content"] == {"root": {"children": [{"type": "paragraph"}]}}

    slim = await client.get(
        a.g(f"/documents/{document_id}"),
        params={"include_content": "false"},
        headers=a.headers,
    )
    assert slim.status_code == 200, slim.text
    body = slim.json()
    assert body["content"] == {}
    assert body["id"] == document_id
    assert body["name"] == full.json()["name"]
    assert body["updated_at"] == full.json()["updated_at"]


@pytest.mark.integration
async def test_a_content_patch_against_a_live_document_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
) -> None:
    """A document being edited live has its room as the writer of its content.

    Editors inside the session report their rendering to the room over their
    own sockets. A rendering arriving over REST belongs to a tab outside it,
    and is refused rather than taken and reported as saved.
    """
    from app.services.tenant.collaboration import collaboration_manager

    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    original = doc.content

    monkeypatch.setattr(
        collaboration_manager, "has_active_collaborators", lambda *_a: True
    )

    response = await client.patch(
        owner.g(f"/documents/{doc.id}"),
        headers=owner.headers,
        json={"content": {"root": "written outside the session"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "DOCUMENT_LIVE_SESSION_OWNS_CONTENT"
    await session.refresh(doc)
    assert doc.content == original


@pytest.mark.integration
async def test_a_live_document_can_still_be_renamed(
    client: AsyncClient, session: AsyncSession, acting_user, monkeypatch
) -> None:
    """Only the content column belongs to the room; the rest of a document
    is unrelated to what its editors are doing and still applies."""
    from app.services.tenant.collaboration import collaboration_manager

    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    monkeypatch.setattr(
        collaboration_manager, "has_active_collaborators", lambda *_a: True
    )

    response = await client.patch(
        owner.g(f"/documents/{doc.id}"),
        headers=owner.headers,
        json={"name": "Renamed while live"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed while live"
