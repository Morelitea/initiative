"""Schemas for how an instance of a tool draws its items: its layouts.

A target has one layout of each kind its tool draws: how it lists its items (a
project's table, board and calendar), and how it shows one of them (its task).
A layout says how things are drawn; what a person narrows a list to and how
they sort it are theirs, not the layout's. A list can offer them presets: named
filters (and, for a table, a sort) that a person picks to start from.

A layout is a tree of registered parts: a ``card`` holds what an item shows, a
``stack`` lays its children out, a ``field`` draws one field, ``properties``
draws every property the item carries and ``plugin`` draws one of an installed
plug-in's parts. A detail layout adds ``section`` and the detail's own parts
(a task's status, dates, comments and the rest). The parts, their props, the kinds
and the built-in field ids are ``Literal``s or enums, so the generated client
carries the same vocabulary the renderer keys by. A property's field is named
``property:<definition id>``, so renaming it keeps every layout that shows it;
a plug-in's is ``plugin:<install id>:<metadata key>``.

``TaskFilterSpec`` is the filter shape a preset holds. It mirrors what the
task filter controls show rather than the ``conditions`` DSL the list endpoint
accepts, so a preset reads back as controls and a copied project can remap its
status ids.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, List, Literal, Optional, Union, get_args

from pydantic import AfterValidator, ConfigDict, Field, field_validator

from app.core.tools import Tool
from app.models.tenant.task import TaskStatusCategory
from app.schemas.base import SanitizedBaseModel
from app.schemas.query import FilterOp, SortDir
from app.services.marketplace.manifest_values import (
    IDENTIFIER_CHARS,
    MAX_IDENTIFIER_LENGTH,
    is_metadata_key,
)
from app.services.tenant.properties import MAX_PROPERTY_FILTERS

#: What one layout may hold. Every part of a tree counts as a
#: node, as does every column.
MAX_NODES = 300
MAX_DEPTH = 6
MAX_DEFINITION_BYTES = 64 * 1024
#: One plug-in's parts on one task: on a card, or across its detail.
MAX_PLUGIN_PARTS = 3
#: Presets on one list.
MAX_PRESETS = 20

# An assignee list holds user ids as strings beside two tokens that mean
# something only when the list is read: "me" is whoever reads it, "none" a task
# with no assignee. That is what makes a preset, and a link to it, mean the
# same for everyone.
ASSIGNEE_ME = "me"
ASSIGNEE_NONE = "none"

#: The tokens the due filter uses; ``None`` is any date.
DueToken = Literal["overdue", "today", "7_days", "30_days"]

MAX_STATUS_IDS = 50
MAX_ASSIGNEES = 25
MAX_TAG_IDS = 25

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
MAX_SLUG_LENGTH = 64


class _Strict(SanitizedBaseModel):
    model_config = ConfigDict(extra="forbid")


# -- Filters ------------------------------------------------------------------


class TaskPropertyFilter(_Strict):
    property_id: int
    op: FilterOp = FilterOp.eq
    value: Any = None


class TaskFilterSpec(_Strict):
    """The task filters a preset holds. Unknown keys are refused."""

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
            if entry not in (ASSIGNEE_ME, ASSIGNEE_NONE) and not entry.isdigit():
                raise ValueError("assignees entries must be a user id, 'me', or 'none'")
        return value

    @field_validator("status_categories")
    @classmethod
    def _dedupe_categories(
        cls, value: List[TaskStatusCategory]
    ) -> List[TaskStatusCategory]:
        return list(dict.fromkeys(value))


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


class EventDetailFieldId(str, Enum):
    """What an event's detail edits as a field. Its dates, its properties and
    your answer are parts of their own."""

    title = "title"
    description = "description"
    location = "location"
    recurrence = "recurrence"
    attendees = "attendees"
    tags = "tags"


PROPERTY_FIELD_PREFIX = "property:"
PLUGIN_FIELD_PREFIX = "plugin:"
#: The characters a row id is written in.
_DIGITS = frozenset("0123456789")
#: A row id is a Postgres ``integer``: at most ten digits.
_MAX_ID_DIGITS = 10


def _is_row_id(value: str) -> bool:
    return (
        0 < len(value) <= _MAX_ID_DIGITS
        and set(value) <= _DIGITS
        and not value.startswith("0")
    )


def _named_field(value: str) -> str:
    """``property:<definition id>`` or ``plugin:<install id>:<metadata key>``.
    By id rather than by name, so renaming a property keeps every layout that
    shows it."""
    if value.startswith(PROPERTY_FIELD_PREFIX):
        if _is_row_id(value.removeprefix(PROPERTY_FIELD_PREFIX)):
            return value
    elif value.startswith(PLUGIN_FIELD_PREFIX):
        install, _, key = value.removeprefix(PLUGIN_FIELD_PREFIX).partition(":")
        if _is_row_id(install) and is_metadata_key(key):
            return value
    raise ValueError(
        "a field is a built-in field id, 'property:<id>' or 'plugin:<id>:<key>'"
    )


def _plugin_field(value: str) -> str:
    """``plugin:<install id>:<metadata key>``."""
    if value.startswith(PLUGIN_FIELD_PREFIX):
        return _named_field(value)
    raise ValueError("a field here is a built-in field id or 'plugin:<id>:<key>'")


NamedFieldId = Annotated[str, AfterValidator(_named_field)]
PluginFieldId = Annotated[str, AfterValidator(_plugin_field)]
CardFieldId = Union[TaskFieldId, NamedFieldId]


# The built-in fields each place draws, named for the generated client.
_COLUMNS = {"title", "startDate", "dueDate", "priority", "tags", "comments"}
_PAGE = {
    "title",
    "description",
    "assignees",
    "checklist",
    "priority",
    "recurrence",
    "tags",
}

#: What a table draws as a column: the rest of a task (its people, its
#: checklist) sits in the title's cell.
TaskColumnFieldId = Enum(
    "TaskColumnFieldId",
    {f.name: f.value for f in TaskFieldId if f.value in _COLUMNS},
    type=str,
)
#: What a task's layout edits as a field. Its status, its dates and its
#: properties are parts of their own, and its counts are a card's.
TaskDetailFieldId = Enum(
    "TaskDetailFieldId",
    {f.name: f.value for f in TaskFieldId if f.value in _PAGE},
    type=str,
)
ColumnFieldId = Union[TaskColumnFieldId, NamedFieldId]
DetailFieldId = Union[TaskDetailFieldId, EventDetailFieldId, PluginFieldId]


def _part_id(value: str) -> str:
    """One of a plug-in's parts, by the id its manifest gives it."""
    if not 0 < len(value) <= MAX_IDENTIFIER_LENGTH or not set(value) <= set(
        IDENTIFIER_CHARS
    ):
        raise ValueError("a part is named by its manifest id")
    return value


