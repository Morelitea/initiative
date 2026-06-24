from __future__ import annotations

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel


class AttachmentUploadResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    filename: str
    url: str
    content_type: str
    size: int
