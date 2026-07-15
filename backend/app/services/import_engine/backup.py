"""Backup-zip import: plan (pre-flight summary from ``manifest.json``) and
apply (the worker-side restore).

A backup is the export engine's zip: per-tool JSON envelopes under
``initiatives/{id}-{slug}/…`` indexed by a root manifest, plus optional
upload blobs under ``assets/``. Import creates **new initiatives** (names
suffixed on collision, tool switches from the manifest, the importer becomes
manager) — never merges — and dispatches every entry to the per-type
importer registry, so an envelope imports identically whether it arrives
alone or inside a backup.

Safety model:
* zip-bomb bounds (member count, total declared uncompressed size, no
  absolute/traversal paths) are checked before anything is read beyond the
  central directory;
* the plan step reads ONLY ``manifest.json`` — milliseconds, so it runs
  synchronously in the upload request;
* apply re-verifies the creator is a REAL guild admin (fail closed on
  revocation), restores assets under their original storage keys (embedded
  editor-state references resolve without rewriting) with per-key dedup and
  storage-quota enforcement, and applies entries in per-entry savepoints —
  one corrupt entry fails alone, the job still completes with a report;
* long applies commit per chunk and refresh ``establish_guild_access``
  (RLS context is valid for at most RLS_CONTEXT_MAX_AGE_SECONDS).
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import ImportEngineMessages
from app.models.platform.user import User
from app.schemas.tenant.backup_export import (
    BACKUP_SCHEMA_VERSION,
    MIN_SUPPORTED_IMPORT_VERSION,
    BackupManifest,
    ManifestEntry,
)
from app.schemas.tenant.import_job import (
    BackupImportPlan,
    BackupImportResult,
    BackupPlanInitiative,
    EntryResult,
)
from app.services.import_engine.common import unique_name
from app.services.import_engine.contract import ImportEngineError

# Apply order within an initiative — convention, not correctness (cross-tool
# references in envelopes are display text only).
_TOOL_ORDER = ("project", "document", "queue", "counter_group", "calendar_event")

# Refresh the routed session's authorization context this often (see the
# export backup adapter's identical constant).
_REFRESH_EVERY = 25

_MANIFEST_NAME = "manifest.json"

logger = logging.getLogger(__name__)


def _normalize_type_field(data: dict[str, Any]) -> dict[str, Any]:
    """0.56.0-era backups spell the discriminator ``kind``."""
    if isinstance(data, dict) and "type" not in data and "kind" in data:
        data = {**data, "type": data["kind"]}
    return data


def open_backup_zip(payload: bytes) -> zipfile.ZipFile:
    """Open + bound-check a backup zip. Raises IMPORT_ZIP_INVALID /
    IMPORT_TOO_LARGE before anything beyond the central directory is read."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    infos = archive.infolist()
    if len(infos) > settings.IMPORT_MAX_ZIP_MEMBERS:
        raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)
    declared = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or ".." in name.split("/"):
            raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID)
        declared += info.file_size
        if declared > settings.IMPORT_MAX_BACKUP_UNCOMPRESSED_BYTES:
            raise ImportEngineError(ImportEngineMessages.IMPORT_TOO_LARGE)
    return archive


def read_manifest(archive: zipfile.ZipFile) -> BackupManifest:
    try:
        raw = json.loads(archive.read(_MANIFEST_NAME))
    except KeyError as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    if isinstance(raw, dict):
        raw = _normalize_type_field(raw)
        raw["entries"] = [
            _normalize_type_field(e) for e in raw.get("entries", []) or []
        ]
    try:
        manifest = BackupManifest.model_validate(raw)
    except Exception as exc:
        raise ImportEngineError(ImportEngineMessages.IMPORT_ZIP_INVALID) from exc
    if not (
        MIN_SUPPORTED_IMPORT_VERSION <= manifest.schema_version <= BACKUP_SCHEMA_VERSION
    ):
        raise ImportEngineError(ImportEngineMessages.IMPORT_SCHEMA_VERSION_UNSUPPORTED)
    return manifest


