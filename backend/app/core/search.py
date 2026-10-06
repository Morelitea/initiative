"""The canonical ``SearchEntityType`` enum — every kind of thing search can find.

Built from :data:`~app.core.tools.KINDS` rather than restating it: every
tool, everything that lives inside one, and the guild's tags are indexed under
their own kind's name, so adding a kind adds a searchable type without an edit
here. The one type that is not a kind is the comment — a remark on something
rather than a thing addressed by itself.

It is an enum rather than a bare string so the API declares the set it accepts:
the generated client gets the same list, and a client cannot ask for a type that
was renamed out from under it. ``search_index_test.py`` asserts the enum and
``SEARCH_SOURCES`` name exactly the same set, so neither can grow a member alone.
"""

from enum import Enum

from app.core.tools import KINDS

_MEMBERS = {v: v for v in sorted([*KINDS, "comment"])}

SearchEntityType = Enum("SearchEntityType", _MEMBERS, type=str, module=__name__)
