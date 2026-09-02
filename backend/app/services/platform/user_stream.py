"""The per-user socket, and the bus behind it.

One person's open tabs, and how a frame reaches all of them wherever they are —
including from a worker that is not the one holding the socket.

Two callers sit on this: :mod:`app.services.platform.notification_stream` (the
inbox moved) and :mod:`app.services.platform.account_stream` (your standing
changed). Both send the same shape and neither owns the machinery, so there is
one place to look when a frame does not arrive.

Every frame is a **content-free invalidation signal**: it says something you can
already read has changed, never what it now says. The client refetches through
the ordinary authorized endpoint, and that request is the only decision point.
So the worst a routing mistake here can do is cost somebody a wasted refetch.

Delivery is two paths, and the split is deliberate:

* **Local** — this worker's own sockets, always, straight from the hook that
  runs once the writing transaction commits.
* **Cross-process** — ``pg_notify`` on a dedicated connection, picked up by
  every other worker's listener.

The local path is what makes this fail-soft. Where the bus cannot be reached the
cross-process half is simply absent and everything behaves as it did before it
existed; nothing waits on it and nothing breaks when it is missing. Each process
stamps frames with its own ``origin`` and skips its own on the way back in, so
the two paths never deliver twice.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from sqlalchemy import event
from sqlalchemy.orm import Session as SyncSession

from app.models.platform.user import Presence
from app.services.platform import presence

logger = logging.getLogger(__name__)

#: Key under which a session accumulates frames it has earned but not committed.
_PENDING_KEY = "user_stream_pending"

#: The Postgres channel every worker listens on. One channel for both callers:
#: the frames are tiny and each names its own resource, so splitting them would
#: buy a second listener and no clarity.
CHANNEL = "user_stream"

#: Who this process is. Stamped on every frame we publish so our own listener
#: can tell our echo from somebody else's news and drop it.
ORIGIN = uuid.uuid4().hex

# ``loop.create_task`` keeps only a weak reference, so a fire-and-forget send
# can be collected mid-flight. Hold them until they finish.
_inflight: Set[asyncio.Task] = set()


class UserStream:
    """Which sockets belong to which user, on this process.

    A user may have several (tabs, phone + laptop); every one gets the frame,
    because each holds its own client-side cache.

    This is one process's sockets, held in memory — which is what the bus below
    exists to bridge. Presence is fed from the same connect/disconnect, since a
    socket here is what "has Initiative open" means.
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
        presence_known_at: Optional[float] = None,
    ) -> None:
        """Register an already-accepted socket as this user's.

        ``presence_known_at`` is when the caller read ``chosen_presence``, so
        the roll can tell a value read before a change from one read after it.
        """
        async with self._lock:
            self._sockets.setdefault(user_id, set()).add(websocket)
            self._socket_user[websocket] = user_id
        presence.online.arrived(user_id, chosen_presence, known_at=presence_known_at)

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
        """Fan one frame out to every socket this user has open **here**."""
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

    def connected_users(self) -> Set[int]:
        """Who this process is holding a socket for.

        Lets a fan-out ask "which of these thousands of members are actually
        here" instead of addressing every one of them.
        """
        return set(self._sockets)


stream = UserStream()


def build_frame(
    resource: str, action: str, ids: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    """The shape both channels send.

    ``ids`` names what to refetch and nothing about it; for a channel addressed
    by *who is asking* it is empty, because there is nothing to name.
    """
    return {
        "resource": resource,
        "action": action,
        "ids": ids or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def publish(user_id: int, frame: Dict[str, Any]) -> None:
    """Deliver one frame to this user, wherever their tabs are.

    Local sockets first and unconditionally, then the bus for everybody else's
    worker. The order matters only in that the local half must not be able to
    fail because of the remote one.
    """
    await stream.send(user_id, frame)
    await _publish_remote(user_id, frame)


async def _publish_remote(user_id: int, frame: Dict[str, Any]) -> None:
    """Hand the frame to the other workers, if we can reach them.

    A bus we cannot reach is not an error anybody can act on — the frame was
    already delivered to every socket this process holds, and the client keeps
    a backstop refetch for exactly this. So it is logged once at debug and the
    request carries on.
    """
    from app.services.platform import user_stream_bus

    try:
        await user_stream_bus.notify(
            json.dumps({"origin": ORIGIN, "user_id": user_id, "frame": frame})
        )
    except Exception:
        logger.debug("user_stream: cross-process publish unavailable", exc_info=True)


async def deliver_remote(payload: str) -> None:
    """Take a frame off the bus and give it to this worker's sockets.

    Skips our own echo: we already delivered it locally before publishing, and
    delivering it again would double every frame on a single-worker install.
    """
    try:
        message = json.loads(payload)
        origin = message["origin"]
        user_id = int(message["user_id"])
        frame = message["frame"]
    except Exception:
        logger.warning("user_stream: unreadable frame on %s", CHANNEL)
        return
    if origin == ORIGIN:
        return
    await stream.send(user_id, frame)


def queue_frame(session: Any, user_id: int | None, frame: Dict[str, Any]) -> None:
    """Note a frame this session has earned but not yet committed.

    Nothing is sent here — the hook below sends it once the transaction
    commits, so a rollback pokes nobody. A frame that arrived before the COMMIT
    would hand the client the state it is replacing, and nothing polls behind
    it closely enough to correct that.

    One frame per user **per channel** per transaction: a transaction writing
    three notifications pokes the inbox once, because every frame means the
    same thing ("refetch") and three would buy three identical requests. The
    first recorded wins, so a read-state change queued behind a creation does
    not downgrade it. Keyed by channel as well as by user, since an inbox frame
    and an account frame say different things and both are owed.

    ``session`` may be an ``AsyncSession`` (whose ``.info`` proxies the sync
    session's) or a sync session; both land in the dict the hook reads.
    """
    if user_id is None:
        return
    pending: Dict[Any, Dict[str, Any]] = session.info.setdefault(_PENDING_KEY, {})
    pending.setdefault((user_id, frame["resource"]), frame)


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
    pending = session.info.pop(_PENDING_KEY, None)
    if not pending:
        return
    for (user_id, _resource), frame in pending.items():
        _spawn(publish(user_id, frame))


def _discard_pending(session: SyncSession, *_args: Any) -> None:
    session.info.pop(_PENDING_KEY, None)


event.listens_for(SyncSession, "after_commit")(_emit_pending)
event.listens_for(SyncSession, "after_rollback")(_discard_pending)
event.listens_for(SyncSession, "after_soft_rollback")(_discard_pending)
