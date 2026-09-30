"""Aggregate calendar-entries response schema.

A union payload for the calendar surfaces: events and task markers over one date
window, fetched in a single request instead of two. The client keeps the merge
(``buildTaskCalendarEntries`` + event mapping), so this deliberately reuses the
existing ``CalendarEventSummary`` and ``TaskListRead`` shapes rather than a new
normalized entry type — no data is lost (bulk event-selection still gets full
event objects, tasks keep project/guild ids for colors + navigation).
"""

from typing import List

from pydantic import ConfigDict

from app.schemas.base import SanitizedBaseModel
from app.schemas.tenant.calendar_event import CalendarEventSummary
from app.schemas.tenant.task import TaskListRead


class CalendarEntriesResponse(SanitizedBaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    #: A repeating event once for each of its occurrences in the window.
    events: List[CalendarEventSummary] = []
    tasks: List[TaskListRead] = []
    #: The upcoming occurrences of repeating tasks in the window: each the
    #: series' current task with its dates moved there. They are not tasks yet;
    #: completing the current one creates the next.
    task_occurrences: List[TaskListRead] = []
