"""The vocabulary of document badges — what a chip in a document can be about.

A badge names one CHANGING fact about one thing: a task's status, a counter's
number, when an event is. What it never names is something the document could
have written down instead — a title does not change, so it is a mention rather
than a badge.

Kept dependency-free, like :mod:`app.core.tools`, so the enums can be imported
from a model, a service or a schema without a cycle. Which pairs of
``(SearchEntityType, BadgeAspect)`` actually exist is the registry's business,
in ``app.services.tenant.badges``.
"""

from enum import Enum

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
    #: What a thing is called right now — what a link to it renders as, so a
    #: rename reaches every place that points at it.
    title = "title"


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


#: How the three parts of a reference are joined: ``task:12:status``.
REF_SEPARATOR = ":"

#: The facts a badge can be about, beyond the title every referenceable thing
#: has. One entry is one reader in ``app.services.tenant.document_badges``.
#:
#: ``title`` is not listed: every kind that can be referred to has one, and the
#: set of those kinds is derived rather than restated.
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


#: The pairs an editor can insert, as a closed set the generated client reads.
#:
#: Only the aspect badges: a title is how a reference RENDERS, not something
#: chosen from a menu, and which kinds have one is derived from the reference
#: surface rather than restated here.
BadgeKind = Enum(
    "BadgeKind",
    {
        f"{kind.value}_{aspect.value}": kind_value(kind, aspect)
        for kind, aspect in BADGE_KINDS
    },
    type=str,
    module=__name__,
)
