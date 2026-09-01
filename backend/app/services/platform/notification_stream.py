"""Per-user signal channel for the notification inbox.

The bell is a *personal* surface: a user's notifications span every guild they
belong to (and some, like ``user_pending_approval``, belong to no guild at
all), so this channel is keyed by user id and carries no guild in its address.
That is what makes it a separate object from :mod:`app.services.realtime`,
whose rooms are ``(guild_id, initiative_id)`` and whose sockets only exist
while a tab sits inside a guild.

Like every other realtime channel here, the stream is a **content-free
invalidation bus**: a frame says "your inbox changed", never what changed. The
client refetches ``GET /notifications/``, and that request — authenticated and
scoped to ``current_user`` — is the authorization gate.

Frames are emitted **after the writing transaction commits**, via an
``after_commit`` hook on the session that wrote the row. Poking on ``flush``
would race the client's refetch against our own COMMIT and could hand it the
inbox as it was *before* the notification landed — a signal that arrives once
and arrives early is worse than no signal at all, because nothing polls behind
it any more.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Set

from sqlalchemy import event
from sqlalchemy.orm import Session as SyncSession

from app.models.platform.user import Presence
from app.services.platform import presence

logger = logging.getLogger(__name__)

# Key under which a session accumulates the users whose inbox it has changed
# but not yet committed.
_PENDING_KEY = "notification_stream_pending"

# ``loop.create_task`` keeps only a weak reference to the task, so a
# fire-and-forget send can be garbage-collected mid-flight. Hold them here
# until they finish.
_inflight: Set[asyncio.Task] = set()


class NotificationStream:
    """Which sockets belong to which user, on this process.

    A user may have several (tabs, phone + laptop); every one of them gets the
    frame, because each holds its own React Query cache. Bounded the same way
    the guild presence roll is: these are one process's sockets. Where the API
    runs as more than one worker or replica, a commit on one of them reaches
    only the tabs that process holds — which is why the client keeps a slow
    backstop refetch even while its socket is open.
    """

    def __init__(self) -> None:
        self._sockets: Dict[int, Set[Any]] = {}
        self._socket_user: Dict[Any, int] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        user_id: int,
        websocket: Any,
        *,
        chosen_presence: Presence = Presence.online,
    ) -> None:
        """Register an already-accepted socket as this user's."""
        async with self._lock:
            self._sockets.setdefault(user_id, set()).add(websocket)
            self._socket_user[websocket] = user_id
        # This socket is open wherever they are in the app, including outside
        # any guild, so it is what "has Initiative open" means. It carries the
        # account's own choice of how to appear along with it, because the roll
        # answers both halves of that question together.
        presence.online.arrived(user_id, chosen_presence)

    async def disconnect(self, websocket: Any) -> None:
        """Drop a socket; the last one drops its user's entry entirely."""
        async with self._lock:
            user_id = self._socket_user.pop(websocket, None)
            if user_id is None:
                return
            sockets = self._sockets.get(user_id)
            if sockets is None:
                return
            sockets.discard(websocket)
            if not sockets:
                del self._sockets[user_id]
        presence.online.left(user_id)

    async def send(self, user_id: int, message: Dict[str, Any]) -> None:
        """Fan one frame out to every socket this user has open here."""
        async with self._lock:
            sockets = list(self._sockets.get(user_id, set()))
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception:
                # A socket that cannot be written to is gone; the endpoint's
                # own ``finally`` may not have run yet.
                await self.disconnect(websocket)

    def socket_count(self, user_id: int) -> int:
        return len(self._sockets.get(user_id, set()))


stream = NotificationStream()


async def signal_user(user_id: int, action: str = "changed") -> None:
    """Tell one user's open tabs that their inbox moved.

    ``ids`` is deliberately empty: the inbox is addressed by *who is asking*,
    so there is nothing for the client to name in its refetch and nothing here
    worth carrying. ``action`` distinguishes a new arrival from a read-state
    change only so a client could treat them differently; both mean "refetch".
    """
    await stream.send(
        user_id,
        {
            "resource": "notification",
            "action": action,
            "ids": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


def queue_signal(session: Any, user_id: int | None, action: str = "changed") -> None:
    """Note that this session changed ``user_id``'s inbox.

    Nothing is sent yet — the frame goes out from the ``after_commit`` hook
    below, so a transaction that rolls back never pokes anyone. ``session`` may
    be an ``AsyncSession`` (whose ``.info`` proxies the sync session's) or a
    sync session; both land in the same dict the hook reads.
    """
    if user_id is None:
        return
    pending = session.info.setdefault(_PENDING_KEY, {})
    # A read-state change queued behind a creation must not downgrade it: the
    # first action recorded for a user in this transaction wins, and every
    # action means "refetch" anyway.
    pending.setdefault(user_id, action)


def _spawn(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop (a sync script, a test driving a sync session): there is
        # nothing to deliver to, and the row is committed either way.
        coro.close()
        return
    task = loop.create_task(coro)
    _inflight.add(task)
    task.add_done_callback(_inflight.discard)


def _emit_pending(session: SyncSession) -> None:
    """``after_commit``: the rows are durable, so the pokes may go out."""
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    for user_id, action in pending.items():
        _spawn(signal_user(user_id, action))


def _discard_pending(session: SyncSession, *_args: Any) -> None:
    """``after_rollback``: the rows never happened, so neither do the pokes."""
    session.info.pop(_PENDING_KEY, None)


# propagate=True so the hooks also fire for SQLModel's Session subclass (the
# sync session under AsyncSession), matching the RLS replay hook in
# ``app.db.session``. Sessions that never queued anything are a no-op.
event.listen(SyncSession, "after_commit", _emit_pending, propagate=True)
event.listen(SyncSession, "after_rollback", _discard_pending, propagate=True)
event.listen(SyncSession, "after_soft_rollback", _discard_pending, propagate=True)
