"""The canonical ``Tool`` enum — the app-wide set of shareable tool kinds.

A tool is a first-class thing an initiative offers. Every tool is the same shape:
a soft-deletable content table under initiative-member RLS, shared via
``resource_grants`` (its string value IS the ``resource_type``). The single source
of truth for that set — the DAC registries and every tool endpoint reference it
rather than repeating string literals. Kept dependency-free (just an enum) so it
can be imported anywhere. ``tools_test.py`` asserts every per-tool surface covers
this enum, so a new member that forgets to wire one fails CI.
"""

from enum import Enum


class Tool(str, Enum):
    project = "project"
    document = "document"
    queue = "queue"
    counter_group = "counter_group"
    calendar = "calendar"
    dashboard = "dashboard"
    advanced_tool = "advanced_tool"

    @property
    def plural(self) -> str:
        """Pluralized stem — the table-ish spelling every derived name uses
        (``counter_group`` → ``counter_groups``)."""
        return f"{self.value}s"

    @property
    def view_permission(self) -> str:
        """The role ``PermissionKey`` value gating viewing this tool. For
        toggleable tools it is also the initiative master-switch column."""
        return f"{self.plural}_enabled"

    @property
    def create_permission(self) -> str:
        """The role ``PermissionKey`` value gating creating this tool."""
        return f"create_{self.plural}"

    @property
    def member_view_field(self) -> str:
        """``InitiativeMemberRead`` computed view flag for this tool."""
        return f"can_view_{self.plural}"

    @property
    def member_create_field(self) -> str:
        """``InitiativeMemberRead`` computed create flag for this tool."""
        return f"can_create_{self.plural}"


# Core tools are always on: no ``*_enabled`` master switch on the initiative and
# view defaults to True. Every other tool is opt-in per initiative via its
# ``{plural}_enabled`` column.
CORE_TOOLS = frozenset({Tool.project, Tool.document})
TOGGLEABLE_TOOLS = tuple(t for t in Tool if t not in CORE_TOOLS)

# Tools that appear in the recent-items bar. The advanced tool is deliberately
# absent: it has no per-entity detail route to return to.
RECENTABLE_TOOLS = tuple(t for t in Tool if t is not Tool.advanced_tool)

# Tools WITHOUT an export-engine source, and why. Stated as an exclusion so the
# default is "a new tool is exportable": the adapter-coverage test then fails
# until the tool either has an adapter or is listed here deliberately. An
# inclusion list would instead let a new tool silently ship with no export.
NON_EXPORTABLE_TOOLS = frozenset(
    {
        # Content lives in the external service, not in our tables.
        Tool.advanced_tool,
        # Export/import ships with the marketplace, which owns the definition
        # envelope format.
        Tool.dashboard,
    }
)

# Tools with an export-engine source (single-entity + bulk selection export).
# The engine's source name / endpoint segment is the KEBAB SINGULAR of the
# tool ("counter_group" -> "counter-group"); the bulk selector param is
# ``{tool}_ids``. The frontend mirrors this as TOOL_REGISTRY's ``bulkExport``
# flag.
BULK_EXPORT_TOOLS = tuple(t for t in Tool if t not in NON_EXPORTABLE_TOOLS)


# Tag-assignment surfaces: EVERY tool is taggable, plus these content-level
# extras — sub-resources of a tool (tasks, queue items) rather than tools
# themselves. The assignment registry (app.services.tenant.tags.TAG_LINKS) and
# the ``TagTarget`` schema enum both derive from TAG_TARGETS, so a new Tool is
# taggable across every surface with no per-surface edit; tags_test.py fails if
# any surface drifts.
TAGGABLE_EXTRAS: tuple[str, ...] = ("task", "queue_item", "calendar_event")
TAG_TARGETS: tuple[str, ...] = tuple(t.value for t in Tool) + TAGGABLE_EXTRAS


# Trash surfaces: EVERY tool is trashable, plus these extras — sub-resources of
# a tool (tasks, counters), the initiative itself, and the guild-level content
# that isn't a tool (tags). Same shape as TAG_TARGETS above, for the same
# reason: the trash EntityType and its registry derive from this, so a new Tool
# reaches the trash can with no per-surface edit.
TRASHABLE_EXTRAS: tuple[str, ...] = (
    "task",
    "queue_item",
    "calendar_event",
    "counter",
    "comment",
    "initiative",
    "tag",
)
TRASH_TARGETS: tuple[str, ...] = tuple(t.value for t in Tool) + TRASHABLE_EXTRAS


def tool_export_source(tool: Tool) -> str:
    """The export adapter registry key / endpoint segment for a tool."""
    return tool.value.replace("_", "-")


def tool_for_create_permission(permission_value: str) -> Tool:
    """The Tool whose ``create_permission`` is ``permission_value`` — the
    inverse lookup the import engine uses to reach a tool's master switch
    without re-deriving column names by string surgery. Raises KeyError for
    a permission that gates no tool (callers validate at registry-build
    time, so a miss is a programming error, never a request error)."""
    return _TOOL_BY_CREATE_PERMISSION[permission_value]


_TOOL_BY_CREATE_PERMISSION: dict[str, Tool] = {t.create_permission: t for t in Tool}
