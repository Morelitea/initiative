"""API payloads for export jobs. ``params`` is the caller's own filter
selector (echoed back so a client can re-run the export); the row never
carries exported content — the artifact is fetched via the download route."""

from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict, Field, computed_field

from app.models.tenant.export_job import ExportJobStatus
from app.schemas.base import SanitizedBaseModel


class ExportJobRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    created_by: int
    source: str
    template_id: str
    format: str
    params: dict[str, Any]
    status: ExportJobStatus
    error: Optional[str] = None
    expires_at: Optional[datetime] = None
    # Read from the row so ``delivered`` can be computed, and excluded from
    # the payload: the destination is a path on the server, which the operator
    # configured and already knows. A community administrator needs to know
    # that an archive was delivered rather than where this deployment keeps
    # its files.
    destination_ref: Optional[str] = Field(default=None, exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delivered(self) -> bool:
        """The archive went to the operator's destination; there is nothing
        here to download."""
        return self.destination_ref is not None

    created_at: datetime
    updated_at: datetime