def plan_backup(
    payload: bytes, *, existing_initiative_names: set[str]
) -> BackupImportPlan:
    """The confirm-screen summary. Reads only the manifest — cheap enough to
    run synchronously inside the upload request."""
    from app.services.import_engine.importers import IMPORTERS

    archive = open_backup_zip(payload)
    manifest = read_manifest(archive)

    unknown_types = sorted(
        {
            entry.type
            for entry in manifest.entries
            if entry.type != "file" and entry.type not in IMPORTERS
        }
    )
    # Suffix previews compound: two imported initiatives can collide with
    # each other, not just with existing ones.
    taken = set(existing_initiative_names)
    initiatives: list[BackupPlanInitiative] = []
    for mi in manifest.initiatives:
        proposed = unique_name(taken, mi.name)
        taken.add(proposed)
        counts: dict[str, int] = {}
        for entry in manifest.entries:
            if entry.initiative_id == mi.id:
                counts[entry.tool] = counts.get(entry.tool, 0) + 1
        initiatives.append(
            BackupPlanInitiative(
                source_id=mi.id,
                name=mi.name,
                proposed_name=proposed,
                tools=mi.tools,
                entry_counts=counts,
            )
        )
    return BackupImportPlan(
        source_guild_name=str((manifest.guild or {}).get("name") or ""),
        app_version=manifest.app_version,
        exported_at=manifest.exported_at.isoformat(),
        schema_version=manifest.schema_version,
        initiatives=initiatives,
        asset_count=len(manifest.assets),
        asset_bytes=sum(a.size_bytes for a in manifest.assets),
        skipped=[s.model_dump(mode="json") for s in manifest.skipped],
        unknown_types=unknown_types,
    )


async def apply_backup(
    session: AsyncSession,
    *,
    user: User,
    guild_id: int,
    payload: bytes,
    include: dict[str, bool] | None,
) -> BackupImportResult:
    """Restore a backup zip into new initiatives, as ``user``, on the
    worker's creator-routed session. Flushes and COMMITS per chunk (the
    always-create policy makes partial progress durable and never re-run)."""
    from app.api.deps import establish_guild_access
    from app.services.import_engine.importers import IMPORTERS
    from app.services.platform import guilds as guilds_service
    from app.services.rls import is_guild_admin
    from app.services.tenant import initiatives as initiatives_service

    # Re-verify REAL guild adminship at apply time — enqueue-time authority
    # can be gone by now, and a backup import creates initiatives.
    membership = await guilds_service.get_membership(
        session, guild_id=guild_id, user_id=user.id
    )
    if membership is None or not is_guild_admin(membership.role):
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_ADMIN_REQUIRED, status_code=403
        )

    archive = open_backup_zip(payload)
    manifest = read_manifest(archive)
    result = BackupImportResult()

    # Assets first, one chunk: written under their ORIGINAL storage keys so
    # embedded editor-state image references resolve without rewriting.
    if manifest.assets:
        await _restore_assets(session, archive, manifest, guild_id, user, result)
        await session.commit()

    assets_by_key = {a.storage_key: a for a in manifest.assets}
    entries_by_initiative: dict[int, list[ManifestEntry]] = {}
    for entry in manifest.entries:
        entries_by_initiative.setdefault(entry.initiative_id, []).append(entry)

    since_refresh = 0
    from app.models.tenant.initiative import Initiative

    for mi in manifest.initiatives:
        await establish_guild_access(session, user, guild_id)
        initiative = await initiatives_service.create_imported_initiative(
            session,
            guild_id=guild_id,
            name=mi.name,
            description=mi.description,
            color=mi.color,
            tool_flags={
                # "disabled" -> off; "included"/"excluded" -> on (the switch
                # reflects the source's configuration, not the include map).
                f"{tool}s_enabled": state != "disabled"
                for tool, state in (mi.tools or {}).items()
            },
            manager_id=user.id,
        )
        result.initiatives.append(
            {
                "source_id": mi.id,
                "initiative_id": initiative.id,
                "name": initiative.name,
            }
        )

        entries = sorted(
            entries_by_initiative.get(mi.id, []),
            key=lambda e: (
                _TOOL_ORDER.index(e.tool) if e.tool in _TOOL_ORDER else len(_TOOL_ORDER)
            ),
        )
        for entry in entries:
            since_refresh += 1
            if since_refresh >= _REFRESH_EVERY:
                await session.commit()
                await establish_guild_access(session, user, guild_id)
                # Re-load the initiative on the refreshed transaction.
                initiative = (
                    await session.exec(
                        select(Initiative).where(Initiative.id == initiative.id)
                    )
                ).one()
                since_refresh = 0
            outcome = await _apply_entry(
                session,
                archive=archive,
                entry=entry,
                initiative=initiative,
                user=user,
                include=include,
                importers=IMPORTERS,
                assets_by_key=assets_by_key,
                result=result,
            )
            result.entries.append(outcome)
            bucket = result.per_tool.setdefault(
                entry.tool, {"created": 0, "failed": 0, "skipped": 0}
            )
            bucket[outcome.status] += 1
        await session.commit()

    return result


