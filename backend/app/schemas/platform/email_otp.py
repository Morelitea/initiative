"""Payloads for signing in with a one-time code sent to an address."""

from typing import Optional

from pydantic import EmailStr, Field

from app.schemas.base import SanitizedBaseModel, TitleStr


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
    #: Whether the app asked rather than a browser. It decides what a finished
    #: sign-in hands back — a refresh token to keep, or a cookie — and is
    #: recorded on the challenge rather than asked for again at the end.
    native: bool = False


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


class EmailOtpTicket(SanitizedBaseModel):
    """A code answered at an address no account holds.

    Returned with ``202``: the code was right, and what is left is to say who
    this is. ``ticket`` is spent by the handle screen.
    """

    registration_ticket: str


class EmailOtpRegister(SanitizedBaseModel):
    """Make the account a proved address earned."""

    registration_ticket: str = Field(min_length=1, max_length=256)
    username: str = Field(min_length=1, max_length=64)
    full_name: Optional[TitleStr] = Field(default=None, max_length=255)
    timezone: Optional[str] = None
    invite_code: Optional[str] = None
