"""Payloads for asking whoever runs this deployment for help."""

from __future__ import annotations

from pydantic import Field as PydanticField

from app.schemas.base import SanitizedBaseModel
from app.services.tenant.support import BODY_LENGTH, SUBJECT_LENGTH


class SupportRequestCreate(SanitizedBaseModel):
    """What somebody asking for help sends."""

    #: One line saying what this is about. Becomes the case's title.
    subject: str = PydanticField(min_length=1, max_length=SUBJECT_LENGTH)
    #: The rest of it, in their own words.
    body: str = PydanticField(min_length=1, max_length=BODY_LENGTH)


class SupportRequestAccepted(SanitizedBaseModel):
    """What they are told back: that it arrived.

    Not where it landed or who will read it — the project a deployment routes
    support into is its own arrangement, and naming it here would make it the
    asker's business.
    """

    accepted: bool = True
