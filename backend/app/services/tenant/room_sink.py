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

Both are scoped to the guilds this process actually holds a socket for, so a
deployment with nobody connected reads nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import session as db_session
from app.db.event_capture import OUTBOX_CHANNEL
from app.db.session import set_rls_context
from app.models.tenant.event_outbox import EventOutbox
from app.services.realtime import manager

logger = logging.getLogger(__name__)

#: The channel the capture raises. One declaration, in the module that renders
#: the trigger raising it.
CHANNEL = OUTBOX_CHANNEL

#: How often the log is read for guilds a hint might have missed.
ROOM_SWEEP_SECONDS = 15

#: Changes one frame will carry. A bulk write — an import, a purge — can put
#: thousands of rows in one transaction, and naming every one of them would
#: send a large frame to every socket in the room to say what its last few
#: entries already say. Past this the frame says so instead, and the client
#: refetches the guild rather than a list of ids.
MAX_CHANGES = 500

_SCHEMA_PREFIX = "guild_"

#: guild_id -> the highest outbox id this process has fanned out for it. In
#: memory and per process: it says where THIS process's sockets have been
#: brought up to, which is not a fact about the guild and not one worth
#: keeping across a restart.
_delivered: dict[int, int] = {}


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
        return {"changes": [], "more": True}
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
    ids = [row.id for row in rows if row.id is not None]
    if ids:
        _delivered[guild_id] = max(_delivered.get(guild_id, 0), max(ids))


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
            await _fan_out(guild_id, await _rows_of_transaction(session, int(txn)))
    except Exception:
        logger.exception("room sink: fan-out failed for guild %s", guild_id)


async def process_room_sweep() -> None:
    """Read the log for every guild this process is holding sockets for.

    The backstop to the hints, which reach only whoever is listening when they
    are raised. Reading by id can miss a transaction that was in flight while a
    later one committed — that one is what the hint delivered — so the two
    cover each other rather than either being exact.
    """
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
                floor = _delivered.get(guild_id)
                if floor is None:
                    # First sight of this guild. Mark where the log is and send
                    # nothing: whoever just connected fetched as they mounted.
                    highest = (
                        await session.exec(select(func.max(EventOutbox.id)))
                    ).one()
                    _delivered[guild_id] = highest or 0
                    continue
                rows = list(
                    await session.exec(
                        select(EventOutbox)
                        .where(EventOutbox.id > floor)
                        .order_by(EventOutbox.id.asc())
                    )
                )
                await _fan_out(guild_id, rows)
            except Exception:
                logger.exception("room sink: sweep failed for guild %s", guild_id)
                await session.rollback()