async def _apply_entry(
    session: AsyncSession,
    *,
    archive: zipfile.ZipFile,
    entry: ManifestEntry,
    initiative,
    user: User,
    include: dict[str, bool] | None,
    importers: dict,
    assets_by_key: dict[str, Any],
    result: BackupImportResult,
) -> EntryResult:
    base = {
        "path": entry.path,
        "tool": entry.tool,
        "type": entry.type,
        "title": entry.title,
    }
    if include is not None and not include.get(entry.tool, True):
        return EntryResult(**base, status="skipped")
    if entry.type == "file":
        return await _apply_file_entry(
            session, entry, initiative, user, assets_by_key, base
        )
    importer = importers.get(entry.type)
    if importer is None:
        return EntryResult(**base, status="skipped", error="IMPORT_UNKNOWN_TYPE")
    try:
        raw = json.loads(archive.read(entry.path))
        validated = importer.validate(_normalize_type_field(raw))
        async with session.begin_nested():
            detail = await importer.apply(
                session,
                envelope=validated,
                target_initiative=initiative,
                importer=user,
            )
    except ImportEngineError as exc:
        logger.warning(
            "backup entry failed path=%s tool=%s code=%s",
            entry.path,
            entry.tool,
            exc.code,
        )
        return EntryResult(**base, status="failed", error=exc.code)
    except Exception:
        # Savepoint isolation stands, but the traceback must reach the logs —
        # the result JSON carries only a status code.
        logger.exception("backup entry failed path=%s tool=%s", entry.path, entry.tool)
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_APPLY_FAILED
        )
    result.unmatched_emails = sorted(
        set(result.unmatched_emails) | set(detail.unmatched_emails)
    )
    return EntryResult(**base, status="created", detail=detail)


