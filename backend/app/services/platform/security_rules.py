"""Rules that watch this deployment and open a case when a line is crossed.

A **rule** watches one thing and decides when it has crossed a line worth a
person's attention. Each one lives beside the thing it watches, and is the
whole of what raises a security case.

Five properties hold for every rule here, and each decides something:

- **The threshold lives beside its rule, in code.** What counts as a line worth
  reporting is changed in a pull request somebody reviews. A deployment
  configures *whether* the security stream is bound; the rules decide what
  crosses.
- **A rule counts what is already recorded.** The evidence is ``audit_events``
  rows, counted on an index that is already there, so a rule needs no storage
  of its own and the population a case is drawn from is the durable one.
- **It fires at or above the threshold, not on equality.** Two refusals
  committing at once can carry the count past the line together, and both
  readers then see the higher number.
- **It cannot fail the thing it watches.** :func:`watch` runs a rule detached
  from the request that triggered it, and every failure path logs and swallows.
  The swallow is broad, so it logs the exception with it.
- **It names the account, never what was typed.** An address submitted to a
  sign-in form may belong to nobody, so a case carries ``user_id``.

Repeats are folded into one case by the writer (``app.services.platform.intake``):
a sustained run produces one case with a count on it, not one per event.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Coroutine, Optional

from sqlalchemy import func
from sqlmodel import select

from app.core.audit_events import AuditEventType
from app.core.intake import IntakeStream
from app.models.platform.audit_event import AuditEvent
from app.services.platform.intake import CaseOutcome, CaseRefs, open_case

logger = logging.getLogger(__name__)

#: Tasks in flight, held so the event loop cannot collect one mid-run.
_running: set[asyncio.Task] = set()


#: How long shutdown waits for rules in flight before going ahead without them.
DRAIN_TIMEOUT_SECONDS = 10.0


def watch(rule: Coroutine) -> None:
    """Run ``rule`` detached from the request that triggered it.

    A detective control is not worth an availability risk, so nothing a rule
    does can reach the caller: it runs on its own task, and the rule itself
    swallows and logs. The reference is held until it finishes, and
    :func:`drain` is what gives it a chance to.
    """
    task = asyncio.create_task(rule)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def drain(timeout: float = DRAIN_TIMEOUT_SECONDS) -> None:
    """Let rules already running finish, within a bound.

    A rule starts after the row it reads has committed, so one that stops
    partway leaves a crossing recorded and no case raised. Shutdown calls this
    first, while the engines are still up. The wait is bounded because a
    restart cannot be held open indefinitely, and anything still going when it
    expires is counted in the log rather than passed over quietly.
    """
    if not _running:
        return
    _, unfinished = await asyncio.wait(set(_running), timeout=timeout)
    if unfinished:
        logger.warning(
            "%d security rule(s) still running after %.0fs; shutting down anyway",
            len(unfinished),
            timeout,
        )


async def _count_since(
    event_type: AuditEventType, *, target_user_id: int, since: datetime
) -> int:
    """How many of these were recorded against this account since ``since``.

    Read on the system engine: ``audit_events`` grants the request path
    nothing, and a rule runs with nobody signed in.
    """
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        return (
            await session.exec(
                select(func.count(AuditEvent.id))
                .where(AuditEvent.event_type == event_type.value)
                .where(AuditEvent.target_user_id == target_user_id)
                .where(AuditEvent.occurred_at >= since)
            )
        ).one()


# --- The rules ---------------------------------------------------------------

#: How many refused sign-ins against one account, inside
#: :data:`SIGN_IN_REFUSAL_WINDOW`, are worth somebody looking.
SIGN_IN_REFUSAL_THRESHOLD = 10
SIGN_IN_REFUSAL_WINDOW = timedelta(minutes=15)


async def note_failed_sign_in(
    user_id: int, *, event_uuid: Optional[str] = None
) -> Optional[CaseOutcome]:
    """Open a case when one account is over the refusal threshold.

    Called after the refusal's own audit row has committed, so the count
    includes the attempt that triggered it. Returns the outcome for a test to
    assert on; nothing in the sign-in path reads it.
    """
    try:
        since = datetime.now(timezone.utc) - SIGN_IN_REFUSAL_WINDOW
        refusals = await _count_since(
            AuditEventType.AUTH_SIGN_IN_FAILED,
            target_user_id=user_id,
            since=since,
        )
        if refusals < SIGN_IN_REFUSAL_THRESHOLD:
            return None

        return await open_case(
            IntakeStream.security,
            title=f"Repeated refused sign-ins for account {user_id}",
            body=(
                f"{refusals} sign-in attempts against this account were refused "
                f"in the last {int(SIGN_IN_REFUSAL_WINDOW.total_seconds() // 60)} "
                "minutes.\n\n"
                "The account is named by id. Resolving it to a person is a "
                "platform screen, and reaching anything it holds is a "
                "break-glass grant that records why it was taken."
            ),
            refs=CaseRefs(subject_user=user_id, source_event=event_uuid),
            dedupe_key=f"sign_in_refusals:{user_id}",
        )
    except Exception:
        # Broad on purpose: a rule must not fail the path it watches, and the
        # exception is logged so a real error is still visible.
        logger.exception("security rule note_failed_sign_in did not complete")
        return None
