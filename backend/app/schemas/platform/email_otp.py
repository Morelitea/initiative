"""Payloads for signing in with a one-time code sent to an address."""

from datetime import date
from typing import Optional

from pydantic import EmailStr, Field

from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.guild import NewCommunity


class EmailOtpSend(SanitizedBaseModel):
    """Ask for a code at an address."""

    email: EmailStr
    #: Checked before the address is looked at, so it answers for the request
    #: rather than for the address. ``None`` where the deployment configures no
    #: captcha provider, which is the default.
    captcha_token: Optional[str] = None
    #: An invite this address was given, where the deployment asks for one.
    #: Carried so that asking about an unknown address can tell whether a
    #: sign-up would be allowed before it posts a code inviting one.
    invite_code: Optional[str] = None


class EmailOtpSent(SanitizedBaseModel):
    """What asking always returns, whoever the address belongs to.

    ``challenge`` names the waiting code. It is the half of the proof that
    stays with the page that asked; the other half is in the mailbox.
    """

    status: str = "sent"
    challenge: str


class EmailOtpVerify(SanitizedBaseModel):
    """Answer a waiting code."""

    challenge: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=1, max_length=16)


class EmailOtpRegister(SanitizedBaseModel):
    """Make the account a proved address earned."""

    registration_ticket: str = Field(min_length=1, max_length=256)
    username: str = Field(min_length=1, max_length=64)
    timezone: Optional[str] = None
    invite_code: Optional[str] = None
    community: Optional[NewCommunity] = None
    # The signed number the name check showed beside the handle, kept if
    # still free.
    username_offer: Optional[str] = Field(default=None, max_length=1024)
    # Answers the directory's age question at sign-up; the date is not kept.
    birthdate: Optional[date] = None
