"""Payloads for filing a ticket, and for what a filing surface offers."""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import AfterValidator, ConfigDict, Field as PydanticField

from app.core.moderation import ReportVenue
from app.schemas.base import SanitizedBaseModel
from app.schemas.tenant.moderation import ReportCreate
from app.services.platform.tickets import TicketMode
from app.services.tenant.support import BODY_LENGTH, SUBJECT_LENGTH


def _said_something(value: str) -> str:
    """Trim, and refuse what is left if it is nothing.

    The length bounds count characters, and a space is one — so the minimum
    alone admits a case whose title is blank on the board somebody has to work
    from. Trimming here also means the stored value is the one that was meant,
    whatever the client did or did not tidy up.
    """
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("must not be blank")
    return trimmed


class SupportTicketCreate(SanitizedBaseModel):
    """Asking for help, from inside a community."""

    stream: Literal["support"]
    #: The community they are asking from. Whether its members may ask is the
    #: operator's entitlement, checked against their own access to it.
    guild_id: int
    #: One line saying what this is about. Becomes the case's title.
    subject: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=SUBJECT_LENGTH
    )
    #: The rest of it, in their own words.
    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )


class ModerationTicketCreate(ReportCreate):
    """Reporting something. The same shape from every surface."""

    stream: Literal["moderation"]


#: One filing, told apart by its stream.
TicketCreate = Annotated[
    Union[SupportTicketCreate, ModerationTicketCreate],
    PydanticField(discriminator="stream"),
]


class TicketAccepted(SanitizedBaseModel):
    """What the filer is told: that it arrived.

    Not who will read it, and for a report not whether one already existed —
    a report is not a conversation with the person who sent it, so ``venue``
    is all it says, and only for a report.
    """

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    accepted: bool = True
    venue: Optional[ReportVenue] = None


class StreamAvailabilityRead(SanitizedBaseModel):
    """What one stream offers the reader, from where they are."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    mode: TicketMode
    #: Who to write to about it, whatever the mode.
    contact: Optional[str] = None


class TicketAvailability(SanitizedBaseModel):
    """What every stream offers the reader. One entry per stream."""

    security: StreamAvailabilityRead
    moderation: StreamAvailabilityRead
    support: StreamAvailabilityRead
    feedback: StreamAvailabilityRead
