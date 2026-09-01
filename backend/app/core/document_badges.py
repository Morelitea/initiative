"""Badges — the facts a chip can show about a thing it references.

A reference (:mod:`app.core.references`) names something and resolves to what
it is called. A badge goes one step further and shows a fact ABOUT it that
changes on its own: the column a task sits in, a counter's reading, when an
event is.

Only the facts live here. Which kinds can be referred to at all is a reference
question, not a badge one.
"""

from enum import Enum

from app.core.references import REF_SEPARATOR
from app.core.search import SearchEntityType


class BadgeAspect(str, Enum):
    """The fact a badge is about."""

    #: A task's column — the one that answers "where is this".
    status = "status"
    #: Who is holding it.
    assignee = "assignee"
    #: When it is due, and whether that has passed.
    due = "due"
    #: How urgent it was said to be.
    priority = "priority"
    #: A counter's current reading.
    value = "value"
    #: When something happens, and whether it has.
    when = "when"


class BadgeTone(str, Enum):
    """How a chip is coloured when nothing more specific applies.

    The server decides this rather than the client, because what counts as
    finished, late or urgent is a product rule and not a rendering detail. A
    chip with its own colour — a task status carries one — sends that instead.
    """

    neutral = "neutral"
    #: Nothing there yet: unassigned, no date.
    muted = "muted"
    #: Finished, or otherwise where you want it to be.
    good = "good"
    #: Worth noticing.
    warn = "warn"
    #: Late, or urgent.
    danger = "danger"


#: Every badge there is: a thing, and the changing fact about it.
#:
#: One entry is one reader in ``app.services.tenant.document_badges``;
#: ``document_badges_test`` fails until a pair added here has one.
BADGE_KINDS: tuple[tuple[SearchEntityType, BadgeAspect], ...] = (
    (SearchEntityType.calendar_event, BadgeAspect.when),
    (SearchEntityType.counter, BadgeAspect.value),
    (SearchEntityType.task, BadgeAspect.assignee),
    (SearchEntityType.task, BadgeAspect.due),
    (SearchEntityType.task, BadgeAspect.priority),
    (SearchEntityType.task, BadgeAspect.status),
)


def kind_value(entity_type: SearchEntityType, aspect: BadgeAspect) -> str:
    """The pair as the API spells it: ``task:status``."""
    return f"{entity_type.value}{REF_SEPARATOR}{aspect.value}"


#: The pairs as a closed set the generated client reads, so an editor's insert
#: menu is built from what this server actually answers.
BadgeKind = Enum(
    "BadgeKind",
    {
        f"{kind.value}_{aspect.value}": kind_value(kind, aspect)
        for kind, aspect in BADGE_KINDS
    },
    type=str,
    module=__name__,
)
