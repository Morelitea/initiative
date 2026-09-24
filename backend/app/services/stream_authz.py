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

**The credential is re-checked too.** A socket keeps the sign-in it was opened
with — the session row and ``token_version`` a session JWT named, or the device
token — and every re-check asks whether that credential still stands: the
session's rotation chain still has a live row, the account's ``token_version``
has not moved, the device token has not been consumed. Ending a sign-in (sign
out, ending a session from the list, a password change) calls
``revoke_user_everywhere``, which re-checks rather than closes, so the account's
other connections stay open when their own credentials still stand. One
statement per table answers for every socket in a sweep.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Set, Tuple

from fastapi import WebSocket, status
from sqlalchemy import text
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import GuildAccessError, establish_guild_access
from app.core import auth_context
from app.db import session as db_session
from app.db.session import (
    CONNECTION_RESET_SQL,
    RLS_CONTEXT_MAX_AGE_SECONDS,
    AsyncSessionLocal,
)
from app.models.platform.user import User, UserStatus
from app.services.auth import sessions as session_service
from app.services.platform import user_tokens

logger = logging.getLogger(__name__)

# Upper bound on how long a within-initiative DAC/settings revocation can lag
# (guild- and initiative-level removals are immediate via revoke_user).
# Derived as half the session layer's snapshot-age floor: a healthy loop
# re-validates every registered socket well before any held context could
# trip StaleAuthorizationContext, and the two bounds cannot drift apart.
REAUTH_INTERVAL_SECONDS = RLS_CONTEXT_MAX_AGE_SECONDS // 2

#: The close code for a socket whose credential has ended, as opposed to one
#: whose access has (``WS_1008_POLICY_VIOLATION``). A client holding a newer
#: credential for the same account — the session a step-up or a password
#: change opened in its place — reconnects with it; one holding none is refused
#: at the handshake.
WS_CREDENTIAL_ENDED = 4001

