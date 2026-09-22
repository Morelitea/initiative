from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.core.tools import TAG_TARGETS
from app.schemas.base import SanitizedBaseModel, TitleStr


class TagBase(SanitizedBaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    color: str = Field(default="#6366F1", pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Tag name cannot be empty")
        return v


class TagCreate(TagBase):
    name: TitleStr = Field(..., min_length=1, max_length=100)


class TagUpdate(SanitizedBaseModel):
    name: Optional[TitleStr] = Field(default=None, min_length=1, max_length=100)
    color: Optional[str] = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Tag name cannot be empty")
        return v


class TagSummary(SanitizedBaseModel):
    """Lightweight tag representation for embedding in other schemas."""

    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    color: str


def tag_summaries(tags) -> List[TagSummary]:
    """Serialize tag rows to ``TagSummary`` — the one serializer every taggable
    entity uses. The caller has already dropped anything trashed; this only
    shapes what is left."""
    return [TagSummary(id=tag.id, name=tag.name, color=tag.color) for tag in tags or []]


def annotated_tags(entity) -> List[TagSummary]:
    """The summaries ``tags_service.annotate_tags`` put on this entity.

    Read rather than recomputed: assignments live in one table now and are
    fetched for a whole page at once, so a serializer that went looking for
    them itself would be a query per card.
    """
    return list(getattr(entity, "tags", None) or [])


class TagRead(TagBase):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    guild_id: int
    created_at: datetime
    updated_at: datetime


class TagSetRequest(SanitizedBaseModel):
    """Request body for setting tags on an entity."""

    tag_ids: List[int] = Field(default_factory=list, max_length=100)


# Derived, never re-declared: every Tool value plus the content-level extras
# (see TAG_TARGETS in app.core.tools). A new Tool lands here — and in the
# OpenAPI spec / generated frontend types — automatically.
TagTarget = Enum("TagTarget", {name: name for name in TAG_TARGETS}, type=str)
TagTarget.__doc__ = "Entity types a bulk tag edit can address."


class TagBulkEditRequest(SanitizedBaseModel):
    """Add and/or remove tags across many entities of one type, atomically."""

    target_type: TagTarget
    target_ids: List[int] = Field(min_length=1, max_length=500)
    add_tag_ids: List[int] = Field(default_factory=list, max_length=100)
    remove_tag_ids: List[int] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def require_an_operation(self) -> "TagBulkEditRequest":
        if not self.add_tag_ids and not self.remove_tag_ids:
            raise ValueError("add_tag_ids or remove_tag_ids must be non-empty")
        return self


class TagBulkEditResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    updated_count: int


class TaggedEntitiesResponse(SanitizedBaseModel):
    """Response for GET /tags/{id}/entities - all entities with a given tag."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    tasks: List["TaggedTaskSummary"] = Field(default_factory=list)
    projects: List["TaggedProjectSummary"] = Field(default_factory=list)
    documents: List["TaggedDocumentSummary"] = Field(default_factory=list)


class TaggedTaskSummary(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    title: str
    project_id: int
    project_name: Optional[str] = None


class TaggedProjectSummary(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    initiative_id: int
    initiative_name: Optional[str] = None


class TaggedDocumentSummary(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    name: str
    initiative_id: int
    initiative_name: Optional[str] = None


class TaggedEventSummary(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    title: str
    initiative_id: int
    initiative_name: Optional[str] = None


# Update forward references
TaggedEntitiesResponse.model_rebuild()
