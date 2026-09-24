"""An export that travels as a zip: its envelope, and the files it names.

A gallery is its pictures, so a gallery exported on its own downloads as a zip
holding its envelope at the top level and each picture under ``assets/``, named
by the storage key the envelope gives it — the layout a backup uses. Importing
that zip puts the pictures in the community's storage under those keys and then
imports the envelope exactly as a lone JSON file is imported, so every rule the
envelope path has (authorization, the people step, inline or queued) holds.

A wiki's zip carries the uploads filed in it the same way. A zip holding any
other tool's envelope imports too: it simply carries nothing beside it.

Every file is what the zip claims only once it has been read: a picture must
be one a gallery can show, and an upload a file a document may hold. One that
is not is left out and the import says so. A key already stored here is never
written over — a re-import of the same zip reuses the file it already brought
— and the community's storage quota is checked against the zip's own sizes
before anything is written.
"""

from __future__ import annotations

import asyncio
import json
import zipfile
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.services.import_engine import engine as import_engine
from app.services.import_engine import limits as import_limits
from app.services.import_engine.backup import open_backup_zip
from app.services.import_engine.contract import ImportEngineError, InlineImport

#: Where the files an envelope names sit in its zip.
ASSET_DIR = "assets/"


def read_envelope_archive(payload: bytes) -> tuple[zipfile.ZipFile, dict[str, Any]]:
    """The zip, bound-checked, and the one envelope at its top level."""
    archive = open_backup_zip(payload)
    candidates = [
        info
        for info in archive.infolist()
        if not info.is_dir() and "/" not in info.filename
    ]
    envelopes = [info for info in candidates if info.filename.endswith(".json")]
    if len(envelopes) != 1:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ARCHIVE_NO_ENVELOPE)
    [info] = envelopes
    if info.file_size > import_limits.IMPORT_MAX_ENVELOPE_BYTES:
        raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)
    try:
        envelope = json.loads(archive.read(info))
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE) from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("type"), str):
        raise ImportEngineError(ImportEngineMessages.IMPORT_INVALID_ENVELOPE)
    return archive, envelope


def _flat_key(key: Any) -> str | None:
    """A storage key the way every stored file is named: one flat filename."""
    if not isinstance(key, str):
        return None
    key = key.strip()
    if not key or "/" in key or "\\" in key or key in (".", ".."):
        return None
    return key


async def restore_archive_assets(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    assets: list[tuple[dict[str, Any], str]],
    *,
    guild_id: int,
    user: User,
) -> tuple[list[str], list[str]]:
    """Put each named file the zip carries into the community's storage.

    ``assets`` are the envelope's own records of its files, each with what it
    should be — ``"picture"`` or ``"file"``; each record's ``content_type`` is
    set to what the file turned out to be, since that is what the importer
    stores. Returns the keys written — for the caller to remove if the import
    then fails — and the warnings to report.
    """
    from app.models.tenant.upload import Upload
    from app.services.storage import get_guild_storage
    from app.services.tenant.attachments import (
        StorageQuotaExceededError,
        compute_content_hash,
        enforce_storage_quota,
        validate_document_file,
    )
    from app.services.tenant.galleries import (
        EmptyImageError,
        InvalidImageError,
        validate_image,
    )

    storage = get_guild_storage(guild_id)
    warnings: list[str] = []
    pending: list[tuple[str, zipfile.ZipInfo, list[dict[str, Any]]]] = []
    by_key: dict[str, list[dict[str, Any]]] = {}
    kinds: dict[str, str] = {}
    for record, kind in assets:
        key = _flat_key(record.get("storage_key"))
        if key is None:
            continue
        by_key.setdefault(key, []).append(record)
        # A key named as a picture anywhere is held to the picture rule.
        if kinds.get(key) != "picture":
            kinds[key] = kind

    incoming = 0
    for key, records in by_key.items():
        try:
            info = archive.getinfo(f"{ASSET_DIR}{key}")
        except KeyError:
            # Not in the zip: the envelope still lists it, and the importer
            # counts it as missing unless it is already stored here.
            continue
        already = (
            await session.exec(select(Upload.id).where(Upload.filename == key))
        ).first() is not None
        if already or storage.exists(key):
            # Stored already — a re-import of the same zip. Never written over.
            continue
        incoming += info.file_size
        pending.append((key, info, records))

    try:
        await enforce_storage_quota(session, guild_id=guild_id, incoming_bytes=incoming)
    except StorageQuotaExceededError as exc:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_QUOTA_EXCEEDED, status_code=400
        ) from exc

    written: list[str] = []
    read_total = 0
    try:
        for key, info, records in pending:
            data = archive.read(info)
            read_total += len(data)
            if read_total > incoming:
                # The sizes the zip declared are what the quota was checked
                # against, so they bound what is written too.
                raise ImportEngineError(
                    ImportEngineMessages.IMPORT_QUOTA_EXCEEDED, status_code=400
                )
            if kinds[key] == "picture":
                try:
                    header, _extension = validate_image(data)
                except (EmptyImageError, InvalidImageError):
                    warnings.append(f"not_a_picture:{key}")
                    continue
                content_type = header.content_type
            else:
                try:
                    content_type, _extension = validate_document_file(
                        data,
                        records[0].get("original_filename"),
                        records[0].get("content_type"),
                    )
                except ValueError:
                    warnings.append(f"unsupported_file:{key}")
                    continue
            await asyncio.to_thread(storage.write, key, data, content_type=content_type)
            written.append(key)
            session.add(
                Upload(
                    filename=key,
                    created_by=user.id,
                    size_bytes=len(data),
                    content_type=content_type,
                    content_hash=compute_content_hash(data),
                )
            )
            for record in records:
                record["content_type"] = content_type
    except BaseException:
        remove_written(guild_id, written)
        raise
    return written, warnings


def remove_written(guild_id: int, keys: list[str]) -> None:
    """Best-effort removal of files an import wrote before it failed."""
    from app.services.storage import get_guild_storage

    storage = get_guild_storage(guild_id)
    for key in keys:
        try:
            storage.delete(key)
        except Exception:  # pragma: no cover - backend-specific failures
            pass


async def start_envelope_archive_import(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    initiative_id: int,
    payload: bytes,
    expected_type: str | None = None,
):
    """Import an exported zip into an initiative: authorize, put its files in
    storage, then import its envelope the way a lone file is imported.

    ``expected_type`` is the envelope type of the tool the import was started
    from; a zip holding another tool's export is refused rather than landing
    somewhere nobody looked for it.
    """
    archive, envelope = read_envelope_archive(payload)
    if expected_type is not None and envelope["type"] != expected_type:
        raise ImportEngineError(ImportEngineMessages.IMPORT_WRONG_TOOL)
    importer = import_engine.get_importer(envelope["type"])
    importer.validate(envelope)
    # Authorized before anything is written: the same gate the import itself
    # runs again below.
    await import_engine.load_target_initiative(
        session,
        guild_id=guild_id,
        initiative_id=initiative_id,
        importer=importer,
        user=user,
    )
    assets_of = getattr(importer, "archive_assets", None)
    written: list[str] = []
    warnings: list[str] = []
    if assets_of is not None:
        written, warnings = await restore_archive_assets(
            session, archive, assets_of(envelope), guild_id=guild_id, user=user
        )
    try:
        outcome = await import_engine.start_envelope_import(
            session,
            user=user,
            guild_id=guild_id,
            initiative_id=initiative_id,
            envelope=envelope,
        )
    except BaseException:
        remove_written(guild_id, written)
        raise
    if isinstance(outcome, InlineImport):
        outcome.result.warnings.extend(warnings)
    return outcome
