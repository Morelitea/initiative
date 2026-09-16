"""Payloads for asking whoever runs this deployment for help."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field as PydanticField

from app.schemas.base import SanitizedBaseModel
from app.services.tenant.support import BODY_LENGTH, SUBJECT_LENGTH


def _said_something(value: str) -> str:
    """Trim, and refuse what is left if it is nothing.

    The length bounds count characters, and a space is one — so the minimum
    alone admits a case whose title and description are blank on the board
    somebody has to work from. Trimming here also means the stored value is the
    one that was meant, whatever the client did or did not tidy up.
    """
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("must not be blank")
    return trimmed


class SupportAvailability(SanitizedBaseModel):
    """Whether the help form should be offered in this community.

    One boolean rather than its two halves: the reader is choosing between a
    form and the FAQ, and which of the two reasons applies is the operator's
    business, not theirs.
    """

    available: bool = False


class SupportRequestCreate(SanitizedBaseModel):
    """What somebody asking for help sends."""

    #: One line saying what this is about. Becomes the case's title.
    subject: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=SUBJECT_LENGTH
    )
    #: The rest of it, in their own words.
    body: Annotated[str, AfterValidator(_said_something)] = PydanticField(
        min_length=1, max_length=BODY_LENGTH
    )


class SupportRequestAccepted(SanitizedBaseModel):
    """What they are told back: that it arrived.

    Not where it landed or who will read it — the project a deployment routes
    support into is its own arrangement, and naming it here would make it the
    asker's business.
    """

    accepted: bool = True
