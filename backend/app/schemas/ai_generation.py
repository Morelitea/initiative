"""AI Generation request and response schemas."""

from pydantic import BaseModel


class GenerateSubtasksResponse(BaseModel):
    """Response schema for subtask generation."""
    subtasks: list[str]


class GenerateDescriptionResponse(BaseModel):
    """Response schema for description generation."""
    description: str
