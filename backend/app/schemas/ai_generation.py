"""AI Generation request and response schemas."""

from pydantic import BaseModel, ConfigDict


class GenerateSubtasksResponse(BaseModel):
    """Response schema for subtask generation."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    subtasks: list[str]


class GenerateDescriptionResponse(BaseModel):
    """Response schema for description generation."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    description: str


class GenerateDocumentSummaryResponse(BaseModel):
    """Response schema for document summarization."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    summary: str
