"""API payloads for import jobs. ``params`` is the caller's own options
(target initiative, include map) echoed back; ``plan``/``result`` are the
pre-flight summary and terminal report — the row never carries envelope
content (large payloads are staged behind storage and deleted on terminal
states)."""

from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict

from app.models.tenant.import_job import ImportJobStatus
from app.schemas.base import SanitizedBaseModel
from app.services.import_engine.contract import EnvelopeImportResult


class ImportJobRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    created_by_id: int
    source: str
    params: dict[str, Any]
    plan: Optional[dict[str, Any]] = None
    result: Optional[dict[str, Any]] = None
    status: ImportJobStatus
    error: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class EnvelopeImportRequest(SanitizedBaseModel):
    """Body of ``POST /imports/envelope``. The envelope is a raw dict —
    its ``type`` field selects the importer, which validates the full shape
    (typing it as a union here would split the OpenAPI schema per type)."""

    initiative_id: int
    envelope: dict[str, Any]


class EnvelopeImportResponse(SanitizedBaseModel):
    """201 body for an inline (small) envelope import."""

    result: EnvelopeImportResult


class EntryResult(SanitizedBaseModel):
    """One manifest entry's apply outcome inside a backup import."""

    path: str
    tool: str
    type: str
    title: str
    status: str  # "created" | "failed" | "skipped"
    error: Optional[str] = None  # short code, never content
    detail: Optional[EnvelopeImportResult] = None


class BackupPlanInitiative(SanitizedBaseModel):
    """One initiative in the pre-flight plan: what would be created."""

    source_id: int
    name: str
    proposed_name: str
    tools: dict[str, str]  # tool -> "included" | "excluded" | "disabled"
    entry_counts: dict[str, int]  # tool -> entries in the zip


class BackupImportPlan(SanitizedBaseModel):
    """The confirm-screen summary, persisted to ``import_jobs.plan`` —
    counts and names only, never envelope content."""

    source_guild_name: str = ""
    app_version: str = ""
    exported_at: Optional[str] = None
    schema_version: int = 0
    initiatives: list[BackupPlanInitiative] = []
    asset_count: int = 0
    asset_bytes: int = 0
    skipped: list[dict[str, Any]] = []
    unknown_types: list[str] = []


class BackupImportResult(SanitizedBaseModel):
    """Terminal report for a backup import, persisted to
    ``import_jobs.result``."""

    initiatives: list[dict[str, Any]] = []  # {source_id, initiative_id, name}
    per_tool: dict[str, dict[str, int]] = {}  # tool -> {created, failed, skipped}
    entries: list[EntryResult] = []
    assets_restored: int = 0
    assets_deduped: int = 0
    asset_bytes: int = 0
    unmatched_emails: list[str] = []
    warnings: list[str] = []
