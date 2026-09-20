"""A one-time code sent to an address, and the handle that goes with it.

Two things are handed out and both are needed to sign in: a **handle**, in the
response to the page that asked, and a **code**, to the mailbox. The challenge
row holds the handle in ``challenge_hash`` — so finding it and spending one of
its attempts stay the single statement they already were — and the code in
``answer_hash``, digested together with the handle.

The lookup is by handle, so a code that does not match still spends one of
the challenge's attempts; the sixth ends it.

Everything here runs on the system engine, like the rest of the challenge
machinery: a code is resolved before there is an authenticated request to
scope.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.platform.auth_challenge import AuthChallenge
from app.services.auth import challenges as challenge_service

#: Digits in the code. Short enough to carry across the room in your head,
#: and paired with the attempt cap rather than relied on alone.
CODE_DIGITS = 6

#: How long a code stands. Longer than the shared challenge window, which is
#: sized for reading an authenticator already in your hand: this one waits on
#: mail delivery and on somebody going to look for it.
CODE_TTL = timedelta(minutes=10)

#: How long the handle screen has to be filled in, once the code is answered.
#: Shorter than the code's own life: the person is already at the keyboard.
TICKET_TTL = timedelta(minutes=15)

#: The purposes a code may be presented against, so one route serves both.
PURPOSES = (
    challenge_service.ChallengePurpose.email_otp,
    challenge_service.ChallengePurpose.email_otp_native,
)

#: And the purposes a registration ticket may be spent against.
TICKET_PURPOSES = (
    challenge_service.ChallengePurpose.email_otp_register,
    challenge_service.ChallengePurpose.email_otp_register_native,
)


@dataclass(frozen=True)
class IssuedCode:
    """A code and the handle that names the challenge holding it.

    ``handle`` goes back to the caller that asked, ``code`` goes to the
    mailbox, and this is the only moment either exists in the clear.
    """

    handle: str
    code: str


def mint_code() -> str:
    """A fresh code, drawn uniformly and rendered with its leading zeros."""
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


async def issue(
    session: AsyncSession,
    *,
    user_id: int | None,
    user_email_id: int | None,
    native: bool,
    email: str | None = None,
) -> IssuedCode:
    """Open a challenge waiting for a code, and hand back both halves.

    ``user_email_id`` names the address the code is going to, so what
    arriving there proves is about that address rather than the account.

    ``email`` is set instead where the address reached no account and a
    sign-up may follow: there is no address row to point at yet, and the code
    is what will prove it.

    ``user_id`` is ``None`` where the address reached no account. The row is
    written anyway: the response to a request about an address is the same
    either way, and a handle that names nothing is what makes that true
    without the route having to remember which case it was in.

    The caller commits, and the caller decides whether a letter goes out.
    """
    code = mint_code()
    issued = await challenge_service.create(
        session,
        user_id=user_id,
        purpose=(
            challenge_service.ChallengePurpose.email_otp_native
            if native
            else challenge_service.ChallengePurpose.email_otp
        ),
        answer=code,
        ttl=CODE_TTL,
        user_email_id=user_email_id,
        email=email,
    )
    return IssuedCode(handle=issued.value, code=code)


async def claim(
    session: AsyncSession, *, handle: str, code: str
) -> AuthChallenge | None:
    """The challenge this pair answers, or ``None``.

    Spends one of the challenge's attempts whether or not the code is right,
    which is the point of looking it up by the handle. ``None`` covers every
    way this can fail to be a sign-in — no such handle, expired, spent, out of
    attempts, or the wrong code — and they read the same from here.

    The attempt is taken in this session and the caller commits it, including
    on the way to refusing.
    """
    challenge = await challenge_service.claim_attempt(
        session, value=handle, purposes=PURPOSES
    )
    if challenge is None:
        return None
    if not challenge_service.answered_by(challenge, value=handle, answer=code):
        return None
    return challenge


async def issue_ticket(session: AsyncSession, *, email: str, native: bool) -> str:
    """Open the ticket the handle screen spends, and hand back its value.

    Its own challenge rather than a longer life on the code's: the code is
    spent by the moment it is answered, and what follows is a different thing
    being waited for. It carries the address the code proved.
    """
    issued = await challenge_service.create(
        session,
        user_id=None,
        purpose=(
            challenge_service.ChallengePurpose.email_otp_register_native
            if native
            else challenge_service.ChallengePurpose.email_otp_register
        ),
        ttl=TICKET_TTL,
        email=email,
    )
    return issued.value


async def claim_ticket(session: AsyncSession, *, ticket: str) -> AuthChallenge | None:
    """The registration ticket this value names, or ``None``."""
    return await challenge_service.claim_attempt(
        session, value=ticket, purposes=TICKET_PURPOSES
    )


def is_native(challenge: AuthChallenge) -> bool:
    """Whether this challenge was opened by the app rather than a browser."""
    return (
        challenge.purpose == challenge_service.ChallengePurpose.email_otp_native.value
    )
