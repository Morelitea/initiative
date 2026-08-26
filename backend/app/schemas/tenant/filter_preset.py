"""Schemas for project filter presets.

``TaskFilterSpec`` is the normalized shape a preset stores. It deliberately
mirrors what the task filter panel can render rather than the ``conditions``
DSL the list endpoint accepts: the panel must be able to show a preset back as
controls, project duplication must remap per-project status ids, and neither is
possible against an arbitrary condition tree. The per-field caps also keep a
maximal preset comfortably inside the DSL's own limits, so a saved preset can
never make the list endpoint reject its own filters.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import ConfigDict, Field, field_validator

from app.core.tools import Tool
from app.models.tenant.task import TaskStatusCategory
from app.schemas.base import SanitizedBaseModel
from app.schemas.query import FilterOp
from app.services.tenant.properties import MAX_PROPERTY_FILTERS

# A preset's assignee list holds user ids as strings alongside two tokens that
# only mean something at query time: "me" resolves to the requesting user (the
# list endpoint already does this), "none" means the task has no assignee at
# all. Keeping them as tokens is what makes a preset — and a link to it —
# portable between people.
ASSIGNEE_ME = "me"
ASSIGNEE_NONE = "none"

# The same tokens the filter control has always used; ``None`` is "any".
DueToken = Literal["overdue", "today", "7_days", "30_days"]

MAX_STATUS_IDS = 50
MAX_ASSIGNEES = 25
MAX_TAG_IDS = 25

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class PresetPropertyFilter(SanitizedBaseModel):
    model_config = ConfigDict(extra="forbid")

    property_id: int
    op: FilterOp = FilterOp.eq
    value: Any = None


class TaskFilterSpec(SanitizedBaseModel):
    """The filter values a task preset holds. Unknown keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    status_ids: List[int] = Field(default_factory=list, max_length=MAX_STATUS_IDS)
    status_categories: List[TaskStatusCategory] = Field(default_factory=list)
    assignees: List[str] = Field(default_factory=list, max_length=MAX_ASSIGNEES)
    tag_ids: List[int] = Field(default_factory=list, max_length=MAX_TAG_IDS)
    properties: List[PresetPropertyFilter] = Field(
        default_factory=list, max_length=MAX_PROPERTY_FILTERS
    )
    due: Optional[DueToken] = None
    include_archived: bool = False

    @field_validator("assignees")
    @classmethod
    def _validate_assignees(cls, value: List[str]) -> List[str]:
        for entry in value:
            if entry in (ASSIGNEE_ME, ASSIGNEE_NONE):
                continue
            if not entry.isdigit():
                raise ValueError("assignees entries must be a user id, 'me', or 'none'")
        return value

    @field_validator("status_categories")
    @classmethod
    def _dedupe_categories(
        cls, value: List[TaskStatusCategory]
    ) -> List[TaskStatusCategory]:
        seen: list[TaskStatusCategory] = []
        for entry in value:
            if entry not in seen:
                seen.append(entry)
        return seen


# One validator per tool. Presets are project-only today; a second tool adopting
# them registers its own spec here rather than widening this one.
FILTER_SPEC_VALIDATORS: dict[Tool, type[SanitizedBaseModel]] = {
    Tool.project: TaskFilterSpec,
}


class FilterPresetCreate(SanitizedBaseModel):
    name: str = Field(min_length=1, max_length=100)
    filters: TaskFilterSpec = Field(default_factory=TaskFilterSpec)
    is_default: bool = False
    position: Optional[int] = Field(default=None, ge=0)


class FilterPresetUpdate(SanitizedBaseModel):
    """Everything but ``slug`` — a slug is what a shared link carries."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    filters: Optional[TaskFilterSpec] = None
    is_default: Optional[bool] = None
    position: Optional[int] = Field(default=None, ge=0)


class FilterPresetRead(SanitizedBaseModel):
    model_config = ConfigDict(
        from_attributes=True, json_schema_serialization_defaults_required=True
    )

    id: int
    project_id: int
    slug: str
    name: str
    position: int
    is_default: bool
    filters: TaskFilterSpec
    created_at: datetime
    updated_at: datetime


class FilterPresetListResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: List[FilterPresetRead]
    # Computed server-side: whether this user may add/edit/reorder/delete
    # presets and set the project's default view. Never derived client-side.
    can_manage: bool = False


class FilterPresetReorderItem(SanitizedBaseModel):
    id: int
    position: int = Field(ge=0)


class FilterPresetReorderRequest(SanitizedBaseModel):
    items: List[FilterPresetReorderItem]
