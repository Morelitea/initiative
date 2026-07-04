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
    calendar_event = "calendar_event"
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
