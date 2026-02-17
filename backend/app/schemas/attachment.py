from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AttachmentUploadResponse(BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    filename: str
    url: str
    content_type: str
    size: int
