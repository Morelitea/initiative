"""
Live editing of a collaborative body (a document, a wiki page).

The socket carries the Yjs sync protocol, updates and awareness; entry and
continuous re-authorization are ``app.api.content_socket``'s. The POST beside
each socket hands over edits a tab made while its socket was closed.
"""

import json
import logging
from typing import Optional


from fastapi import (
    APIRouter,
    HTTPException,
    WebSocket,
    status,
)

from app.api.deps import (
    SessionDep,
    UploadUserDep,
    establish_guild_access,
    GuildAccessError,
    raise_for_guild_access,
)
from app.core.messages import DocumentMessages
from app.models.platform.user import User
from app.schemas.tenant.collaboration import CollaborationHandover
from sqlmodel.ext.asyncio.session import AsyncSession
from app.services.tenant.collaboration import (
    broadcast_awareness,
    collaboration_manager,
    room_roster,
    user_has_connection,
)
from app.services.tenant.collaborative_resources import (
    CollaborativeResource,
    Collaborating,
    ContentFrameError,
    resource_for,
)
from app.core.search import SearchEntityType
from app.db.session import require_guild_context
from app.services.tenant import documents as documents_service
from app.services import permissions as permissions_service
from app.services.content_sockets import RoomKey, Wire, resource_room, sockets
from app.api.content_socket import admit, hold_open
from app.api import resource_access
from app.core.request_audit import record_privileged_edit
from app.core.user_display import display_name, handle_of

router = APIRouter()
logger = logging.getLogger(__name__)

# Message types for the collaboration protocol
MSG_SYNC_STEP1 = 0  # Client requests current state
MSG_SYNC_STEP2 = 1  # Server sends current state
MSG_UPDATE = 2  # Incremental Yjs update
MSG_AWARENESS = 3  # Join / leave / roster, server to client (JSON)
MSG_AWARENESS_BINARY = 4  # y-protocols awareness (binary, relayed as-is)
MSG_CONTENT = 6  # Editor's JSON rendering of the document, for the content column


def _addresses_the_same_thing(
    spec: CollaborativeResource, resolved: Collaborating, parent_id: int | None
) -> bool:
    """Whether the parent the URL named is the one the row actually has.

    Only a nested resource has one. The authorization never reads the path
    segment — it reads the row — so a mismatch is simply refused rather than
    quietly serving the right room under the wrong address.
    """
    if parent_id is None:
        return True
    return getattr(resolved.body, "wiki_id", None) == parent_id


@router.websocket("/documents/{document_id}/collaborate")
async def websocket_collaborate_document(
    websocket: WebSocket,
    guild_id: int,
    document_id: int,
):
    """Live editing of a document's body."""
    await _collaborate(
        websocket, guild_id, resource_for(SearchEntityType.document.value), document_id
    )


@router.websocket("/wikis/{wiki_id}/pages/{page_id}/collaborate")
async def websocket_collaborate_wiki_page(
    websocket: WebSocket,
    guild_id: int,
    wiki_id: int,
    page_id: int,
):
    """Live editing of a wiki page's body.

    ``wiki_id`` is in the path because a page is addressed through its wiki
    everywhere else, and a socket that named the page alone would be the one
    place it is not. The page's own row names the wiki that governs it, so the
    authorization does not read the path segment — a mismatched one is refused
    below rather than believed.
    """
    await _collaborate(
        websocket,
        guild_id,
        resource_for(SearchEntityType.wiki_page.value),
        page_id,
        parent_id=wiki_id,
    )


class _Editing:
    """Who may be in one body's room, asked at join and at every re-check.

    The body and the row whose sharing governs it are loaded under RLS (the
    initiative boundary), then ``resource_access.authorize`` asks what every
    REST read asks: the tool's switch on its initiative, and the sharing. The
    write level found at join is kept, and a writer who has lost it is closed
    rather than quietly downgraded — they reconnect as the reader they now are.
    A community turning read-only caps the level the same way.
    """

    def __init__(
        self,
        guild_id: int,
        spec: CollaborativeResource,
        resource_id: int,
        parent_id: int | None,
    ) -> None:
        self.guild_id = guild_id
        self.spec = spec
        self.resource_id = resource_id
        self.parent_id = parent_id
        self.resolved: Collaborating | None = None
        self.can_write: bool | None = None

    async def __call__(
        self, session: AsyncSession, user: User
    ) -> Optional[frozenset[RoomKey]]:
        resolved = await self.spec.load(session, self.resource_id, self.guild_id)
        if resolved is None or not _addresses_the_same_thing(
            self.spec, resolved, self.parent_id
        ):
            return None
        context = require_guild_context(session)
        try:
            resource_access.authorize(
                self.spec.tool, resolved.governing, user, context=context
            )
        except HTTPException:
            return None
        level = permissions_service.compute_permission(
            resolved.governing, context=context
        )
        writes = level in ("write", "owner")
        if self.can_write is None:
            self.resolved = resolved
            self.can_write = writes
        elif self.can_write and not writes:
            return None
        # The body's room, and the room of the row whose sharing governs it —
        # the same room for a document, the wiki's for a page — so a change
        # to that sharing re-checks this socket at once.
        return frozenset(
            {
                resource_room(self.guild_id, self.spec.resource_type, self.resource_id),
                resource_room(
                    self.guild_id, self.spec.tool.value, resolved.governing.id
                ),
            }
        )


