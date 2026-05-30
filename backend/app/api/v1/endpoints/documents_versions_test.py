"""
Integration tests for document file-version endpoints:
upload new version, list versions, download a specific version, delete a version.
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
)
from app.models.guild import GuildRole
from app.models.upload import Upload
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    get_auth_headers,
    get_guild_headers,
)

PDF_BYTES = b"%PDF-1.4 first version body"
PDF_BYTES_V2 = b"%PDF-1.4 second version body that differs"


def _uploads_dir() -> Path:
    path = Path(settings.UPLOADS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _setup_guild_with_owner(session: AsyncSession):
    owner = await create_user(session)
    guild = await create_guild(session, creator=owner)
    await create_guild_membership(session, user=owner, guild=guild, role=GuildRole.admin)
    initiative = await create_initiative(session, guild, owner)
    return owner, guild, initiative


async def _upload_initial_file_doc(
    client: AsyncClient,
    *,
    guild,
    user,
    initiative,
    title: str = "Versioned Doc",
    content: bytes = PDF_BYTES,
    filename: str = "v1.pdf",
    content_type: str = "application/pdf",
) -> dict:
    """Create a file document through the real upload endpoint (creates v1)."""
    headers = get_guild_headers(guild, user)
    response = await client.post(
        "/api/v1/documents/upload",
        headers=headers,
        data={"title": title, "initiative_id": str(initiative.id)},
        files={"file": (filename, content, content_type)},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.integration
async def test_initial_upload_creates_version_one(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Uploading a file document seeds version 1."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)

    headers = get_guild_headers(guild, owner)
    resp = await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=headers)
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["is_current"] is True

    # Clean up the blob.
    result = await session.exec(
        select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
    )
    for v in result.all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_version_creates_v2_and_mirrors_document(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A write user uploads v2; document mirror + Upload row + version row update."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    writer = await create_user(session)
    await create_guild_membership(session, user=writer, guild=guild)
    await create_initiative_member(session, initiative, writer)

    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    # Grant the writer write access.
    session.add(
        DocumentPermission(
            document_id=doc["id"],
            user_id=writer.id,
            level=DocumentPermissionLevel.write,
            guild_id=guild.id,
        )
    )
    await session.commit()

    headers = get_guild_headers(guild, writer)
    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["version_number"] == 2
    assert body["is_current"] is True

    # Document row now mirrors v2.
    session.expire_all()
    refreshed = await session.get(Document, doc["id"])
    assert refreshed.file_size == len(PDF_BYTES_V2)
    assert refreshed.original_filename == "v2.pdf"

    # Two version rows + two Upload rows exist.
    versions = (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all()
    assert {v.version_number for v in versions} == {1, 2}
    for v in versions:
        upload = (
            await session.exec(
                select(Upload).where(Upload.filename == v.file_url.split("/")[-1])
            )
        ).one_or_none()
        assert upload is not None
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_version_read_user_forbidden(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A read-only user cannot upload a new version."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    reader = await create_user(session)
    await create_guild_membership(session, user=reader, guild=guild)
    await create_initiative_member(session, initiative, reader)

    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    session.add(
        DocumentPermission(
            document_id=doc["id"],
            user_id=reader.id,
            level=DocumentPermissionLevel.read,
            guild_id=guild.id,
        )
    )
    await session.commit()

    headers = get_guild_headers(guild, reader)
    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    assert resp.status_code == 403

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_version_type_mismatch_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A new version must match the original file type."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)

    headers = get_guild_headers(guild, owner)
    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=headers,
        files={"file": ("notes.txt", b"plain text not a pdf", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "DOCUMENT_VERSION_TYPE_MISMATCH"

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_version_non_file_document_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Native documents don't support versions."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    headers = get_guild_headers(guild, owner)
    create = await client.post(
        "/api/v1/documents/",
        headers=headers,
        json={"title": "Native doc", "initiative_id": initiative.id},
    )
    assert create.status_code == 201
    native_id = create.json()["id"]

    resp = await client.post(
        f"/api/v1/documents/{native_id}/versions",
        headers=headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "DOCUMENT_NOT_A_FILE_DOCUMENT"

    # Listing versions on a non-file document is rejected too.
    list_resp = await client.get(f"/api/v1/documents/{native_id}/versions", headers=headers)
    assert list_resp.status_code == 400
    assert list_resp.json()["detail"] == "DOCUMENT_NOT_A_FILE_DOCUMENT"


@pytest.mark.integration
async def test_upload_version_unsupported_file_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """An unsupported/invalid file is rejected with a coded error."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)

    headers = get_guild_headers(guild, owner)
    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=headers,
        files={"file": ("evil.exe", b"MZ\x90\x00\x03 not allowed", "application/x-msdownload")},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "DOCUMENT_INVALID_FILE"

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_list_versions_read_user_allowed_and_ordered(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Read users can list versions; newest first with is_current on the highest."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    reader = await create_user(session)
    await create_guild_membership(session, user=reader, guild=guild)
    await create_initiative_member(session, initiative, reader)

    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    session.add(
        DocumentPermission(
            document_id=doc["id"],
            user_id=reader.id,
            level=DocumentPermissionLevel.read,
            guild_id=guild.id,
        )
    )
    await session.commit()

    # Owner uploads v2.
    owner_headers = get_guild_headers(guild, owner)
    await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=owner_headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )

    reader_headers = get_guild_headers(guild, reader)
    resp = await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=reader_headers)
    assert resp.status_code == 200
    versions = resp.json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[0]["is_current"] is True
    assert versions[1]["is_current"] is False

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_specific_version_returns_its_bytes(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Downloading an old version returns that version's bytes, not the current one."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)

    guild_headers = get_guild_headers(guild, owner)
    await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=guild_headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )

    versions = (
        await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=guild_headers)
    ).json()
    v1 = next(v for v in versions if v["version_number"] == 1)
    v2 = next(v for v in versions if v["version_number"] == 2)

    auth_headers = get_auth_headers(owner)
    r1 = await client.get(
        f"/api/v1/documents/{doc['id']}/versions/{v1['id']}/download", headers=auth_headers
    )
    r2 = await client.get(
        f"/api/v1/documents/{doc['id']}/versions/{v2['id']}/download", headers=auth_headers
    )
    assert r1.status_code == 200 and r1.content == PDF_BYTES
    assert r2.status_code == 200 and r2.content == PDF_BYTES_V2

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_version_unknown_returns_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A version id that doesn't belong to the document 404s."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)

    auth_headers = get_auth_headers(owner)
    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/versions/99999/download", headers=auth_headers
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "DOCUMENT_VERSION_NOT_FOUND"

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_download_version_cross_guild_forbidden(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A user from another guild cannot download a version."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    versions = (
        await client.get(
            f"/api/v1/documents/{doc['id']}/versions", headers=get_guild_headers(guild, owner)
        )
    ).json()
    v1 = versions[0]

    outsider = await create_user(session)
    resp = await client.get(
        f"/api/v1/documents/{doc['id']}/versions/{v1['id']}/download",
        headers=get_auth_headers(outsider),
    )
    assert resp.status_code == 404

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_delete_non_current_version_owner(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Owner deletes an old version; current stays, blob + Upload row removed."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    guild_headers = get_guild_headers(guild, owner)
    await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=guild_headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    versions = (
        await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=guild_headers)
    ).json()
    v1 = next(v for v in versions if v["version_number"] == 1)

    # Resolve v1's blob filename before deletion.
    v1_row = (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.id == v1["id"])
        )
    ).one()
    v1_filename = v1_row.file_url.split("/")[-1]

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}/versions/{v1['id']}", headers=guild_headers
    )
    assert resp.status_code == 204

    remaining = (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all()
    assert [v.version_number for v in remaining] == [2]
    # Upload row + blob for v1 are gone.
    assert (
        await session.exec(select(Upload).where(Upload.filename == v1_filename))
    ).one_or_none() is None
    assert not (_uploads_dir() / v1_filename).exists()

    # Current (v2) unchanged on document.
    remaining_filename = remaining[0].file_url.split("/")[-1]
    session.expire_all()
    refreshed = await session.get(Document, doc["id"])
    assert refreshed.file_size == len(PDF_BYTES_V2)

    (_uploads_dir() / remaining_filename).unlink(missing_ok=True)


@pytest.mark.integration
async def test_delete_current_version_promotes_previous(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Deleting the current version rolls the document back to the prior version."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    guild_headers = get_guild_headers(guild, owner)
    v2_resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=guild_headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    v2_id = v2_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}/versions/{v2_id}", headers=guild_headers
    )
    assert resp.status_code == 204

    # Document mirror reverts to v1.
    session.expire_all()
    refreshed = await session.get(Document, doc["id"])
    assert refreshed.file_size == len(PDF_BYTES)
    assert refreshed.original_filename == "v1.pdf"

    versions = (
        await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=guild_headers)
    ).json()
    assert [v["version_number"] for v in versions] == [1]
    assert versions[0]["is_current"] is True

    (_uploads_dir() / refreshed.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_delete_last_version_blocked(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The only remaining version can't be deleted."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    guild_headers = get_guild_headers(guild, owner)
    versions = (
        await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=guild_headers)
    ).json()
    v1_id = versions[0]["id"]

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}/versions/{v1_id}", headers=guild_headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "DOCUMENT_CANNOT_DELETE_LAST_VERSION"

    (_uploads_dir() / versions[0]["original_filename"]).unlink(missing_ok=True)
    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_delete_version_non_owner_forbidden(
    client: AsyncClient, session: AsyncSession
) -> None:
    """A write (non-owner) user cannot delete versions."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    writer = await create_user(session)
    await create_guild_membership(session, user=writer, guild=guild)
    await create_initiative_member(session, initiative, writer)

    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)
    session.add(
        DocumentPermission(
            document_id=doc["id"],
            user_id=writer.id,
            level=DocumentPermissionLevel.write,
            guild_id=guild.id,
        )
    )
    await session.commit()
    guild_headers = get_guild_headers(guild, owner)
    await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=guild_headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    versions = (
        await client.get(f"/api/v1/documents/{doc['id']}/versions", headers=guild_headers)
    ).json()
    v1_id = next(v for v in versions if v["version_number"] == 1)["id"]

    resp = await client.delete(
        f"/api/v1/documents/{doc['id']}/versions/{v1_id}",
        headers=get_guild_headers(guild, writer),
    )
    assert resp.status_code == 403

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_upload_version_allowed_when_stored_content_type_is_null(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Legacy documents with NULL ``file_content_type`` still accept new versions.

    Without the NULL guard, ``_normalize_mime(None) == ""`` would always
    mismatch the uploaded MIME type and permanently reject new versions
    with ``VERSION_TYPE_MISMATCH``.
    """
    owner, guild, initiative = await _setup_guild_with_owner(session)
    doc = await _upload_initial_file_doc(client, guild=guild, user=owner, initiative=initiative)

    # Simulate a legacy / backfilled row where the content type was never recorded.
    db_doc = await session.get(Document, doc["id"])
    assert db_doc is not None
    db_doc.file_content_type = None
    await session.commit()

    guild_headers = get_guild_headers(guild, owner)
    resp = await client.post(
        f"/api/v1/documents/{doc['id']}/versions",
        headers=guild_headers,
        files={"file": ("v2.pdf", PDF_BYTES_V2, "application/pdf")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["version_number"] == 2

    for v in (
        await session.exec(
            select(DocumentFileVersion).where(DocumentFileVersion.document_id == doc["id"])
        )
    ).all():
        (_uploads_dir() / v.file_url.split("/")[-1]).unlink(missing_ok=True)


@pytest.mark.integration
async def test_delete_version_non_file_document_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Delete is rejected on non-file documents with the same code as upload/list."""
    owner, guild, initiative = await _setup_guild_with_owner(session)
    headers = get_guild_headers(guild, owner)
    create = await client.post(
        "/api/v1/documents/",
        headers=headers,
        json={"title": "Native doc", "initiative_id": initiative.id},
    )
    assert create.status_code == 201
    native_id = create.json()["id"]

    # Any version_id will do — the type check fires before the version lookup.
    resp = await client.delete(
        f"/api/v1/documents/{native_id}/versions/9999",
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "DOCUMENT_NOT_A_FILE_DOCUMENT"
