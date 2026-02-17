from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#6366F1", pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Tag name cannot be empty")
        return v


class TagCreate(TagBase):
    pass


class TagUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Tag name cannot be empty")
        return v


class TagSummary(BaseModel):
    """Lightweight tag representation for embedding in other schemas."""
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    name: str
    color: str


class TagRead(TagBase):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    guild_id: int
    created_at: datetime
    updated_at: datetime


class TagSetRequest(BaseModel):
    """Request body for setting tags on an entity."""
    tag_ids: List[int] = Field(default_factory=list)


class TaggedEntitiesResponse(BaseModel):
    """Response for GET /tags/{id}/entities - all entities with a given tag."""
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tasks: List["TaggedTaskSummary"] = Field(default_factory=list)
    projects: List["TaggedProjectSummary"] = Field(default_factory=list)
    documents: List["TaggedDocumentSummary"] = Field(default_factory=list)


class TaggedTaskSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    title: str
    project_id: int
    project_name: Optional[str] = None


class TaggedProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    name: str
    initiative_id: int
    initiative_name: Optional[str] = None


class TaggedDocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, json_schema_serialization_defaults_required=True)

    id: int
    title: str
    initiative_id: int
    initiative_name: Optional[str] = None


# Update forward references
TaggedEntitiesResponse.model_rebuild()
