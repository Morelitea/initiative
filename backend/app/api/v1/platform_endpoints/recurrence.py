"""A repeat's next starts, from the engine the calendar uses.

A form sends the rule as picked, the series start and the zone its days are
in, and shows the dates that come back, so what it shows is what the calendar
will. Not guild-scoped, and it takes no session: the answer is arithmetic on
the request, and reads nothing from the database.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_active_user
from app.core import recurrence
from app.core.messages import CalendarEventMessages
from app.schemas.recurrence import RecurrencePreview, RecurrencePreviewRequest

router = APIRouter()


@router.post(
    "/preview",
    response_model=RecurrencePreview,
    dependencies=[Depends(get_current_active_user)],
)
def preview_recurrence(body: RecurrencePreviewRequest) -> RecurrencePreview:
    """The rule as it would be stored, its shift, and its next starts."""
    try:
        rule, shift = (
            recurrence.stored(body.rule, body.start, body.tz, kind=body.kind)
            if body.shift is None
            else (recurrence.normalize(body.rule, kind=body.kind), body.shift)
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=CalendarEventMessages.RECURRENCE_INVALID,
        )
    return RecurrencePreview(
        rule=rule,
        shift=shift,
        occurrences=recurrence.first(rule, body.start, shift, body.count),
    )
