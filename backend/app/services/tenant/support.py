"""Asking whoever runs this deployment for help.

Whether a community's members can is an **operator** entitlement
(``guild_administration.support_enabled``), not something the community's own
admins switch on: the deployment that would receive the requests is the one
that decides it is staffing them. Off is the default, and the "Ask for help"
control then opens the FAQ.

Where a request lands is not this module's business either — it becomes a case
in the ``support`` stream, and the binding says which project that is.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.user import User
from app.services.platform.intake import CaseRefs, open_case, stream_is_bound

#: Longest a request's summary and its body may be. The case is a task, whose
#: title is a line; the body is a description somebody reads, not a log.
SUBJECT_LENGTH = 200
BODY_LENGTH = 5000


class SupportUnavailable(Exception):
    """This deployment does not take help requests from this community."""


class NowhereToSend(Exception):
    """The entitlement is on, but no project is bound to receive support."""


async def _entitled(session: AsyncSession, guild_id: int) -> bool:
    """Whether this community's members may ask. One indexed row.

    Read on the caller's own guild-routed session: the table admits a member to
    their own guild's row, so this is the same answer the settings page gets.
    """
    row = (
        await session.exec(
            select(GuildAdministration.support_enabled).where(
                GuildAdministration.guild_id == guild_id
            )
        )
    ).first()
    return bool(row)


async def can_ask_for_help(session: AsyncSession, *, guild_id: int) -> bool:
    """Whether to offer the form rather than the FAQ.

    Both halves, because either one missing makes the form a dead end: the
    operator has to have switched it on, and something has to be bound to
    receive what is sent.
    """
    if not await _entitled(session, guild_id):
        return False
    return await stream_is_bound(IntakeStream.support)


async def request_help(
    session: AsyncSession,
    *,
    guild_id: int,
    requester: User,
    subject: str,
    body: str,
    now: Optional[datetime] = None,
) -> int:
    """File one help request as a support case. Returns the case's task id.

    The case names who asked and which community they asked from, as the weak
    refs every case carries — so whoever picks it up can reach them without
    this endpoint having to resolve anybody.
    """
    if not await _entitled(session, guild_id):
        raise SupportUnavailable

    moment = now or datetime.now(timezone.utc)
    outcome = await open_case(
        IntakeStream.support,
        title=subject,
        body=body,
        refs=CaseRefs(
            subject_user=requester.id,
            subject_guild=guild_id,
            reported_at=moment,
        ),
    )
    if outcome is None:
        # Nothing is bound to receive it. Said plainly rather than answering
        # "we have it" to a request that reached nobody.
        raise NowhereToSend
    return outcome.task_id
