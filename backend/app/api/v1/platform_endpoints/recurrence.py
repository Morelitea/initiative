"""Repeat rules between the days someone picked and the stored rule.

A repeat is stored in UTC terms (``app.core.recurrence``), and people pick days
in their own zone, so the form sends what was picked and saves what comes back.
It also lists the next starts, from the same engine the calendar uses.

Not guild-scoped, and it takes no session: the answer is arithmetic on the
request, and reads nothing from the database.
"""

from itertools import islice

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.core import recurrence
from app.core.messages import CalendarEventMessages
from app.core.user_input_validators import resolve_zone
from app.schemas.recurrence import RecurrencePreview, RecurrencePreviewRequest

router = APIRouter()


@router.post(
    "/preview",
    response_model=RecurrencePreview,
    dependencies=[Depends(get_current_active_user)],
)
def preview_recurrence(body: RecurrencePreviewRequest) -> RecurrencePreview:
    """Convert a repeat between the days picked in ``tz`` (``terms=local``) and
    the stored rule (``terms=utc``), and list its next starts. An all-day
    event's days are UTC dates, so its form sends ``tz=UTC``."""
    zone = resolve_zone(body.tz)
    try:
        if body.terms == "local":
            local = recurrence.normalize(body.rule, kind=body.kind)
            stored = recurrence.normalize(
                recurrence.to_utc_terms(local, body.start, zone), kind=body.kind
            )
        else:
            stored = recurrence.normalize(body.rule, kind=body.kind)
            local = recurrence.to_local_terms(stored, body.start, zone)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=CalendarEventMessages.RECURRENCE_INVALID,
        )
    series = recurrence.ruleset(recurrence.parse(stored), body.start)
    return RecurrencePreview(
        rule=stored,
        local_rule=local,
        occurrences=list(islice(series, body.count)),
        exact=recurrence.is_exact(local, stored, body.start, zone),
    )
