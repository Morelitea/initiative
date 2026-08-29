"""Writing down what was done.

One function. A call site is a single line, and adding a newly-audited action
is that line plus an ``AuditEventType`` member and its metadata row — there is
no second place to register anything.

Two deliveries, one write, and the write decides. The row goes into the
caller's own transaction, so the record and the action it describes commit
together or not at all — and the log line is held until that commit, so an
action that rolls back leaves no row and tells nobody it happened. The line
carries the same envelope to a structured logger named ``audit``, which is the
ingestible seam: an operator's container-log pipeline already scrapes stdout,
so shipping this stream costs them no new coupling to us.

Identity is never in the envelope — ids only, resolved when the board is read
and only for accounts that still exist.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import SCHEMA_VERSION, AuditEventType, meta_for
from app.models.platform.audit_event import AuditEvent

audit_logger = logging.getLogger("audit")

#: Envelopes staged in a session, waiting on its commit. Kept on
#: ``Session.info`` rather than in a module global so concurrent requests never
#: share a queue.
_PENDING = "audit_pending_envelopes"


@event.listens_for(Session, "after_commit")
def _emit_committed_envelopes(session: Session) -> None:
    """Ship the lines for work that actually landed."""
    for envelope in session.info.pop(_PENDING, []):
        # Best-effort: a logging handler that throws must not take down a
        # transaction that has already committed.
        try:
            audit_logger.info(json.dumps(envelope, separators=(",", ":")))
        except Exception:  # pragma: no cover - a broken handler, not our logic
            logging.getLogger(__name__).exception("audit log line could not be emitted")


@event.listens_for(Session, "after_rollback")
def _discard_uncommitted_envelopes(session: Session) -> None:
    """Drop the lines for work that did not land."""
    session.info.pop(_PENDING, None)


async def record(
    session: AsyncSession,
    *,
    event_type: AuditEventType,
    actor_user_id: int,
    target_user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    detail: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    """Record one action in ``session``'s transaction and emit its log line.

    Staged, not committed: the caller owns the transaction, which is what makes
    the record atomic with the thing it records.
    """
    meta = meta_for(event_type)
    occurred_at = datetime.now(timezone.utc)

    event = AuditEvent(
        event_type=event_type.value,
        occurred_at=occurred_at,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        guild_id=guild_id,
        target_type=target_type,
        target_id=target_id,
        tier=meta.tier,
    )
    event.envelope = {
        "schema_version": SCHEMA_VERSION,
        "event_uuid": str(event.event_uuid),
        "event_type": event_type.value,
        "occurred_at": occurred_at.isoformat(),
        "actor_user_id": actor_user_id,
        "target_user_id": target_user_id,
        "guild_id": guild_id,
        "target": (
            {"type": target_type, "id": target_id} if target_type is not None else None
        ),
        "tier": meta.tier,
        "category": meta.category.value,
        "is_write": meta.is_write,
        "detail": detail or {},
    }
    session.add(event)

    # Queued, not emitted. The line goes out when the transaction commits, so
    # the two sinks cannot disagree: an action that rolls back leaves no row
    # and tells nobody it happened.
    session.info.setdefault(_PENDING, []).append(event.envelope)

    return event