async def _collaborate(
    websocket: WebSocket,
    guild_id: int,
    spec: CollaborativeResource,
    resource_id: int,
    *,
    parent_id: int | None = None,
):
    """Live editing of one body over Yjs.

    Entry is ``app.api.content_socket.admit``: the first frame is ``MSG_AUTH``
    with ``{token}``, and the guild comes from the ``/c/{guild_id}`` path. Then:
    the server asks for what the client has (``SYNC_STEP1``) and sends the
    roster; the client answers and sends its own ``SYNC_STEP1``; after that,
    ``UPDATE`` frames are applied and relayed, and binary awareness is relayed
    as-is. Each frame is one type byte and its payload.

    Database sessions are opened only for the join and the final write, never
    held for the socket's life.
    """
    room_key = resource_room(guild_id, spec.resource_type, resource_id)
    editing = _Editing(guild_id, spec, resource_id, parent_id)
    room = None
    # Filled before the socket is registered, so a roster read in between
    # never shows this connection without its name.
    meta: dict = {}

    async def open_room(session: AsyncSession, user: User) -> None:
        nonlocal room
        meta.update(
            {
                "name": display_name(user),
                "can_write": bool(editing.can_write),
                "avatar_url": user.avatar_url,
            }
        )
        room = await collaboration_manager.get_or_create_room(
            guild_id, spec.resource_type, resource_id, session
        )
        # Held until the socket is registered, so the room is not read as idle
        # and retired in the gap between the two.
        room.hold()

    try:
        sub = await admit(
            websocket,
            guild_id,
            wire=Wire.bytes,
            authorize=editing,
            prepare=open_room,
            meta=meta,
        )
    finally:
        if room is not None:
            room.release()
    if sub is None or room is None or editing.resolved is None:
        return

    user = sub.user
    can_write = bool(editing.can_write)
    body = editing.resolved.body
    collaborator_name = meta["name"]
    # One line per session says they edited it; the rest is keystrokes.
    edit_recorded = False

    try:
        # Ask what this connection has that the room does not. A client that
        # reconnects holding work the room never saw — because the room was
        # rebuilt from the row while it was away — can only hand it over if it
        # is asked. It answers with SYNC_STEP2, and sends its own SYNC_STEP1
        # for the other direction, so one connect settles both ways.
        sub.send_bytes(bytes([MSG_SYNC_STEP1]) + room.state_vector())
        sub.send_bytes(
            bytes([MSG_AWARENESS])
            + json.dumps(
                {
                    "type": "collaborators",
                    "data": room_roster(guild_id, spec.resource_type, resource_id),
                }
            ).encode()
        )
        broadcast_awareness(
            guild_id,
            spec.resource_type,
            resource_id,
            {
                "type": "join",
                "user": {
                    "user_id": user.id,
                    "name": collaborator_name,
                    "avatar_url": user.avatar_url,
                },
            },
            exclude=websocket,
        )

        def on_bytes(data: bytes) -> None:
            nonlocal edit_recorded
            msg_type = data[0]
            payload = data[1:]

            if msg_type == MSG_SYNC_STEP1:
                # The client's state vector: send only what it is missing.
                state = room.get_state_diff(payload) if payload else room.get_state()
                sub.send_bytes(bytes([MSG_SYNC_STEP2]) + state)

            elif msg_type in (MSG_UPDATE, MSG_SYNC_STEP2):
                # An edit, or the answer to the room's opening SYNC_STEP1 —
                # both are Yjs updates and both are writes, so both need the
                # write level. A reader answering the handshake is still a
                # reader.
                if not can_write:
                    logger.warning(
                        f"Collaboration: Read-only user {handle_of(user)} tried to send update"
                    )
                    return
                if not payload:
                    return

                try:
                    room.apply_update(payload, connection=websocket)
                    if msg_type == MSG_UPDATE and not edit_recorded:
                        # Once per session, and only for an update: a
                        # SYNC_STEP2 is the client answering the room's
                        # opening handshake, which is not somebody typing.
                        edit_recorded = record_privileged_edit(
                            guild_id=guild_id,
                            resource_type=spec.resource_type,
                            resource_id=resource_id,
                            actor_user_id=user.id,
                        )
                    # Relayed under MSG_UPDATE whichever it arrived as: to every
                    # other connection this is simply state they do not have.
                    sockets.emit_bytes(
                        room_key, bytes([MSG_UPDATE]) + payload, exclude=websocket
                    )
                except Exception as e:
                    logger.warning(f"Failed to apply Yjs update: {e}")

            elif msg_type == MSG_CONTENT:
                # The editor's JSON rendering of what it just wrote. Held on
                # the room and written alongside the Yjs state, so the two
                # views of the document are always saved from one moment.
                if not can_write:
                    return
                try:
                    room.offer_content(
                        spec.normalize(body, json.loads(payload.decode())),
                        connection=websocket,
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.warning(
                        f"Collaboration: unreadable content frame from {handle_of(user)}"
                    )
                except (
                    documents_service.DocumentContentError,
                    ContentFrameError,
                ) as exc:
                    logger.warning(
                        f"Collaboration: rejected content frame from "
                        f"{handle_of(user)}: {exc.code}"
                    )

            elif msg_type == MSG_AWARENESS_BINARY:
                # y-protocols awareness update - relay as-is to other clients
                sockets.emit_bytes(
                    room_key, bytes([MSG_AWARENESS_BINARY]) + payload, exclude=websocket
                )

        await hold_open(sub, on_bytes=on_bytes)
    except Exception as e:
        logger.error(
            f"Collaboration error for {handle_of(user)} on "
            f"{spec.resource_type} {resource_id}: {e}"
        )
    finally:
        # Idempotent if a re-check already closed it.
        sockets.leave(websocket)

        # Tell the rest of the room only when this was the account's last
        # connection: the others keep a roster of people, and one of somebody's
        # two tabs closing does not take them out of the document.
        if not user_has_connection(guild_id, spec.resource_type, resource_id, user.id):
            broadcast_awareness(
                guild_id,
                spec.resource_type,
                resource_id,
                {"type": "leave", "user_id": user.id},
                exclude=websocket,
            )

        # Save what this session added and retire the room, once nothing is
        # connected to it — another tab of the same account is another
        # connection, and keeps it.
        await collaboration_manager.leave(guild_id, spec.resource_type, resource_id)


@router.post(
    "/documents/{document_id}/collaborate", status_code=status.HTTP_204_NO_CONTENT
)
async def hand_over_document_edits(
    guild_id: int,
    document_id: int,
    handover: CollaborationHandover,
    session: SessionDep,
    user: UploadUserDep,
) -> None:
    """Merge edits a tab made while its socket was closed into the document."""
    await _hand_over(
        session,
        user,
        guild_id,
        resource_for(SearchEntityType.document.value),
        document_id,
        handover,
    )


@router.post(
    "/wikis/{wiki_id}/pages/{page_id}/collaborate",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def hand_over_wiki_page_edits(
    guild_id: int,
    wiki_id: int,
    page_id: int,
    handover: CollaborationHandover,
    session: SessionDep,
    user: UploadUserDep,
) -> None:
    """Merge edits a tab made while its socket was closed into the page."""
    await _hand_over(
        session,
        user,
        guild_id,
        resource_for(SearchEntityType.wiki_page.value),
        page_id,
        handover,
        parent_id=wiki_id,
    )


async def _hand_over(
    session: AsyncSession,
    user: User,
    guild_id: int,
    spec: CollaborativeResource,
    resource_id: int,
    handover: CollaborationHandover,
    *,
    parent_id: int | None = None,
) -> None:
    """Hand a leaving tab's unsent edits to the body's room.

    Called as a page unloads with its socket already gone, so what the tab did
    offline is not lost with it. The edits go through the room — merged into
    whatever the room holds, live or loaded for the purpose — and are saved the
    way the room always saves, both views together. The tab's rendering is
    taken only when the tab had everything the merged room has; otherwise it
    describes an older document, and the room keeps the rendering it had.

    Authenticates the header-less way (session cookie on web, a short-lived
    uploads-scoped ``?token=`` on native), since a keepalive request carries no
    header, and is admitted exactly as the socket is, at the write level.
    """
    try:
        await establish_guild_access(session, user, guild_id)
    except GuildAccessError as exc:
        raise_for_guild_access(exc)
    editing = _Editing(guild_id, spec, resource_id, parent_id)
    if not await editing(session, user) or editing.resolved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=spec.tool.not_found_code
        )
    if not editing.can_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=spec.tool.write_required_code
        )

    room = await collaboration_manager.get_or_create_room(
        guild_id, spec.resource_type, resource_id, session
    )
    room.hold()
    try:
        tab = object()
        try:
            room.apply_update(handover.update, connection=tab)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=DocumentMessages.COLLABORATION_UPDATE_INVALID,
            ) from None
        if handover.content is not None and room.known_to(handover.state_vector):
            try:
                room.offer_content(
                    spec.normalize(editing.resolved.body, handover.content),
                    connection=tab,
                )
            except (documents_service.DocumentContentError, ContentFrameError):
                pass
        sockets.emit_bytes(
            resource_room(guild_id, spec.resource_type, resource_id),
            bytes([MSG_UPDATE]) + handover.update,
        )
        record_privileged_edit(
            guild_id=guild_id,
            resource_type=spec.resource_type,
            resource_id=resource_id,
            actor_user_id=user.id,
        )
    finally:
        room.release()
    if room.is_empty():
        await collaboration_manager.leave(guild_id, spec.resource_type, resource_id)