# -- Parts --------------------------------------------------------------------


class StackProps(_Strict):
    direction: Optional[Literal["column", "row"]] = None
    gap: Optional[Literal["xs", "sm"]] = None
    wrap: Optional[bool] = None
    #: Items keep their own width rather than filling the column.
    align: Optional[Literal["start"]] = None
    tone: Optional[Literal["muted"]] = None


class FieldProps(_Strict):
    field: CardFieldId


class CardPart(_Strict):
    type: Literal["card"]
    children: List[CardChild] = Field(default_factory=list)


class StackPart(_Strict):
    type: Literal["stack"]
    props: Optional[StackProps] = None
    children: List[CardChild] = Field(default_factory=list)


class FieldPart(_Strict):
    type: Literal["field"]
    props: FieldProps


class PropertiesPart(_Strict):
    """Every property the item carries, in its own order."""

    type: Literal["properties"]


class PluginPartProps(_Strict):
    #: The install, as the community's plug-in routes name it.
    plugin: int = Field(gt=0)
    part: Annotated[str, AfterValidator(_part_id)]


class PluginPart(_Strict):
    """One of an installed plug-in's parts, drawn as its manifest builds it.
    A part the install no longer declares draws nothing."""

    type: Literal["plugin"]
    props: PluginPartProps


CardChild = Annotated[
    Union[CardPart, StackPart, FieldPart, PropertiesPart, PluginPart],
    Field(discriminator="type"),
]

CardPart.model_rebuild()
StackPart.model_rebuild()


class DetailFieldProps(_Strict):
    field: DetailFieldId


class DetailFieldPart(_Strict):
    type: Literal["field"]
    props: DetailFieldProps


class SectionProps(_Strict):
    #: The initiative's own words, drawn as written.
    title: Optional[str] = Field(default=None, max_length=100)
    #: Drawn folded until the reader opens it.
    collapsed: Optional[bool] = None


class SectionPart(_Strict):
    """A bordered group of a detail layout's parts."""

    type: Literal["section"]
    props: Optional[SectionProps] = None
    children: List[DetailPart] = Field(default_factory=list)


class DetailStackPart(_Strict):
    type: Literal["stack"]
    props: Optional[StackProps] = None
    children: List[DetailPart] = Field(default_factory=list)


#: The parts a detail draws as its own, which edit or show more than one
#: field: a task's status, who made it, its read-only notice, its case and its
#: comments; an event's answer; and either's dates, menu and relations. Which
#: of them a kind of detail draws is
#: ``app.services.tenant.tool_layouts.DETAIL_PARTS``.
OwnPartType = Literal[
    "status",
    "dates",
    "byline",
    "notice",
    "actions",
    "relations",
    "case",
    "comments",
    "rsvp",
]


