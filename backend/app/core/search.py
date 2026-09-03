"""The canonical ``SearchEntityType`` enum — every kind of thing search can find.

Built from :class:`~app.core.tools.Tool` rather than restating it: a tool's own
rows are indexed under the tool's own name, so adding a tool adds a searchable
type without an edit here. What IS stated is the set that has no tool of its own
— the entities that live inside one, and the guild's vocabulary.

It is an enum rather than a bare string so the API declares the set it accepts:
the generated client gets the same list, and a client cannot ask for a type that
was renamed out from under it. ``search_index_test.py`` asserts the enum and
``SEARCH_SOURCES`` name exactly the same set, so neither can grow a member alone.
"""

from enum import Enum

from app.core.tools import Tool

#: Indexed things that are not a tool: the four that live inside one, what people
#: say on any of them, and the guild-level vocabulary.
NON_TOOL_ENTITY_TYPES: tuple[str, ...] = (
    "task",
    "queue_item",
    "counter",
    "calendar_event",
    "comment",
    "tag",
)

_MEMBERS = {v: v for v in sorted([t.value for t in Tool] + list(NON_TOOL_ENTITY_TYPES))}

SearchEntityType = Enum("SearchEntityType", _MEMBERS, type=str, module=__name__)
