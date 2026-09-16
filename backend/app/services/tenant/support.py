"""Asking whoever runs this deployment for help.

A community's members can send a help request only where that community has
switched support on. Off is the default and the answer on every install that
has nobody to staff a queue, and the surface then shows the FAQ instead —
which is why this is a question the guild row answers rather than something
the client decides.

Where the request lands is not this module's business either: it becomes a
case in the ``support`` stream, and the binding says which project that is.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.intake import IntakeStream
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.services.platform.intake import CaseRefs, open_case

#: Longest a request's summary and its body may be. The case is a task, whose
#: title is a line; the body is a description somebody reads, not a log.
SUBJECT_LENGTH = 200
BODY_LENGTH = 5000


class SupportUnavailable(Exception):
    """This community does not take help requests."""


class NowhereToSend(Exception):
    """Support is on here, but the deployment has bound no support project."""


async def request_help(
    *,
    guild: Guild,
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
    if not guild.support_enabled:
        raise SupportUnavailable

    moment = now or datetime.now(timezone.utc)
    outcome = await open_case(
        IntakeStream.support,
        title=subject,
        body=body,
        refs=CaseRefs(
            subject_user=requester.id,
            subject_guild=guild.id,
            reported_at=moment,
        ),
    )
    if outcome is None:
        # Nothing is bound to receive it. Said plainly rather than answering
        # "we have it" to a request that reached nobody.
        raise NowhereToSend
    return outcome.task_id
