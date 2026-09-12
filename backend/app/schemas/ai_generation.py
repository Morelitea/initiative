"""AI Generation request and response schemas."""

from pydantic import ConfigDict

from app.schemas.base import RawTextStr, SanitizedBaseModel


class GenerateChecklistResponse(SanitizedBaseModel):
    """Suggested checklist lines, as text — the caller decides which to keep."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[str]


class GenerateDescriptionResponse(SanitizedBaseModel):
    """Response schema for description generation."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    description: RawTextStr


class GenerateDocumentSummaryResponse(SanitizedBaseModel):
    """Response schema for document summarization."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    summary: RawTextStr
