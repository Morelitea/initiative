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


# The tool string values as a set — the accepted ``resource_grants.resource_type``
# values, derived from the enum (single source of truth).
TOOL_TYPES = frozenset(t.value for t in Tool)