class OwnPart(_Strict):
    """One of a detail's own parts."""

    type: OwnPartType


DetailPart = Annotated[
    Union[
        DetailStackPart,
        SectionPart,
        DetailFieldPart,
        PropertiesPart,
        PluginPart,
        OwnPart,
    ],
    Field(discriminator="type"),
]

SectionPart.model_rebuild()
DetailStackPart.model_rebuild()


# -- Definitions --------------------------------------------------------------

#: Every way a layout can list a tool's items; which of them a tool draws is
#: ``app.core.tools.LIST_LAYOUTS``.
ListLayoutKind = Literal["table", "board", "calendar"]
#: Every kind of thing a detail layout shows one of; which a tool holds is
#: ``app.core.tools.DETAIL_LAYOUTS``.
DetailLayoutKind = Literal["task", "calendar_event"]


#: What a table can be sorted by, as the task list takes it.
TaskSortField = Literal[
    "title",
    "due_date",
    "start_date",
    "date_group",
    "priority",
    "status_position",
    "tag_name",
]


class PresetSort(_Strict):
    field: TaskSortField
    dir: SortDir = SortDir.asc


class LayoutPreset(_Strict):
    """Filters, and for a table a sort, that a person can pick to start from.
    Picking one makes them that person's own."""

    #: Left out for a shipped preset no one renamed, which each reader sees
    #: named in their own language.
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    #: What a link to the preset carries; kept when it is renamed.
    slug: str = Field(min_length=1, max_length=MAX_SLUG_LENGTH, pattern=SLUG_PATTERN)
    filters: TaskFilterSpec = Field(default_factory=TaskFilterSpec)
    sort: List[PresetSort] = Field(
        default_factory=list, max_length=len(get_args(TaskSortField))
    )


class ListLayoutDefinition(_Strict):
    """How a list draws its items, and the presets it offers. What it leaves
    out is drawn as shipped: a board with no ``card`` draws the shipped card, a
    table with no ``columns`` the shipped columns, a list with no ``presets``
    the shipped presets."""

    card: Optional[CardPart] = None
    columns: Optional[List[ColumnFieldId]] = None
    presets: Optional[List[LayoutPreset]] = Field(default=None, max_length=MAX_PRESETS)

    @field_validator("presets")
    @classmethod
    def _one_preset_per_slug(
        cls, value: Optional[List[LayoutPreset]]
    ) -> Optional[List[LayoutPreset]]:
        slugs = [preset.slug for preset in value or ()]
        if len(set(slugs)) != len(slugs):
            raise ValueError("each preset needs its own slug")
        return value


class DetailLayoutDefinition(_Strict):
    """How one task (or event) is shown on its own, in three regions, each its
    parts in order. A region it leaves out is drawn as shipped, and a field
    placed in none of them is drawn in a "More fields" section."""

    header: Optional[List[DetailPart]] = None
    main: Optional[List[DetailPart]] = None
    side: Optional[List[DetailPart]] = None


# -- Requests -----------------------------------------------------------------


class ListLayoutWrite(_Strict):
    kind: ListLayoutKind
    definition: ListLayoutDefinition


class DetailLayoutWrite(_Strict):
    kind: DetailLayoutKind
    definition: DetailLayoutDefinition


#: One layout as it is changed.
ToolLayoutWrite = Annotated[
    Union[ListLayoutWrite, DetailLayoutWrite], Field(discriminator="kind")
]


class ToolLayoutDefaultWrite(_Strict):
    """The list a target opens on."""

    kind: ListLayoutKind


# -- Responses ----------------------------------------------------------------


class ListLayoutRead(SanitizedBaseModel):
    """One way a target lists its items: as shipped until it is changed."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: ListLayoutKind
    #: Whether the target opens on it.
    is_default: bool
    definition: ListLayoutDefinition
    #: When it was last changed; None as shipped.
    updated_at: Optional[datetime] = None


class DetailLayoutRead(SanitizedBaseModel):
    """How a target shows one of its items: as shipped until it is changed."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    kind: DetailLayoutKind
    definition: DetailLayoutDefinition
    #: When it was last changed; None as shipped.
    updated_at: Optional[datetime] = None


#: One of a target's layouts.
ToolLayoutRead = Annotated[
    Union[ListLayoutRead, DetailLayoutRead], Field(discriminator="kind")
]


class ToolLayoutSetRead(SanitizedBaseModel):
    """A target's layouts, one of each kind its tool draws: its lists, then its
    items, in the order the tool names them."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    layouts: List[ToolLayoutRead]
    #: Whether this reader may change them, computed server-side.
    can_configure: bool


class InitiativeToolLayoutsRead(ToolLayoutSetRead):
    """One instance's layouts, as its initiative's list of them shows them."""

    tool: Tool
    tool_id: int
    #: The instance's own name.
    name: str
