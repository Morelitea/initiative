"""Repeat rules on the wire: RFC 5545 lines in UTC terms (``app.core.recurrence``)."""

from datetime import datetime
from typing import Annotated, List, Literal, Optional

from pydantic import AfterValidator, Field

from app.core import recurrence
from app.schemas.base import SanitizedBaseModel


def _task_rule(value: str) -> str:
    return recurrence.normalize(value, kind="task")


def _event_rule(value: str) -> str:
    return recurrence.normalize(value, kind="event")


_DESCRIPTION = (
    "RFC 5545 recurrence lines: one RRULE, and optional EXDATE and RDATE "
    "lines, in UTC terms from the series start. POST /recurrence/preview "
    "converts days picked in a zone."
)

TaskRule = Annotated[
    str, Field(max_length=4000, description=_DESCRIPTION), AfterValidator(_task_rule)
]
EventRule = Annotated[
    str, Field(max_length=4000, description=_DESCRIPTION), AfterValidator(_event_rule)
]


class RecurrencePreviewRequest(SanitizedBaseModel):
    rule: str = Field(max_length=4000)
    #: The series start: an event's start, a task's due date.
    start: datetime
    #: The zone the rule's days are in. An all-day event's days are UTC dates.
    tz: Optional[str] = Field(default=None, max_length=64)
    kind: Literal["task", "event"]
    #: ``local`` converts picked days to the stored rule; ``utc`` reads a
    #: stored rule back in ``tz``.
    terms: Literal["local", "utc"] = "local"
    count: int = Field(default=5, ge=1, le=20)


class RecurrencePreview(SanitizedBaseModel):
    #: The stored form, in UTC terms.
    rule: str
    #: The same rule in the request's zone.
    local_rule: str
    #: The next starts, from the series start.
    occurrences: List[datetime]
    #: False when no rule in UTC terms says exactly what was picked, and the
    #: stored rule is the nearest one.
    exact: bool
