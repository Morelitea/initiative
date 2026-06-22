"""Continuous authorization for content-streaming WebSockets.

The realtime *content* channels (collaboration, counters, queues) push live data
for a connection's whole lifetime. Authorizing only at connect leaves a
revocation gap: a grant / membership / role / PAM change mid-session keeps
streaming until disconnect. This module is the single place that closes that gap
for every content channel — the same six-gate check, re-run continuously,
hard-disconnecting anyone who no longer qualifies.

**One source of truth: the re-check IS the join check.** ``_still_authorized``
runs ``establish_guild_access`` (guild membership / PAM / break-glass / guild
role) → the adapter's ``authorize`` (load the resource under RLS, which enforces
the *initiative* boundary, then the DAC ``compute_*_permission``). So every layer
— guild, initiative, role, DAC sharing, PAM, guild-admin — is re-enforced
identically to the REST path, never re-derived. A guild removal makes
``establish_guild_access`` raise; an initiative removal hides the resource at the
RLS load; a DAC/role change shows up in ``compute_*``. All caught by one call.

Two triggers (per ``history/realtime-authorization-design.md`` + product decision):
  * **guild- and initiative-level access removal is IMMEDIATE** — the mutation
    calls ``revoke_user`` and that user's content sockets are re-checked at once;
  * **within-initiative DAC / settings changes ride a bounded re-auth interval**
    — the background loop re-checks every socket every ``REAUTH_INTERVAL_SECONDS``.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional, Set, Tuple

from fastapi import WebSocket, status
from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildAccessError, establish_guild_access
from app.db.session import AsyncSessionLocal
from app.models.user import User

logger = logging.getLogger(__name__)

# Upper bound on how long a within-initiative DAC/settings revocation can lag
# (guild- and initiative-level removals are immediate via revoke_user).
REAUTH_INTERVAL_SECONDS = 30

# An adapter authorizes one socket against its resource, on a session that has
# ALREADY been guild-established: load the resource (RLS enforces guild +
# initiative + PAM) and check DAC (compute_*_permission). True iff the user may
# still stream it. Each content channel supplies its own (closing over the
# resource id + its DAC resolver) — the per-tool half of the spine.
Authorizer = Callable[[AsyncSession, User], Awaitable[bool]]

# A fan-out room is (guild_id, resource_type, resource_id). The guild_id is
# REQUIRED: resource ids (document/counter-group/queue) are per-guild-schema
# SERIAL sequences and collide across guilds, so a bare id would cross the
# tenancy boundary — the same trap as the events bus.
RoomKey = Tuple[int, str, int]


@dataclass
class _StreamMember:
    websocket: WebSocket
    user: User
    guild_id: int
    initiative_id: int
    room: RoomKey
    authorize: Authorizer


class StreamAuthority:
    """The one streaming spine for every content channel (collaboration, counters,
    queues): it owns the socket registry, fan-out, and the single continuous
    re-authorization mechanism. Per-tool endpoints stay thin — they supply a DAC
    ``authorize`` closure and emit through ``emit``; there is no per-tool realtime
    manager."""

    def __init__(self) -> None:
        self._members: dict[WebSocket, _StreamMember] = {}
        self._rooms: Dict[RoomKey, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._loop_task: Optional[asyncio.Task] = None

    async def join(
        self,
        websocket: WebSocket,
        user: User,
        *,
        guild_id: int,
        initiative_id: int,
        resource_type: str,
        resource_id: int,
        authorize: Authorizer,
    ) -> None:
        """Register an already-authorized content socket: add it to its fan-out
        room and govern it for continuous re-auth.

        The caller must have run the full join check (``establish_guild_access`` +
        the adapter load + DAC) at connect; the socket is governed from here on.
        """
        room: RoomKey = (guild_id, resource_type, resource_id)
        async with self._lock:
            self._members[websocket] = _StreamMember(
                websocket=websocket,
                user=user,
                guild_id=guild_id,
                initiative_id=initiative_id,
                room=room,
                authorize=authorize,
            )
            self._rooms.setdefault(room, set()).add(websocket)
        self._ensure_loop()

    async def leave(self, websocket: WebSocket) -> None:
        async with self._lock:
            member = self._members.pop(websocket, None)
            if member is not None:
                sockets = self._rooms.get(member.room)
                if sockets is not None:
                    sockets.discard(websocket)
                    if not sockets:
                        del self._rooms[member.room]

    async def emit(
        self,
        guild_id: int,
        resource_type: str,
        resource_id: int,
        event_type: str,
        data: Dict[str, Any],
    ) -> None:
        """Fan a server event out to one resource's room (guild-namespaced).

        Replaces the old per-tool ``*_manager.broadcast``; the message shape
        ``{type, data, timestamp}`` is unchanged for the clients. Send failures
        drop the socket (the continuous re-auth loop / leave handle the rest)."""
        room: RoomKey = (guild_id, resource_type, resource_id)
        async with self._lock:
            sockets = list(self._rooms.get(room, set()))
        message = {
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        for websocket in sockets:
            try:
                await websocket.send_json(message)
            except Exception:
                await self.leave(websocket)

    def room_size(self, guild_id: int, resource_type: str, resource_id: int) -> int:
        return len(self._rooms.get((guild_id, resource_type, resource_id), set()))

    async def revoke_user(self, guild_id: int, user_id: int) -> None:
        """Immediately re-check every content socket held by ``user_id`` in
        ``guild_id`` and hard-disconnect those who lost access. Call after a
        guild/initiative membership change, role change, or PAM revoke for the
        user — guild- and initiative-level access is enforced without waiting for
        the bounded loop."""
        await self._recheck(lambda m: m.guild_id == guild_id and m.user.id == user_id)

    # ── internals ──────────────────────────────────────────────────────────

    async def _recheck(self, predicate: Callable[[_StreamMember], bool]) -> None:
        async with self._lock:
            targets = [m for m in self._members.values() if predicate(m)]
        for member in targets:
            if not await self._still_authorized(member):
                await self._disconnect(member)

    async def _still_authorized(self, member: _StreamMember) -> bool:
        """Re-run the FULL join check on a fresh session — every gate, one place.

        Fail closed: any error (including a since-dropped guild schema) drops the
        socket rather than leaving a potentially-unauthorized stream open.
        """
        try:
            async with AsyncSessionLocal() as session:
                # AsyncSessionLocal skips get_session's per-request reset; clear
                # any stale pooled-connection GUCs before establishing context.
                await session.execute(
                    text(
                        "SELECT set_config('role', 'none', false), "
                        "set_config('search_path', 'public', false)"
                    )
                )
                try:
                    await establish_guild_access(session, member.user, member.guild_id)
                except GuildAccessError:
                    return False  # guild membership / PAM / break-glass revoked
                # Initiative boundary (RLS resource load) + DAC, inside the adapter.
                return await member.authorize(session, member.user)
        except Exception:
            logger.exception(
                "stream re-auth check failed; disconnecting to fail closed"
            )
            return False

    async def _disconnect(self, member: _StreamMember) -> None:
        await self.leave(member.websocket)
        try:
            await member.websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        except Exception:
            pass

    def _ensure_loop(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._reauth_loop())

    async def _reauth_loop(self) -> None:
        """Bounded re-auth backstop: re-check every socket every interval. Catches
        within-initiative DAC/settings changes (deliberately not hooked for
        immediate revocation) within a bounded window, and backstops any missed
        immediate trigger."""
        while True:
            await asyncio.sleep(REAUTH_INTERVAL_SECONDS)
            try:
                await self._recheck(lambda _m: True)
            except Exception:
                logger.exception("stream re-auth loop iteration failed")


authority = StreamAuthority()
