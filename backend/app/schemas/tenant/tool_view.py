"""Schemas for an initiative's views of a tool, and its item layouts.

A view and an item layout are trees of registered parts: a ``card`` holds what
an item shows, a ``stack`` lays its children out, a ``field`` draws one field
and ``properties`` draws every property the item carries. The parts, their
props, the layouts and the built-in field ids are ``Literal``s or enums, so the
generated client carries the same vocabulary the renderer keys by. A
property's field is named ``property:<definition id>``, so renaming it keeps
every view that shows it.

``TaskFilterSpec`` is the normalized filter shape a view stores. It mirrors
what the task filter panel can render rather than the ``conditions`` DSL the
list endpoint accepts: the panel must be able to show a view's filters back as
controls, project duplication must remap per-project status ids, and neither is
possible against an arbitrary condition tree. The per-field caps also keep a
maximal spec comfortably inside the DSL's own limits.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, List, Literal, Optional, Union

from pydantic import AfterValidator, ConfigDict, Field, field_validator

from app.models.tenant.task import TaskStatusCategory
from app.schemas.base import SanitizedBaseModel
from app.schemas.query import FilterOp
from app.services.tenant.properties import MAX_PROPERTY_FILTERS

# An assignee list holds user ids as strings alongside two tokens that only
# mean something at query time: "me" resolves to the requesting user (the list
# endpoint already does this), "none" means the task has no assignee at all.
# Keeping them as tokens is what makes a view, and a link to it, portable
# between people.
ASSIGNEE_ME = "me"
ASSIGNEE_NONE = "none"

# The same tokens the filter control has always used; ``None`` is "any".
DueToken = Literal["overdue", "today", "7_days", "30_days"]

MAX_STATUS_IDS = 50
MAX_ASSIGNEES = 25
MAX_TAG_IDS = 25

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_SLUG_LENGTH = 64

#: Views per target, and what one view or item layout may hold. Every part of
#: a tree counts as a node, as does every column and every sort. A project
#: kept up to 30 filter presets, which became views beside the shipped six.
MAX_VIEWS = 40
MAX_NODES = 300
MAX_DEPTH = 6
MAX_DEFINITION_BYTES = 64 * 1024


class _Strict(SanitizedBaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskPropertyFilter(_Strict):
    property_id: int
    op: FilterOp = FilterOp.eq
    value: Any = None


class TaskFilterSpec(_Strict):
    """The filter values a task view holds. Unknown keys are rejected."""

    status_ids: List[int] = Field(default_factory=list, max_length=MAX_STATUS_IDS)
    status_categories: List[TaskStatusCategory] = Field(default_factory=list)
    assignees: List[str] = Field(default_factory=list, max_length=MAX_ASSIGNEES)
    tag_ids: List[int] = Field(default_factory=list, max_length=MAX_TAG_IDS)
    properties: List[TaskPropertyFilter] = Field(
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


# -- Fields -------------------------------------------------------------------


class TaskFieldId(str, Enum):
    """A task's built-in fields, by the ids the renderer keys them by. An enum
    rather than a ``Literal`` so the generated client names the set."""

    title = "title"
    description = "description"
    assignees = "assignees"
    startDate = "startDate"
    dueDate = "dueDate"
    recurrence = "recurrence"
    checklist = "checklist"
    priority = "priority"
    comments = "comments"
    blockers = "blockers"
    tags = "tags"


PROPERTY_FIELD_PREFIX = "property:"
#: The characters a property's definition id is written in.
_DIGITS = frozenset("0123456789")
#: A definition id is a Postgres ``integer``: at most ten digits.
_MAX_ID_DIGITS = 10


def _property_field(value: str) -> str:
    """``property:<definition id>``. By id rather than by name, so renaming a
    property keeps every view that shows it."""
    rest = value.removeprefix(PROPERTY_FIELD_PREFIX)
    if (
        rest == value
        or not 0 < len(rest) <= _MAX_ID_DIGITS
        or not set(rest) <= _DIGITS
        or rest.startswith("0")
    ):
        raise ValueError("a field is a built-in field id or 'property:<id>'")
    return value


PropertyFieldId = Annotated[str, AfterValidator(_property_field)]
ViewFieldId = Union[TaskFieldId, PropertyFieldId]


# -- Parts --------------------------------------------------------------------


class StackProps(_Strict):
    direction: Optional[Literal["column", "row"]] = None
    gap: Optional[Literal["xs", "sm"]] = None
    wrap: Optional[bool] = None
    #: Items keep their own width rather than filling the column.
    align: Optional[Literal["start"]] = None
    tone: Optional[Literal["muted"]] = None


class FieldProps(_Strict):
    field: ViewFieldId


class CardPart(_Strict):
    type: Literal["card"]
    children: List[ViewPart] = Field(default_factory=list)


class StackPart(_Strict):
    type: Literal["stack"]
    props: Optional[StackProps] = None
    children: List[ViewPart] = Field(default_factory=list)


class FieldPart(_Strict):
    type: Literal["field"]
    props: FieldProps


class PropertiesPart(_Strict):
    """Every property the item carries, in its own order."""

    type: Literal["properties"]


ViewPart = Annotated[
    Union[CardPart, StackPart, FieldPart, PropertiesPart],
    Field(discriminator="type"),
]

CardPart.model_rebuild()
StackPart.model_rebuild()


# -- Definitions --------------------------------------------------------------

#: Every layout a view can take; which of them a tool draws is
#: ``app.services.tenant.tool_views.LAYOUTS``.
ViewLayoutType = Literal["table", "board", "calendar"]
#: Every kind of item an item layout can lay out; which a tool holds is
#: ``app.services.tenant.tool_views.ITEM_KINDS``.
ItemLayoutKind = Literal["task"]


class ViewLayout(_Strict):
    type: ViewLayoutType


class ViewSort(_Strict):
    field: ViewFieldId
    direction: Literal["asc", "desc"] = "asc"


class ViewDefinition(_Strict):
    """A view. What it leaves out is drawn as shipped: a view with no ``card``
    draws the shipped card, one with no ``columns`` the shipped columns."""

    layout: ViewLayout
    filters: Optional[TaskFilterSpec] = None
    card: Optional[CardPart] = None
    columns: Optional[List[ViewFieldId]] = None
    sort: Optional[List[ViewSort]] = None
    #: How an item opens: in a side panel or on its own page.
    opens: Optional[Literal["panel", "page"]] = None


class ItemLayoutDefinition(_Strict):
    """An item's page, in three regions. A field placed in none of them is
    drawn in a "More fields" section."""

    header: Optional[ViewPart] = None
    main: Optional[ViewPart] = None
    side: Optional[ViewPart] = None


# -- Requests -----------------------------------------------------------------


class ToolViewWrite(_Strict):
    name: str = Field(min_length=1, max_length=100)
    #: What a link to the view carries. Derived from the name when left out.
    slug: Optional[str] = Field(
        default=None, max_length=MAX_SLUG_LENGTH, pattern=SLUG_PATTERN
    )
    is_default: bool = False
    definition: ViewDefinition


class ToolItemLayoutWrite(_Strict):
    item_kind: ItemLayoutKind
    definition: ItemLayoutDefinition


class ToolViewSetWrite(_Strict):
    """A target's whole set, in order. It replaces whatever was stored."""

    #: At most ``MAX_VIEWS``, which the service checks so the refusal names it.
    views: List[ToolViewWrite] = Field(min_length=1)
    item_layouts: List[ToolItemLayoutWrite] = Field(default_factory=list)


# -- Responses ----------------------------------------------------------------


class ToolViewRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: None for a shipped view, which is stored nowhere.
    id: Optional[int] = None
    name: str
    slug: str
    position: int
    is_default: bool
    definition: ViewDefinition


class ToolItemLayoutRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    id: int
    item_kind: ItemLayoutKind
    definition: ItemLayoutDefinition


class ToolViewSetRead(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    views: List[ToolViewRead]
    item_layouts: List[ToolItemLayoutRead]
    #: Whether the set is the target's own. False: these are the shipped views.
    stored: bool
    #: Whether this reader may change the set, computed server-side.
    can_configure: bool
