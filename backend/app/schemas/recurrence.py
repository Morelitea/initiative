"""Repeat rules on the wire: RFC 5545 lines as picked (``app.core.recurrence``)."""

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
    "lines in UTC. The rule's days are as picked in the request's tz, or UTC "
    "days without one. POST /recurrence/preview lists its next starts."
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
    #: The zone the rule's days were picked in; UTC without one, and for an
    #: all-day event, whose days are UTC dates.
    tz: Optional[str] = Field(default=None, max_length=64)
    kind: Literal["task", "event"]
    count: int = Field(default=5, ge=1, le=20)


class RecurrencePreview(SanitizedBaseModel):
    #: The rule as it is stored.
    rule: str
    #: The shift stored beside it (``app.core.recurrence``).
    shift: int
    #: The next starts, from the series start.
    occurrences: List[datetime]
