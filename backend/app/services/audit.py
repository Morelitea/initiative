"""Writing down what was done.

One function. A call site is a single line, and adding a newly-audited action
is that line plus an ``AuditEventType`` member and its metadata row — there is
no second place to register anything.

The record is one JSON line on the ``audit`` logger, written after the
transaction that performed the action commits, so the line and the action
land together or not at all. It is written nowhere else: the platform that
ships this process's logs is where the record is kept, queried, retained and
alerted on. A record staged inside a savepoint goes with the savepoint.

Identity is never in the line — ids only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.orm import Session, SessionTransaction
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import SCHEMA_VERSION, SERVICE, AuditEventType, meta_for

audit_logger = logging.getLogger("audit")

#: Envelopes staged in a session, each with the transaction it was staged in,
#: waiting on the commit. Kept on ``Session.info`` rather than in a module
#: global so concurrent requests never share a queue.
_PENDING = "audit_pending_envelopes"


def _current_transaction(session: AsyncSession) -> SessionTransaction:
    """The innermost transaction open on ``session``, begun here if none is:
    a record needs one to ride, so that a rollback before the first
    statement still discards it."""
    sync = session.sync_session
    return sync.get_nested_transaction() or sync.get_transaction() or sync.begin()


def _within(txn: SessionTransaction | None, ancestor: SessionTransaction) -> bool:
    while txn is not None:
        if txn is ancestor:
            return True
        txn = txn.parent
    return False


@event.listens_for(Session, "after_commit")
def _emit_committed_envelopes(session: Session) -> None:
    """Ship the lines for work that actually landed."""
    for _txn, envelope in session.info.pop(_PENDING, []):
        # Best-effort: a logging handler that throws must not take down a
        # transaction that has already committed.
        try:
            audit_logger.info(json.dumps(envelope, separators=(",", ":")))
        except Exception:  # pragma: no cover - a broken handler, not our logic
            logging.getLogger(__name__).exception("audit log line could not be emitted")


@event.listens_for(Session, "after_soft_rollback")
def _discard_uncommitted_envelopes(
    session: Session, previous_transaction: SessionTransaction
) -> None:
    """Drop the lines for work that did not land.

    A savepoint's rollback drops what was staged inside it and keeps the
    rest; the outermost rollback drops everything.
    """
    pending = session.info.get(_PENDING)
    if not pending:
        return
    if previous_transaction.parent is None:
        session.info.pop(_PENDING, None)
        return
    session.info[_PENDING] = [
        (txn, envelope)
        for txn, envelope in pending
        if not _within(txn, previous_transaction)
    ]


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
) -> dict[str, Any]:
    """Stage one action's record for ``session``'s commit, and return it.

    ``actor_user_id`` is ``None`` for an action nobody signed in took: a
    refused sign-in, a system sweep. ``guild_id`` names the community the
    action happened in or to, where there is one. Staged, not emitted: the
    caller owns the transaction, which is what makes the record and the thing
    it records land together.
    """
    meta = meta_for(event_type)
    envelope: dict[str, Any] = {
        # The key a collector routes on: this line is the audit stream, and
        # the application's own logs are not.
        "stream": "audit",
        # And which service's: billing and auto write the same shape.
        "service": SERVICE,
        "schema_version": SCHEMA_VERSION,
        "event_uuid": str(uuid4()),
        "event_type": event_type.value,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
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
    session.info.setdefault(_PENDING, []).append(
        (_current_transaction(session), envelope)
    )
    return envelope


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
