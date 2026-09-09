"""The calendar-event dataset.

Read off ``CalendarEvent``: its columns, the calendar picker its foreign key
implies, and its tags. Events carry no grants of their own — access derives from
the parent calendar — so nothing here says anything about permission; the
policies on the table answer that.
"""

from __future__ import annotations

from app.models.tenant.calendar_event import CalendarEvent
from app.services.fields.derive import derive_fields
from app.services.fields.spec import Dataset

#: A recurrence rule is an instruction to the calendar, not a value anybody
#: narrows a list by.
_INTERNAL = frozenset({"recurrence"})


def build() -> Dataset:
    return Dataset(
        model=CalendarEvent,
        name_override="calendar_events",
        fields=derive_fields(CalendarEvent, internal=_INTERNAL),
    )
