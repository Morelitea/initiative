"""Asking whoever runs this deployment for help.

Whether a community's members can is an **operator** entitlement
(``guild_administration.support_enabled``), not something the community's own
admins switch on: the deployment that would receive the requests is the one
that decides it is staffing them. Off is the default, and the "Ask for help"
control then offers the support address, or the FAQ where there is none.

Where a request lands is not this module's business either — it becomes a case
in the ``support`` stream, and the binding says which project that is.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.models.platform.guild_administration import GuildAdministration
from app.models.platform.user import User
from app.db import cohorts
from app.services.platform.intake import CaseFiler, CaseRefs, open_case

if TYPE_CHECKING:
    from app.services.platform.evidence import PreparedEvidence

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


async def entitled(requester: User, guild_id: int) -> bool:
    """Whether ``requester`` may ask for help from ``guild_id``.

    Asked on a session of their own, routed into the community through the
    ordinary entry point, so membership and every gate apply exactly as they
    do on a read: somebody who cannot reach the community cannot ask from it.
    """
    from app.api.deps import GuildAccessError, establish_guild_access

    async with cohorts.request_sessionmaker(guild_id)() as session:
        account = await session.merge(requester, load=False)
        try:
            await establish_guild_access(session, account, guild_id)
        except GuildAccessError:
            return False
        return await _entitled(session, guild_id)


async def request_help(
    *,
    guild_id: int,
    requester: User,
    subject: str,
    body: str,
    evidence: Sequence["PreparedEvidence"] = (),
    now: Optional[datetime] = None,
) -> int:
    """File one help request as a support case. Returns the case's task id.

    The case names who asked and which community they asked from, as the weak
    refs every case carries, and records them as its filer: their subject and
    their words open the case, said to them, so the conversation starts where
    they started it. The description is the platform's summary. What they
    attached is stored with it.
    """
    if not await entitled(requester, guild_id):
        raise SupportUnavailable

    moment = now or datetime.now(timezone.utc)
    outcome = await open_case(
        IntakeStream.support,
        title=subject,
        body=(
            f"Help request from account {requester.id}, sent from community {guild_id}."
        ),
        refs=CaseRefs(
            subject_user=requester.id,
            subject_guild=guild_id,
            reported_at=moment,
        ),
        now=moment,
        filer=CaseFiler(user_id=requester.id, subject=subject, words=body),
        evidence=evidence,
    )
    if outcome is None:
        # Nothing is bound to receive it. Said plainly rather than answering
        # "we have it" to a request that reached nobody.
        raise NowhereToSend
    return outcome.task_id
