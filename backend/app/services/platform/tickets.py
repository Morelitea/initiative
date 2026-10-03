"""Filing a ticket: one way in, for every kind of operations work.

A ticket is an intake case — a task in the operations guild — filed by a
person. This module is what every filing surface goes through: it says, per
stream, whether a form can be offered at all, holds each account to the
stream's pace, and hands the filing to the stream that knows what it means.

Where a stream cannot take a filing — nothing is bound to receive it, or the
person is not entitled to file it from where they are — the answer is the
stream's contact address rather than a form, and where there is no address
either, nothing. A form that can only answer "nowhere to send this" is worse
than the address it replaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from limits import parse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream, meta
from app.core.rate_limit import take_allowance
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import User
from app.services.platform import intake as intake_service
from app.services.tenant import support as support_service

#: The counter namespace a filing's pace is kept under.
_PACE_NAMESPACE = "tickets"

#: The streams a person can file into here. The others are still reached by
#: their contact address; each joins this set in the phase that builds its
#: form.
FILEABLE: frozenset[IntakeStream] = frozenset(
    {IntakeStream.support, IntakeStream.moderation}
)


class TicketMode(str, Enum):
    """What a filing surface offers for a stream."""

    #: The form: there is somewhere to send it, and this person may.
    form = "form"
    #: The stream's contact address, and nothing to fill in.
    email = "email"
    #: Nothing at all: no form and nobody to write to.
    none = "none"


@dataclass(frozen=True)
class StreamAvailability:
    """What one stream offers this person, from where they are."""

    mode: TicketMode
    #: Who to write to about the stream, whatever the mode — a form whose
    #: filing turns out to have nowhere to go falls back to it.
    contact: Optional[str]


class FilingTooFast(Exception):
    """This account has filed into the stream as often as its pace allows."""


class TooManyOpen(Exception):
    """This account already has as many of the stream's cases open as it may."""


async def _contacts(session: AsyncSession) -> dict[IntakeStream, Optional[str]]:
    """Every stream's contact address, from one read of the settings row.

    The stream's own address, else the deployment's general one — the rule
    :func:`app.services.platform.intake.contact_for` applies, for all four.
    """
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        return {stream: None for stream in IntakeStream}
    own = row.intake_contacts or {}
    return {
        stream: own.get(stream.value) or row.intake_general_contact
        for stream in IntakeStream
    }


def _fallback(contact: Optional[str]) -> StreamAvailability:
    return StreamAvailability(
        mode=TicketMode.email if contact else TicketMode.none, contact=contact
    )


async def availability(
    session: AsyncSession, *, user: User, guild_id: Optional[int]
) -> dict[IntakeStream, StreamAvailability]:
    """What each stream offers ``user``, standing in ``guild_id`` if anywhere.

    ``session`` is the caller's own platform session; whether they may file
    from a community is asked on a session of theirs routed into it.
    """
    contacts = await _contacts(session)
    offered: dict[IntakeStream, StreamAvailability] = {}
    for stream in IntakeStream:
        contact = contacts[stream]
        if stream is IntakeStream.moderation:
            # A report about a community's own content goes to that
            # community's moderators and needs no platform at all, so the
            # form is always there; a report the platform would have to take
            # falls back to the address when nothing is bound.
            offered[stream] = StreamAvailability(TicketMode.form, contact)
        elif (
            stream is IntakeStream.support
            and guild_id is not None
            and await intake_service.stream_is_bound(stream)
            and await support_service.entitled(user, guild_id)
        ):
            offered[stream] = StreamAvailability(TicketMode.form, contact)
        else:
            offered[stream] = _fallback(contact)
    return offered


async def hold_pace(user: User, stream: IntakeStream) -> None:
    """Refuse a filing past the stream's pace or its open-case cap.

    The pace is counted per account, under the stream's declared rate; the cap
    is read from the cases themselves, so closing one makes room at once.
    """
    declared = meta(stream)
    if not await take_allowance(
        parse(declared.filing_rate), _PACE_NAMESPACE, f"{stream.value}:user:{user.id}"
    ):
        raise FilingTooFast
    if declared.max_open_per_filer is not None:
        held = await intake_service.open_cases_filed_by(user.id, stream)
        if held >= declared.max_open_per_filer:
            raise TooManyOpen
