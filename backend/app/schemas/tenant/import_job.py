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
