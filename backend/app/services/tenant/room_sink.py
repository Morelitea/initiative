"""The change log, fanned out to the sockets watching it.

Every write to guild content already lands in ``event_outbox``, stamped by the
capture trigger with the initiative it belongs to and the resources around it.
This reads that log and pokes the initiative rooms — which is the same signal
the endpoints used to raise by hand, from a source that cannot forget.

Three things follow from taking it off the log rather than off the call sites:

* **A write signals once, wherever it happened.** An endpoint, a background
  job, a cascade, a migration: if it changed a content row it is in the log,
  so it reaches the room. Nothing has to remember to announce itself, and a
  new tool is live the day its table is captured.
* **Fan-out is not this process's own.** The hint arrives over
  ``LISTEN``/``NOTIFY``, so every worker holding a socket for that guild reads
  the same committed rows. A signal raised on one worker no longer stops there.
* **The envelope is the log's.** ``resource``, ``parents``, ``action`` — ids
  and names, never a value, exactly as a webhook subscriber receives them. The
  client refetches through the RLS-gated REST path, which stays the only
  authorization decision point.

Two paths in, on purpose. The **hint** is what makes it prompt: the capture
raises ``pg_notify`` at commit, naming the schema and the transaction, and this
reads exactly that transaction's rows. The **sweep** is what makes it durable:
notifications reach only whoever is listening at the time, so a worker whose
bus connection was rebuilding missed whatever went past. Both are at-least-once
and neither needs to be exact — a signal delivered twice costs one refetch.

The sweep reads **a window of the log by time**, not everything above the
highest id it has sent. Outbox ids are handed out at insert and published at
commit, so a transaction that began earlier can become visible after a later
one has already gone out; a mark that only moved forward by id would step over
it, and where that transaction's hint was one a reconnect missed, nothing would
ever go back for it. Reading by time and skipping what has already been sent
has no such hole. What reading a window cannot reach is a transaction that
takes longer than the window to commit — its rows are stamped when it began —
and that one is delivered by its hint.

So the hint is load-bearing for exactly one case, and the case where hints go
missing is knowable: they reach only whoever is listening, and the bus counts
the times it has come up. A sweep that finds that number has moved knows it was
deaf for a while and cannot know for how long, so it says the one honest thing
— that more happened than it can name — and the room reads the guild again.
Rare, coarse, and the only part of this that is.

Both are scoped to the guilds this process actually holds a socket for, so a
deployment with nobody connected reads nothing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import session as db_session
from app.db.event_capture import OUTBOX_CHANNEL
from app.db.session import set_rls_context
from app.models.tenant.event_outbox import EventOutbox
from app.services.platform import notify_bus
from app.services.realtime import manager

logger = logging.getLogger(__name__)

#: The channel the capture raises. One declaration, in the module that renders
#: the trigger raising it.
CHANNEL = OUTBOX_CHANNEL

#: How often the log is read for guilds a hint might have missed.
ROOM_SWEEP_SECONDS = 15

#: How much of the log a sweep reads. Every row inside it is either already
#: sent or about to be, so this also bounds what has to be remembered: the ids
#: in the window, per guild this process holds a socket for.
SWEEP_WINDOW_SECONDS = 60

#: What a frame says when it cannot name what changed: a bulk write past the
#: cap below, or a gap in the hints. The room reads the guild again.
EVERYTHING = {"changes": [], "more": True}

#: Changes one frame will carry. A bulk write — an import, a purge — can put
#: thousands of rows in one transaction, and naming every one of them would
#: send a large frame to every socket in the room to say what its last few
#: entries already say. Past this the frame says so instead, and the client
#: refetches the guild rather than a list of ids.
MAX_CHANGES = 500

_SCHEMA_PREFIX = "guild_"

#: The bus generation the last sweep ran under. A change means hints went
#: missing in between.
_bus_generation: int | None = None

#: guild_id -> the outbox ids this process has already sent for it, pruned to
#: the sweep window. In memory and per process: it says what THIS process's
#: sockets have been told, which is not a fact about the guild and not one
#: worth keeping across a restart. A guild absent here has never been read,
#: which is not the same as having been read and found empty.
_delivered: dict[int, set[int]] = {}


def _guild_id(schema: str) -> int | None:
    """The guild a schema name addresses, or None if it addresses none."""
    if not schema.startswith(_SCHEMA_PREFIX):
        return None
    tail = schema[len(_SCHEMA_PREFIX) :]
    return int(tail) if tail.isdigit() else None


def _change(row: EventOutbox) -> dict[str, Any]:
    """One log row as the client reads it: what moved, and what it sits in."""
    return {
        "resource": {"type": row.resource_type, "id": row.resource_id},
        "parents": list(row.parents),
        "action": row.action,
    }


def _frame(rows: list[EventOutbox]) -> dict[str, Any]:
    """One room's share of a batch.

    Repeats collapse: a row written three times in one transaction is one thing
    to refetch, and the client would do the same work three times over.
    """
    seen: dict[tuple[str, int, str], EventOutbox] = {}
    for row in rows:
        seen.setdefault((row.resource_type, row.resource_id, row.action), row)
    changes = list(seen.values())
    if len(changes) > MAX_CHANGES:
        return dict(EVERYTHING)
    return {"changes": [_change(row) for row in changes]}


async def _fan_out(guild_id: int, rows: list[EventOutbox]) -> None:
    """Send each initiative its own changes, and the guild's to everyone.

    A row with no initiative belongs to none — a tag, an installed app — and is
    something every member of the guild can already read, so it goes to every
    socket rather than to a room.
    """
    if not rows:
        return
    by_room: dict[int | None, list[EventOutbox]] = {}
    for row in rows:
        by_room.setdefault(row.initiative_id, []).append(row)
    for initiative_id, batch in by_room.items():
        message = _frame(batch)
        if initiative_id is None:
            await manager.broadcast_guild(guild_id, message)
        else:
            await manager.broadcast(guild_id, initiative_id, message)
    _delivered.setdefault(guild_id, set()).update(_ids(rows))


def _ids(rows: list[EventOutbox]) -> set[int]:
    return {row.id for row in rows if row.id is not None}


async def _rows_in_window(session: AsyncSession) -> list[EventOutbox]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=SWEEP_WINDOW_SECONDS)
    return list(
        await session.exec(
            select(EventOutbox)
            .where(EventOutbox.occurred_at > cutoff)
            .order_by(EventOutbox.id.asc())
        )
    )


async def _rows_of_transaction(session: AsyncSession, txn_id: int) -> list[EventOutbox]:
    return list(
        await session.exec(
            select(EventOutbox)
            .where(EventOutbox.txn_id == txn_id)
            .order_by(EventOutbox.id.asc())
        )
    )


async def deliver(payload: str) -> None:
    """One committed transaction, off the hint the capture raised for it.

    The hint arrives at COMMIT and names the transaction, so there is no
    watermark to reason about here: these are exactly the rows that just became
    visible, whatever ids they were given while in flight.
    """
    schema, _, txn = payload.partition(":")
    guild_id = _guild_id(schema)
    if guild_id is None or not txn.isdigit():
        logger.warning("room sink: unreadable hint on %s", CHANNEL)
        return
    if guild_id not in set(manager.guild_ids()):
        return
    try:
        async with db_session.AdminSessionLocal() as session:
            await set_rls_context(session, guild_id=guild_id, guild_role="admin")
            rows = await _rows_of_transaction(session, int(txn))
            if guild_id not in _delivered:
                # First read of this guild here. Everything else already in the
                # window belongs to before whoever just connected, who fetched
                # as they mounted — so that is marked seen rather than sent,
                # and this transaction, which is news, is not.
                _delivered[guild_id] = _ids(await _rows_in_window(session)) - _ids(rows)
            await _fan_out(guild_id, rows)
    except Exception:
        logger.exception("room sink: fan-out failed for guild %s", guild_id)


async def process_room_sweep() -> None:
    """Read the log for every guild this process is holding sockets for.

    The backstop to the hints, which reach only whoever is listening when they
    are raised — and, by reading a window rather than everything above a mark,
    the answer to a transaction becoming visible after a later one has already
    gone out.
    """
    global _bus_generation
    generation = notify_bus.bus.generation
    # A first observation says nothing: it is where counting starts, not a gap.
    deaf = _bus_generation is not None and generation != _bus_generation
    _bus_generation = generation

    watched = manager.guild_ids()
    for guild_id in set(_delivered) - set(watched):
        # Nobody here is watching it any more. Dropping the mark means the next
        # socket to arrive is brought up to the log's current end rather than
        # told everything that happened while nobody was looking.
        _delivered.pop(guild_id, None)
    if not watched:
        return
    async with db_session.AdminSessionLocal() as session:
        for guild_id in watched:
            session.expunge_all()
            try:
                await set_rls_context(session, guild_id=guild_id, guild_role="admin")
                rows = await _rows_in_window(session)
                sent = _delivered.get(guild_id)
                if sent is None:
                    # First sight of this guild. Mark what is there and send
                    # nothing: whoever just connected fetched as they mounted.
                    _delivered[guild_id] = _ids(rows)
                    continue
                if deaf:
                    # Whatever the hints carried while the bus was rebuilding
                    # reached nobody, and a transaction that began before this
                    # window cannot be found by reading it. What was missed is
                    # not knowable, so the room is told that much.
                    await manager.broadcast_guild(guild_id, dict(EVERYTHING))
                else:
                    await _fan_out(guild_id, [r for r in rows if r.id not in sent])
                # Everything in the window has now been sent, and anything that
                # has fallen out of it will not be read again — so this is both
                # the record and the pruning of it.
                _delivered[guild_id] = _ids(rows)
            except Exception:
                logger.exception("room sink: sweep failed for guild %s", guild_id)
                await session.rollback()
