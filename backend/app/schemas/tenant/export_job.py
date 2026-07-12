"""API payloads for export jobs. ``params`` is the caller's own filter
selector (echoed back so a client can re-run the export); the row never
carries exported content — the artifact is fetched via the download route."""

from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict

from app.models.tenant.export_job import ExportJobStatus
from app.schemas.base import SanitizedBaseModel


class ExportJobRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    created_by_id: int
    source: str
    template_id: str
    format: str
    params: dict[str, Any]
    status: ExportJobStatus
    error: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