# An adapter authorizes one socket against its resource, on a session that has
# ALREADY been guild-established: load the resource (RLS enforces guild +
# initiative + PAM) and check DAC (compute_*_permission). True iff the user may
# still stream it. Each content channel supplies its own (closing over the
# resource id + its DAC resolver) — the per-tool half of the spine.
# ``establish_guild_access`` records the guild lifecycle state (frozen content)
# in the request context, and the DAC engine caps its levels from it — so a
# writer socket in a guild that turns read_only fails the adapter's write check
# with no extra plumbing here.
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
    # The satisfied-provider set of the session that opened the socket,
    # captured at join. Replayed on every re-check so a guild auth policy
    # added mid-connection disconnects sockets whose session doesn't satisfy
    # it — same continuous-authorization rule as every other gate.
    satisfied_providers: frozenset[int] = frozenset()
    # The rest of that session's standing: the markers it recorded about how
    # it was opened. Captured at join for the same reason and presented the
    # same way — a re-check runs in another task's context, so it reads these
    # off the member rather than off whatever request happens to be in flight.
    session_amr: frozenset[str] = frozenset()
    # And what those providers asserted for the claims a community narrows one
    # of them by, captured for the same reason: the gate reads these off the
    # context too, and a re-check runs in another task's.
    satisfied_claims: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    # The credential that opened the socket, captured at join from what the
    # socket's authenticator recorded: the session row and ``token_version`` of
    # a session JWT, or the device token's id. ``session_id`` moves forward
    # along its rotation chain as the re-checks find the row the sign-in has
    # reached. All three ``None`` for a member registered with no credential
    # recorded, which has nothing of its own to re-check.
    session_id: Optional[uuid.UUID] = None
    token_version: Optional[int] = None
    device_token_id: Optional[int] = None
    # Per-connection state the channel owns and the spine only carries:
    # collaboration keeps the display name and write level it computed at
    # join here. It lives on the member so a channel never needs a second
    # registry of its own sockets — the thing that has to be keyed by socket
    # is keyed by socket exactly once, here.
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoomMember:
    """One connection in a room, as a channel sees it.

    ``user`` is the account that opened the socket and ``meta`` is whatever
    the channel attached at join. Two connections from one account are two
    members: a roster for *people* has to fold them together itself, which is
    a display choice, not a delivery one.
    """

    user: User
    meta: Mapping[str, Any]


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
        satisfied_providers: frozenset[int] = frozenset(),
        meta: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Register an already-authorized content socket: add it to its fan-out
        room and govern it for continuous re-auth.

        The caller must have run the full join check (``establish_guild_access`` +
        the adapter load + DAC) at connect; the socket is governed from here on.
        ``satisfied_providers`` is the joining session's satisfied set — the
        re-checks replay it against the guild's (possibly changed) auth policy.
        The factor flags and the narrowing claims beside it are read from the
        joining request's own auth context, where the credential validator
        recorded them, and so is which credential it was.
        """
        room: RoomKey = (guild_id, resource_type, resource_id)
        credential = auth_context.session_credential()
        async with self._lock:
            self._members[websocket] = _StreamMember(
                websocket=websocket,
                user=user,
                guild_id=guild_id,
                initiative_id=initiative_id,
                room=room,
                authorize=authorize,
                satisfied_providers=satisfied_providers,
                session_amr=auth_context.session_amr(),
                satisfied_claims=auth_context.satisfied_claims(),
                session_id=credential.session_id if credential else None,
                token_version=credential.token_version if credential else None,
                device_token_id=auth_context.device_token_id(),
                meta=dict(meta) if meta else {},
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

    async def emit_bytes(
        self,
        guild_id: int,
        resource_type: str,
        resource_id: int,
        payload: bytes,
        *,
        exclude: Optional[WebSocket] = None,
    ) -> None:
        """Fan a binary frame out to one resource's room (guild-namespaced).

        The byte-stream counterpart of :meth:`emit`, for channels whose wire
        format is not JSON — collaboration relays Yjs updates and awareness
        this way.

        ``exclude`` is the **connection** the frame came from, never a user.
        One account can hold several connections, and each of them is a peer
        of the others; the only frame worth withholding is the sender's own
        echo. Pass the originating socket.
        """
        room: RoomKey = (guild_id, resource_type, resource_id)
        async with self._lock:
            sockets = [s for s in self._rooms.get(room, set()) if s is not exclude]
        for websocket in sockets:
            try:
                await websocket.send_bytes(payload)
            except Exception:
                await self.leave(websocket)

    def room_members(
        self, guild_id: int, resource_type: str, resource_id: int
    ) -> list[RoomMember]:
        """Every connection in one room, with the state its channel attached.

        One entry per socket. A channel presenting people rather than
        connections folds by ``user.id`` itself.
        """
        room: RoomKey = (guild_id, resource_type, resource_id)
        return [
            RoomMember(user=member.user, meta=member.meta)
            for websocket in self._rooms.get(room, set())
            if (member := self._members.get(websocket)) is not None
        ]

    def room_size(self, guild_id: int, resource_type: str, resource_id: int) -> int:
        return len(self._rooms.get((guild_id, resource_type, resource_id), set()))

    async def revoke_user(self, guild_id: int, user_id: int) -> None:
        """Immediately re-check every content socket held by ``user_id`` in
        ``guild_id`` and hard-disconnect those who lost access. Call after a
        guild/initiative membership change, role change, or PAM revoke for the
        user — guild- and initiative-level access is enforced without waiting for
        the bounded loop."""
        await self._recheck(lambda m: m.guild_id == guild_id and m.user.id == user_id)

    async def revoke_user_everywhere(self, user_id: int) -> None:
        """The same, across every guild at once.

        For a change to the account rather than to one membership — a platform
        action has no guild to name, and the account holds sockets in all of
        them. Also for a change to one of its credentials: ending a session,
        signing out, a password change. Each socket is re-checked against its
        own credential, so the ones opened on a credential that still stands
        stay open.
        """
        await self._recheck(lambda m: m.user.id == user_id)

    # ── internals ──────────────────────────────────────────────────────────

    async def _recheck(self, predicate: Callable[[_StreamMember], bool]) -> None:
        async with self._lock:
            targets = [m for m in self._members.values() if predicate(m)]
        if not targets:
            return
        ended = await self._ended_credentials(targets)
        for member in targets:
            if member.websocket in ended:
                await self._disconnect(member, code=WS_CREDENTIAL_ENDED)
            elif not await self._still_authorized(member):
                await self._disconnect(member)

    async def _ended_credentials(self, targets: list[_StreamMember]) -> set[WebSocket]:
        """The sockets among ``targets`` whose credential no longer stands.

        One statement per kind of credential for the whole batch, on the system
        engine, which is where ``auth_sessions`` and ``user_tokens`` are read.
        A session's ``session_id`` is moved to the live row its chain has
        reached, so the next check walks from there.

        Fail closed: a lookup that errors ends every credential it was asked
        about.
        """
        session_ids = {m.session_id for m in targets if m.session_id is not None}
        device_ids = {
            m.device_token_id for m in targets if m.device_token_id is not None
        }
        versioned = {m.user.id for m in targets if m.token_version is not None}
        if not session_ids and not device_ids:
            return set()
        try:
            async with db_session.SystemSessionLocal() as system_session:
                tips = await session_service.live_chain_tips(
                    system_session, session_ids=session_ids
                )
                live_devices = await user_tokens.live_device_token_ids(
                    system_session, token_ids=device_ids
                )
                versions: dict[int, int] = {}
                if versioned:
                    rows = await system_session.exec(
                        select(User.id, User.token_version).where(
                            col(User.id).in_(versioned)
                        )
                    )
                    versions = {user_id: version for user_id, version in rows.all()}
        except Exception:
            logger.exception(
                "stream credential check failed; disconnecting to fail closed"
            )
            return {
                m.websocket
                for m in targets
                if m.session_id is not None or m.device_token_id is not None
            }

        ended: set[WebSocket] = set()
        for member in targets:
            if member.session_id is not None:
                tip = tips.get(member.session_id)
                if tip is None or versions.get(member.user.id) != member.token_version:
                    ended.add(member.websocket)
                    continue
                member.session_id = tip
            if (
                member.device_token_id is not None
                and member.device_token_id not in live_devices
            ):
                ended.add(member.websocket)
        return ended

    async def _still_authorized(self, member: _StreamMember) -> bool:
        """Re-run the FULL join check on a fresh session — every gate, one place.

        Fail closed: any error (including a since-dropped guild schema) drops the
        socket rather than leaving a potentially-unauthorized stream open.
        """
        # The gate below reads the factor flags and the narrowing claims from
        # the auth context, and this runs in whoever asked for the re-check — a
        # request with a session of its own, or the bounded loop. What is there
        # is held and put back on the way out.
        held_amr, held_factor, held_claims = (
            auth_context.session_amr(),
            auth_context.platform_factor(),
            auth_context.satisfied_claims(),
        )
        try:
            async with AsyncSessionLocal() as session:
                # AsyncSessionLocal skips get_session's per-request reset; clear
                # any stale pooled-connection GUCs before establishing context.
                await session.exec(text(CONNECTION_RESET_SQL))
                # Read the account fresh. ``member.user`` is the snapshot taken
                # when the socket joined, so anything about the account itself
                # that has changed since is not in it. Only a live account
                # streams guild content.
                current = await session.get(User, member.user.id)
                if current is None or current.status != UserStatus.active:
                    return False
                # The rest of the joining session's standing, presented the
                # way ``satisfied_providers`` is: the socket's own values, so
                # a community's rule about how its people sign in is answered
                # against the session that opened it.
                auth_context.set_session_amr(member.session_amr)
                auth_context.set_satisfied_claims(member.satisfied_claims)
                try:
                    await establish_guild_access(
                        session,
                        member.user,
                        member.guild_id,
                        satisfied_providers=member.satisfied_providers,
                    )
                except GuildAccessError:
                    return False  # guild access or auth-policy satisfaction revoked
                # Initiative boundary (RLS resource load) + DAC, inside the adapter.
                return await member.authorize(session, member.user)
        except Exception:
            logger.exception(
                "stream re-auth check failed; disconnecting to fail closed"
            )
            return False
        finally:
            auth_context.set_session_amr(held_amr)
            auth_context.set_satisfied_claims(held_claims)
            # The gate inside the access check resolves this for the account
            # being re-checked; put back whoever's it was.
            auth_context.set_platform_factor(held_factor)

    async def _disconnect(
        self,
        member: _StreamMember,
        *,
        code: int = status.WS_1008_POLICY_VIOLATION,
    ) -> None:
        await self.leave(member.websocket)
        try:
            await member.websocket.close(code=code)
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
