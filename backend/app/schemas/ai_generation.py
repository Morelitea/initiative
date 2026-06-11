"""AI Generation request and response schemas."""

from pydantic import ConfigDict

from app.schemas.base import RawTextStr, SanitizedBaseModel


class GenerateSubtasksResponse(SanitizedBaseModel):
    """Response schema for subtask generation."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    subtasks: list[str]


class GenerateDescriptionResponse(SanitizedBaseModel):
    """Response schema for description generation."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    description: RawTextStr


class GenerateDocumentSummaryResponse(SanitizedBaseModel):
    """Response schema for document summarization."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    summary: RawTextStr