async def _apply_file_entry(
    session: AsyncSession,
    entry: ManifestEntry,
    initiative,
    user: User,
    assets_by_key: dict[str, Any],
    base: dict,
) -> EntryResult:
    """A file document: its content is the restored ``assets/`` blob."""
    from app.models.tenant.document import Document, DocumentType
    from app.models.tenant.property import DocumentPropertyValue
    from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
    from app.models.tenant.tag import DocumentTag
    from app.models.tenant.upload import Upload
    from app.schemas.tenant.import_envelopes import EnvelopePropertyValue
    from app.services.import_engine.common import (
        ensure_tag,
        load_initiative_member_emails,
    )
    from app.services.import_engine.importers._base import resolve_property_values

    storage_key = (entry.asset or "").removeprefix("assets/")
    if not storage_key:
        return EntryResult(**base, status="failed", error="IMPORT_INVALID_ENVELOPE")
    asset = assets_by_key.get(storage_key)
    upload = (
        await session.exec(select(Upload).where(Upload.filename == storage_key))
    ).one_or_none()
    if upload is None:
        # Uploads were excluded from this backup (or the blob failed to
        # restore) — recorded, not silently dropped.
        return EntryResult(**base, status="skipped", error="IMPORT_ASSET_MISSING")

    try:
        async with session.begin_nested():
            document = Document(
                title=entry.title,
                document_type=DocumentType.file,
                content={},
                initiative_id=initiative.id,
                guild_id=initiative.guild_id,
                created_by_id=user.id,
                updated_by_id=user.id,
                file_url=f"/uploads/{initiative.guild_id}/{storage_key}",
                # The original name lives in the manifest's asset record —
                # the uploads row's filename IS the storage key.
                original_filename=(
                    asset.original_filename if asset is not None else storage_key
                ),
                file_content_type=upload.content_type,
                file_size=upload.size_bytes,
            )
            session.add(document)
            await session.flush()
            session.add(
                ResourceGrant(
                    resource_type="document",
                    resource_id=document.id,
                    user_id=user.id,
                    role_id=None,
                    level=ResourceAccessLevel.owner,
                    guild_id=initiative.guild_id,
                    initiative_id=initiative.id,
                )
            )
            for tag_name in entry.tags:
                resolved = await ensure_tag(
                    session,
                    guild_id=initiative.guild_id,
                    name=tag_name,
                    color="#6b7280",
                )
                session.add(DocumentTag(document_id=document.id, tag_id=resolved.id))
            if entry.properties:
                values = [
                    EnvelopePropertyValue.model_validate(p) for p in entry.properties
                ]
                member_emails = await load_initiative_member_emails(
                    session, initiative_id=initiative.id
                )
                attached = await resolve_property_values(
                    session,
                    initiative_id=initiative.id,
                    values=values,
                    member_emails=member_emails,
                )
                for prop_id, column_kwargs in attached.column_kwargs_by_id.items():
                    session.add(
                        DocumentPropertyValue(
                            document_id=document.id,
                            property_id=prop_id,
                            **column_kwargs,
                        )
                    )
    except Exception:
        logger.exception(
            "backup file entry failed path=%s asset=%s", entry.path, entry.asset
        )
        return EntryResult(
            **base, status="failed", error=ImportEngineMessages.IMPORT_APPLY_FAILED
        )
    return EntryResult(**base, status="created")


async def _restore_assets(
    session: AsyncSession,
    archive: zipfile.ZipFile,
    manifest: BackupManifest,
    guild_id: int,
    user: User,
    result: BackupImportResult,
) -> None:
    """Write ``assets/`` blobs to guild storage under their original keys,
    register ``uploads`` rows, dedup against keys that already exist (a
    re-import of the same backup), and enforce the guild's storage quota."""
    from app.models.tenant.upload import Upload
    from app.services.storage import get_guild_storage
    from app.services.tenant.attachments import (
        StorageQuotaExceededError,
        compute_content_hash,
        enforce_storage_quota,
    )

    storage = get_guild_storage(guild_id)
    incoming = 0
    to_restore = []
    for asset in manifest.assets:
        existing = (
            await session.exec(
                select(Upload).where(Upload.filename == asset.storage_key)
            )
        ).one_or_none()
        if existing is not None:
            result.assets_deduped += 1
            continue
        # Quota accumulates from the zip's OWN central-directory size, never
        # the manifest's declared size_bytes: the manifest is caller-supplied
        # text and could understate to slip past the guild's storage cap.
        # zipfile guarantees .read() returns at most info.file_size (a
        # mismatching stream fails the CRC check), so this is the true upper
        # bound of what gets written.
        try:
            info = archive.getinfo(asset.path)
        except KeyError:
            result.warnings.append(f"asset_missing:{asset.storage_key}")
            continue
        incoming += info.file_size
        to_restore.append(asset)

    try:
        await enforce_storage_quota(session, guild_id=guild_id, incoming_bytes=incoming)
    except StorageQuotaExceededError as exc:
        raise ImportEngineError(
            ImportEngineMessages.IMPORT_QUOTA_EXCEEDED, status_code=400
        ) from exc

    for asset in to_restore:
        try:
            data = archive.read(asset.path)
        except Exception:
            result.warnings.append(f"asset_missing:{asset.storage_key}")
            continue
        storage.write(
            asset.storage_key,
            data,
            content_type=asset.content_type or "application/octet-stream",
        )
        session.add(
            Upload(
                filename=asset.storage_key,
                guild_id=guild_id,
                uploader_user_id=user.id,
                size_bytes=len(data),
                content_type=asset.content_type,
                content_hash=compute_content_hash(data),
            )
        )
        result.assets_restored += 1
        result.asset_bytes += len(data)
