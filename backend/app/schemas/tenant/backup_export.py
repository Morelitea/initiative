"""Initiative/guild backup manifest — the index at the root of a backup zip.

A backup is a zip of per-tool JSON envelopes (each independently versioned by
its own ``type`` + ``schema_version``) plus optional upload blobs under
``assets/``. The manifest is what a future import wizard reads first: it
inventories every entry by type so files dispatch to the right importer, maps
assets back to the documents that reference them, and records what was
deliberately left out (``skipped``) so a backup never silently loses data.

Privacy rule: ``skipped`` lists only items the exporter can SEE but policy
excluded (e.g. file documents when uploads are excluded). Rows invisible to
the exporter under sharing rules are simply absent everywhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.schemas.base import SanitizedBaseModel

BACKUP_SCHEMA_VERSION = 1
MIN_SUPPORTED_IMPORT_VERSION = 1


class ManifestEntry(SanitizedBaseModel):
    """One exported file inside the archive."""

    path: str
    tool: str  # "project" | "document" | "queue" | "counter_group" | "calendar_event"
    type: str  # envelope type, or "file"
    schema_version: Optional[int] = None  # None for foreign formats
    entity_id: int
    title: str
    initiative_id: int
    # Metadata for entries whose file format can't carry it itself
    # (file entries are raw blobs; envelopes carry their own tags/properties).
    tags: list[str] = []
    properties: list[dict] = []
    # ``assets/{storage_key}`` for file documents (the blob IS the document).
    asset: Optional[str] = None


class ManifestAsset(SanitizedBaseModel):
    """One upload blob under ``assets/``, keyed by its storage key (unique by
    construction); the original filename lives here, not in the entry name."""

    path: str
    storage_key: str
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: int = 0
    referenced_by: list[str] = []


class ManifestSkipped(SanitizedBaseModel):
    tool: str
    entity_id: int
    title: str
    initiative_id: int
    reason: str  # "uploads_excluded" | ...


class ManifestInitiative(SanitizedBaseModel):
    id: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    # tool -> "included" | "excluded" | "disabled" (per-initiative flag off)
    tools: dict[str, str]


class BackupManifest(SanitizedBaseModel):
    type: str  # "initiative-backup" | "guild-backup"
    schema_version: int = BACKUP_SCHEMA_VERSION
    app_version: str
    exported_at: datetime
    exported_by_email: Optional[str] = None
    source_instance_url: Optional[str] = None
    guild: dict[str, Any]
    include_uploads: bool
    initiatives: list[ManifestInitiative]
    entries: list[ManifestEntry]
    assets: list[ManifestAsset]
    skipped: list[ManifestSkipped]


class BackupToolEstimate(SanitizedBaseModel):
    count: int = 0
    disabled: bool = False


class BackupEstimate(SanitizedBaseModel):
    """The wizard's pre-flight numbers: per-tool entity counts, the uploads
    footprint (approximate — embedded document images resolve at build time),
    and the row/byte ceilings so the client can warn before submitting."""

    tools: dict[str, BackupToolEstimate]
    uploads_count: int = 0
    uploads_bytes: int = 0
    uploads_approximate: bool = True
    estimated_rows: int = 0
    max_rows: int = 0
    max_upload_bytes: int = 0
