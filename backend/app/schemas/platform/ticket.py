"""Payloads for filing a ticket, and for what a filing surface offers."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, List, Literal, Optional, Union

from pydantic import AfterValidator, ConfigDict, Field as PydanticField

from app.core.intake import Conversation, IntakeStream
from app.core.moderation import ReportVenue
from app.schemas.base import RichTextStr, SanitizedBaseModel
from app.schemas.tenant.evidence import EvidencePolicyRead, EvidenceRead
from app.schemas.tenant.moderation import ReportCreate
from app.services.platform.tickets import FilerState, TicketMode
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
    community_id: int
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
    #: What may be attached to a filing or an answer in this stream.
    evidence: EvidencePolicyRead


class TicketAvailability(SanitizedBaseModel):
    """What every stream offers the reader. One entry per stream."""

    security: StreamAvailabilityRead
    moderation: StreamAvailabilityRead
    support: StreamAvailabilityRead
    feedback: StreamAvailabilityRead


class FiledTicketRead(SanitizedBaseModel):
    """One case its filer can follow: what they called it, and where it stands."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    task_id: int
    stream: IntakeStream
    #: What they called it, in their own words.
    subject: Optional[str] = None
    state: FilerState
    opened_at: datetime
    updated_at: Optional[datetime] = None


class FiledTicketList(SanitizedBaseModel):
    """The cases the reader filed, most recently moved first."""

    items: List[FiledTicketRead]


class TicketMessageRead(SanitizedBaseModel):
    """One part of the conversation about a case, as its filer reads it.

    The people handling the case are not named here: ``mine`` says whether the
    reader wrote it, and everything else is the team's.
    """

    id: int
    mine: bool
    #: Kept as written, like any comment body.
    content: RichTextStr
    created_at: datetime
    #: The files that came with it. Only the reader's own: what they sent.
    attachments: List[EvidenceRead] = PydanticField(default_factory=list)


class FiledTicketDetailRead(FiledTicketRead):
    """One case its filer filed, with what has been said to them about it."""

    conversation: Conversation
    #: Whether the reader may answer now: the kind of case allows it, it is
    #: not closed, and where the people handling it speak first, they have.
    can_reply: bool
    #: What an answer may carry with it, for this kind of case.
    evidence: EvidencePolicyRead
    messages: List[TicketMessageRead]


class TicketReplyCreate(SanitizedBaseModel):
    """A filer's answer on their own case."""

    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )
