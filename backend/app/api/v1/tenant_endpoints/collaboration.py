"""
WebSocket endpoint for real-time document collaboration.

Handles:
- Token-based authentication
- Document permission checks
- Yjs sync protocol
- Awareness (cursor presence)
"""

import json
import logging
from typing import Optional

from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    Request,
    WebSocket,
    WebSocketDisconnect,
)

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    UploadUserDep,
    establish_guild_access,
    get_current_active_user,
    get_guild_membership,
    GuildAccessError,
    GuildContext,
)
from app.core.messages import DocumentMessages
from app.db.cohorts import request_sessionmaker
from app.models.platform.user import User
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
from app.services.tenant import content_references
from app.services.tenant import documents as documents_service
from app.services.tenant.relationships import Endpoint
from app.services import permissions as permissions_service
from app.services.content_sockets import RoomKey, Wire, resource_room, sockets
from app.api.content_socket import admit
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
        return frozenset(
            {resource_room(self.guild_id, self.spec.resource_type, self.resource_id)}
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

        while True:
            data = await websocket.receive_bytes()
            if len(data) < 1:
                continue

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
                    continue
                if not payload:
                    continue

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
                    continue
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

    except WebSocketDisconnect:
        pass
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

        # Save what this session added. The room is only retired afterwards,
        # and only once nothing is connected to it — another tab of the same
        # account is another connection, and keeps it.
        async with request_sessionmaker(guild_id)() as session:
            await establish_guild_access(session, user, guild_id)
            await collaboration_manager.persist_room(
                guild_id, spec.resource_type, resource_id, session
            )
        await collaboration_manager.remove_room(
            guild_id, spec.resource_type, resource_id
        )


@router.get("/documents/{document_id}/collaborators")
async def get_document_collaborators(
    document_id: int,
    session: RLSSessionDep,
    _current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: Annotated[GuildContext, Depends(get_guild_membership)],
) -> list[dict]:
    """Get the list of current collaborators on a document."""
    return room_roster(
        guild_context.guild_id, SearchEntityType.document.value, document_id
    )


@router.post("/documents/{document_id}/sync-content")
async def sync_document_content(
    document_id: int,
    guild_id: int,
    request: Request,
    session: SessionDep,
    user: UploadUserDep,
):
    """
    Sync Lexical content from the frontend to the database.

    Called via a ``keepalive`` fetch on page unload to keep the content column
    in sync with yjs_state. Authenticates with the same header-less scheme as
    ``/uploads/*`` and document downloads (``UploadUserDep``): the HttpOnly
    session cookie on web, a short-lived uploads-scoped ``?token=`` on native —
    so the long-lived session JWT never rides in a URL (SEC-12), unlike the
    earlier ``?token=<session jwt>`` version. The guild comes from the
    ``/c/{guild_id}`` path — the document being synced was open inside it.

    The request body should contain the Lexical serialized state as JSON.
    """
    # Parse the JSON body (the keepalive fetch sends a raw body)
    try:
        content = await request.json()
    except Exception as e:
        logger.warning(f"Sync content: Failed to parse JSON body: {e}")
        return {"status": "error", "message": "Invalid JSON body"}

    # Establish the guild access context through the single entry point (same as
    # the REST path and the collaboration socket). The path is only a selector;
    # this validates real membership / a live PAM grant / break-glass and applies
    # the full RLS + role + grant context. Previously this endpoint did a
    # membership-only check, so a break-glass or PAM grantee couldn't sync.
    try:
        await establish_guild_access(session, user, guild_id)
    except GuildAccessError:
        logger.warning(
            f"Sync content: user {user.id} has no access to guild {guild_id}"
        )
        return {"status": "error", "message": "No guild access"}

    # Get document and check write permission
    spec = resource_for(SearchEntityType.document.value)
    resolved = await spec.load(session, document_id, guild_id)
    document = resolved.body if resolved else None
    if not document:
        logger.warning(f"Sync content: Document {document_id} not found")
        return {"status": "error", "message": "Document not found"}

    # Write level via the shared DAC engine (guild-admin / break-glass / PAM /
    # explicit grants), against the context establish_guild_access set above.
    level = permissions_service.compute_permission(
        document, context=require_guild_context(session)
    )
    if level not in ("write", "owner"):
        logger.warning(
            f"Sync content: User {handle_of(user)} has no write access to document {document_id}"
        )
        return {"status": "error", "message": "No write access"}

    # A live room owns both views of the document and writes them together,
    # so a snapshot arriving beside it is not applied here: this beacon can
    # come from a tab that has been disconnected for some time, and its idea
    # of the content is that old. With no room, this is the only writer.
    if collaboration_manager.has_active_collaborators(
        guild_id, spec.resource_type, document_id
    ):
        # The room owns the content column while it is live and takes its
        # rendering from the connection that made it. This request carries no
        # connection, so it is not applied.
        logger.info(
            f"Sync content: document {document_id} is live; leaving the "
            "content column to its room"
        )
        return {
            "status": "error",
            "message": DocumentMessages.LIVE_SESSION_OWNS_CONTENT,
        }

    # Update the content column
    try:
        # Record what the new body points at, and repair any link whose target
        # has since been deleted.
        fixed_content = await content_references.sync_for_entity(
            session,
            Endpoint(SearchEntityType.document, document_id),
            body=content,
            author_id=user.id,
            fix_content=True,
        )
        document.content = fixed_content if fixed_content else content
        session.add(document)
        await session.commit()
        logger.info(
            f"Sync content: Updated content for document {document_id} by {handle_of(user)}"
        )
        return {"status": "ok"}
    except Exception as e:
        # Log the full error server-side; return a generic message so internal
        # detail (e.g. DB error text) isn't exposed to the caller.
        logger.error(f"Sync content: Failed to update document {document_id}: {e}")
        await session.rollback()
        return {"status": "error", "message": "Failed to sync content"}
