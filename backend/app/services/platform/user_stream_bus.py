"""Carrying a per-user frame between workers, over Postgres.

The API may run as more than one process. A frame raised by the worker that
handled a request has to reach the worker holding that person's socket, and
those are routinely not the same one.

This uses ``LISTEN``/``NOTIFY``, which is already deployed everywhere the app
is: no broker to run, no port to open, no credential to rotate, and no second
service between a self-hosted install and its own realtime. It rides the
database connection this codebase has already built its roles and policies
around, which for a bus carrying no content is the whole of what it needs.

Two properties of the mechanism shape the code below:

* **``LISTEN`` is session state.** It belongs to one connection for as long as
  that connection lives, so it cannot come from a transaction pool that hands
  out a different backend each time. This holds its own connection, apart from
  every engine. ``NOTIFY`` has no such constraint — it is an ordinary statement
  — but it is sent on this same connection to keep the whole bus in one place.
* **Delivery is at-most-once and only to whoever is listening now.** There is
  no queue and no replay: a worker that was reconnecting missed what went past.
  That is acceptable precisely because a frame is only ever a nudge to refetch,
  and it is why nothing here is allowed to be load-bearing.

Every failure is therefore soft. Where the bus cannot start, callers still
deliver to their own process's sockets and the deployment behaves exactly as it
did before this existed.
"""

import asyncio
import logging
from contextlib import suppress
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

import asyncpg

from app.core.config import settings

logger = logging.getLogger(__name__)

#: How long to wait before rebuilding a connection that dropped. A bus that is
#: down costs cross-process delivery, not correctness, so this backs off rather
#: than hammering a database that may be the reason it dropped.
_RECONNECT_DELAY_SECONDS = 5.0
_RECONNECT_MAX_SECONDS = 60.0

#: Delivery tasks in flight, held so the event loop's weak reference cannot
#: collect one mid-frame.
_inflight: set[asyncio.Task] = set()


def _dsn() -> str:
    """The connection to listen on, as libpq spells it.

    ``LISTEN`` needs a session it keeps, so this deliberately does not come from
    any of the app's engines — those pool, and a pooled connection is a
    different backend from one statement to the next.

    Which address to use is a deployment's own to state
    (``DATABASE_URL_LISTEN``); unset, it falls back to the ordinary database
    URL, which is right for the common case of an app talking to Postgres
    directly.
    """
    url = settings.DATABASE_URL_LISTEN or settings.DATABASE_URL
    parts = urlsplit(url)
    # SQLAlchemy spells the driver into the scheme; asyncpg wants plain
    # ``postgresql://``.
    scheme = parts.scheme.split("+", 1)[0]
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


class UserStreamBus:
    """One held connection: listening for other workers, and telling them."""

    def __init__(self) -> None:
        self._connection: Optional[asyncpg.Connection] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        # One statement at a time on the held connection. A connection carries
        # a single operation, so two overlapping sends raise rather than queue
        # — and the fan-out path publishes a frame per member at once, which is
        # exactly where that would bite.
        self._send_lock = asyncio.Lock()
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._connection is not None and not self._connection.is_closed()

    async def start(self) -> None:
        """Open the connection and subscribe. Never raises.

        A deployment that cannot reach the bus — the address is a transaction
        pooler, the network says no — must still serve requests, so this
        reports and returns rather than holding up startup.
        """
        self._stopping = False
        if self._task is None:
            self._task = asyncio.create_task(self._maintain())

    async def stop(self) -> None:
        """Stand the bus down and wait for its connection to be released.

        The connection is closed by the task that opened it (see
        ``_maintain``); this waits for that to finish rather than racing it.
        """
        self._stopping = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._connection = None

    async def notify(self, payload: str) -> None:
        """Put one frame on the bus for the other workers.

        Serialized: senders wait for each other rather than sharing the
        connection, because a connection performs one operation at a time and
        overlapping sends raise instead of queueing. Frames are one small
        statement each, so the wait is short and the alternative is losing
        them.

        Raises when the bus is not up. The caller treats that as "no
        cross-process delivery this time", never as a failed request — see
        ``user_stream._publish_remote``.
        """
        from app.services.platform.user_stream import CHANNEL

        async with self._send_lock:
            connection = self._connection
            if connection is None or connection.is_closed():
                raise RuntimeError("user stream bus is not connected")
            await connection.execute("SELECT pg_notify($1, $2)", CHANNEL, payload)

    async def _maintain(self) -> None:
        """Keep a listening connection up, reconnecting with backoff."""
        from app.services.platform.user_stream import CHANNEL

        delay = _RECONNECT_DELAY_SECONDS
        while not self._stopping:
            connection: Optional[asyncpg.Connection] = None
            try:
                connection = await asyncpg.connect(dsn=_dsn())
                await connection.add_listener(CHANNEL, self._on_notify)
                async with self._lock:
                    self._connection = connection
                logger.info("user stream bus listening on %s", CHANNEL)
                delay = _RECONNECT_DELAY_SECONDS
                # Hold the connection open. asyncpg dispatches notifications on
                # its own reader task, so there is nothing to poll here — this
                # waits until the connection goes away.
                while not self._stopping and not connection.is_closed():
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                # First failure is worth a line; the retries are not, or a
                # database that stays down fills the log with one message.
                logger.info(
                    "user stream bus unavailable; cross-process frames are not "
                    "being delivered by this worker",
                    exc_info=True,
                )
            finally:
                # Closed here, by whoever opened it. ``stop()`` cancels this
                # task, and a cancel lands *inside* the loop above — so a close
                # that lived only in ``stop()`` would find the attribute
                # already cleared and leave the socket open.
                async with self._lock:
                    self._connection = None
                if connection is not None and not connection.is_closed():
                    with suppress(Exception):
                        await connection.close()
            if self._stopping:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_SECONDS)

    def _on_notify(self, _connection, _pid, _channel, payload: str) -> None:
        from app.services.platform.user_stream import deliver_remote

        # asyncpg calls this from its reader task, so delivery is scheduled
        # rather than awaited. The task is held until it finishes: the loop
        # keeps only a weak reference, and a collected task drops the frame.
        task = asyncio.create_task(deliver_remote(payload))
        _inflight.add(task)
        task.add_done_callback(_inflight.discard)


bus = UserStreamBus()


async def notify(payload: str) -> None:
    await bus.notify(payload)


async def start() -> None:
    await bus.start()


async def stop() -> None:
    await bus.stop()
