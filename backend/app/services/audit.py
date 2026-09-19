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
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import SCHEMA_VERSION, AuditEventType, meta_for
from app.models.platform.audit_event import AuditEvent

audit_logger = logging.getLogger("audit")

#: Rows staged in a session with their envelopes, waiting on its commit. Kept
#: on ``Session.info`` rather than in a module global so concurrent requests
#: never share a queue.
_PENDING = "audit_pending_envelopes"


@event.listens_for(Session, "after_commit")
def _emit_committed_envelopes(session: Session) -> None:
    """Ship the lines for work that actually landed.

    Each entry is checked against its own row. A record staged inside a
    savepoint that was rolled back loses its identity with it, while one the
    session merely let go of after flushing keeps it; the line is judged by
    that, not by the transaction as a whole.
    """
    for row, envelope in session.info.pop(_PENDING, []):
        if inspect(row).key is None:
            continue
        # Best-effort: a logging handler that throws must not take down a
        # transaction that has already committed.
        try:
            audit_logger.info(json.dumps(envelope, separators=(",", ":")))
        except Exception:  # pragma: no cover - a broken handler, not our logic
            logging.getLogger(__name__).exception("audit log line could not be emitted")


@event.listens_for(Session, "after_soft_rollback")
def _discard_uncommitted_envelopes(session: Session, previous_transaction) -> None:
    """Drop the lines for work that did not land.

    A savepoint's rollback keeps the queue: what it undid is expunged with it
    and judged row by row when the transaction commits.
    """
    if previous_transaction.nested:
        return
    session.info.pop(_PENDING, None)


async def record(
    session: AsyncSession,
    *,
    event_type: AuditEventType,
    actor_user_id: Optional[int],
    target_user_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    detail: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    """Record one action in ``session``'s transaction and emit its log line.

    ``actor_user_id`` is ``None`` for an action nobody signed in took — see
    ``AuditEvent.actor_user_id``.

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
    # Flushed now, so the row belongs to whatever transaction or savepoint is
    # open at this point and a refused insert surfaces here, at the call.
    await session.flush()

    # Queued, not emitted. The line goes out when the transaction commits, so
    # the two sinks cannot disagree: an action that rolls back leaves no row
    # and tells nobody it happened.
    session.info.setdefault(_PENDING, []).append((event, event.envelope))

    return event


_OMITTED = object()


def _recordable(value: Any) -> Any:
    """``value`` as it may appear in a record, or ``_OMITTED``.

    Booleans, numbers, ``None`` and enumeration members are copied. A string
    is not: a string field can hold a secret, an address, a name, a URL, and
    the record names the field instead. A list or set is copied only when
    every element is.
    """
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [_recordable(item) for item in value]
        if any(item is _OMITTED for item in items):
            return _OMITTED
        return sorted(items, key=repr) if isinstance(value, (set, frozenset)) else items
    return _OMITTED


def changed_fields(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """What a write changed, in the form a configuration record carries.

    ``{"changed": [field, ...], "values": {field: {"from": .., "to": ..}}}``.
    Every field whose value differs is named; a before/after pair is copied
    in only where both sides are recordable (see ``_recordable``), so a
    rotated secret or a retyped address is recorded as the fact that the
    field moved and nothing more. Fields present on one side only count as
    changed from or to ``None``.
    """
    names = sorted(set(before) | set(after))
    changed: list[str] = []
    values: dict[str, dict[str, Any]] = {}
    for name in names:
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        changed.append(name)
        old_r, new_r = _recordable(old), _recordable(new)
        if old_r is not _OMITTED and new_r is not _OMITTED:
            values[name] = {"from": old_r, "to": new_r}
    return {"changed": changed, "values": values}


def snapshot(obj: Any, names: Iterable[str]) -> dict[str, Any]:
    """The named attributes of ``obj``, for a before/after ``changed_fields``."""
    return {name: getattr(obj, name) for name in names}
