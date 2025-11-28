from __future__ import annotations

from pydantic import BaseModel


class AttachmentUploadResponse(BaseModel):
    filename: str
    url: str
    content_type: str
    size: int
