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
    Depends,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.core.auth_context import satisfied_provider_ids
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
from app.core.security import SESSION_COOKIE_NAME
from app.db.session import AsyncSessionLocal, set_rls_context
from app.models.platform.user import User
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
from app.core.tools import Tool
from app.services.tenant import content_references
from app.services.tenant import documents as documents_service
from app.services.tenant.relationships import Endpoint
from app.services import permissions as permissions_service
from app.services.stream_authz import authority as stream_authority
from app.services.platform.ws_auth import authenticate_ws_token
from app.core.user_display import display_name, handle_of

router = APIRouter()
logger = logging.getLogger(__name__)

# Message types for the collaboration protocol
MSG_SYNC_STEP1 = 0  # Client requests current state
MSG_SYNC_STEP2 = 1  # Server sends current state
MSG_UPDATE = 2  # Incremental Yjs update
MSG_AWARENESS = 3  # Join / leave / roster, server to client (JSON)
MSG_AWARENESS_BINARY = 4  # y-protocols awareness (binary, relayed as-is)
MSG_AUTH = 5  # Authentication message (JSON: {token, guild_id})
MSG_CONTENT = 6  # Editor's JSON rendering of the document, for the content column


async def _get_user_from_token(token: str, session) -> Optional[User]:
    """Validate a session JWT or device token and return the user, or None.

    Delegates to the shared ``authenticate_ws_token`` helper so the
    ``token_version`` revocation check stays in lockstep with the HTTP auth
    path and the other realtime WebSocket endpoints (SEC-4).
    """
    return await authenticate_ws_token(token, session)


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


async def _collaborate(
    websocket: WebSocket,
    guild_id: int,
    spec: CollaborativeResource,
    resource_id: int,
    *,
    parent_id: int | None = None,
):
    """
    WebSocket endpoint for collaborative editing of one body.

    Protocol:
    1. Client connects and sends MSG_AUTH with {token} as first message; the
       guild comes from the ``/g/{guild_id}`` path segment
    2. Server validates auth and sends current Yjs state (SYNC_STEP2)
    3. Client sends incremental updates (UPDATE)
    4. Server broadcasts updates to other clients
    5. Awareness messages (AWARENESS) for cursor positions

    Message format (binary):
    - First byte: message type
    - Rest: payload (Yjs update bytes or JSON for awareness)

    Note: This endpoint manages its own database sessions to avoid holding
    connections open for the entire WebSocket lifetime.
    """
    # Must accept WebSocket before we can close it properly
    # If we try to close before accept, the HTTP upgrade never completes
    # and the client sees an abnormal closure (1006)
    await websocket.accept()
    logger.info(
        f"Collaboration: WebSocket accepted for {spec.resource_type} {resource_id}"
    )

    # Wait for authentication message (must be first message)
    try:
        auth_data = await websocket.receive_bytes()
        if len(auth_data) < 2 or auth_data[0] != MSG_AUTH:
            logger.warning(
                f"Collaboration: Expected MSG_AUTH as first message for "
                f"{spec.resource_type} {resource_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Parse auth payload
        try:
            auth_payload = json.loads(auth_data[1:].decode())
            token = auth_payload.get("token")
            if not token:
                # Fall back to session cookie (web sessions after page refresh)
                token = websocket.cookies.get(SESSION_COOKIE_NAME)
            if not token:
                raise ValueError("Missing token")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                f"Collaboration: Invalid auth payload for {spec.resource_type} "
                f"{resource_id}: {e}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except WebSocketDisconnect:
        logger.info(
            f"Collaboration: Client disconnected before auth for "
            f"{spec.resource_type} {resource_id}"
        )
        return

    # Authenticate and check permissions using a short-lived session
    async with AsyncSessionLocal() as session:
        user = await _get_user_from_token(token, session)
        if not user:
            logger.warning(
                f"Collaboration: Auth failed for {spec.resource_type} {resource_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Establish the guild access context through the single entry point —
        # real membership, a live PAM grant, or break-glass — so the document
        # checks below see the *same* context (guild-admin DAC bypass, PAM scope,
        # break-glass elevation, delegation pin) the REST path would. Hand-rolling
        # this here is exactly what let a guild admin be denied on the socket
        # while allowed on the REST read.
        try:
            await establish_guild_access(session, user, guild_id)
        except GuildAccessError:
            logger.warning(
                f"Collaboration: {handle_of(user)} has no access to guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # The body, and the row whose sharing governs it. For a document they
        # are the same row; for a wiki page the governing row is its wiki.
        resolved = await spec.load(session, resource_id, guild_id)
        if resolved is None or not _addresses_the_same_thing(spec, resolved, parent_id):
            logger.warning(
                f"Collaboration: {spec.resource_type} {resource_id} not found "
                f"or not in guild {guild_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        body = resolved.body

        # Per-resource level via the shared DAC engine — guild-admin /
        # break-glass bypass (→ owner), a live PAM grant lifted to its level, or
        # the resource's explicit user/role/all-members grants. The active role +
        # grant context was established above, and establish_guild_access already
        # proved guild reach, so the only open question is this level.
        level = permissions_service.compute_permission(
            permissions_service.DAC_RESOURCES[spec.tool], resolved.governing, user.id
        )
        if level is None:
            logger.warning(
                f"Collaboration: User {handle_of(user)} has no read access to "
                f"{spec.resource_type} {resource_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        # The DAC engine caps the level at "read" while the guild's content is
        # frozen (read_only lifecycle status, recorded by establish_guild_access),
        # so a frozen guild can never hand out a writable socket.
        can_write = level in ("write", "owner")

        # Get or create the document room (needs session for initial load)
        room = await collaboration_manager.get_or_create_room(
            guild_id, spec.resource_type, resource_id, session
        )
        # Held from here until this socket is in the register, so the room is
        # not read as idle and retired in the gap between the two.
        room.hold()

    logger.info(
        f"Collaboration: user {user.id} authenticated for "
        f"{spec.resource_type} {resource_id}"
    )

    collaborator_name = display_name(user)

    # Govern this socket with continuous, every-level re-authorization. A
    # grant / membership / role / PAM change disconnects it — immediately for
    # guild- and initiative-level removal (via revoke_user), within the bounded
    # interval for within-initiative DAC changes. The check re-runs the FULL join
    # (establish_guild_access → load the document under RLS → DAC), so every gate
    # is re-enforced in one place. ``needs_write`` makes a writer who loses write
    # disconnect too (hard-disconnect, no mid-session downgrade), so the stale
    # ``can_write`` below can't outlive the user's actual write access.
    needs_write = can_write

    async def _authorize(check_session, check_user):
        again = await spec.load(check_session, resource_id, guild_id)
        if again is None:
            return False  # initiative removed (RLS hides it) or the row is gone
        current = permissions_service.compute_permission(
            permissions_service.DAC_RESOURCES[spec.tool], again.governing, check_user.id
        )
        if current is None:
            return False  # read access revoked
        # A guild flipping to read_only mid-session caps ``current`` at "read"
        # (the DAC engine reads the lifecycle flag recorded by the re-auth's
        # establish_guild_access), so writer sockets hard-disconnect here and
        # reconnect read-only — same rule as a lost DAC write level.
        return not needs_write or current in ("write", "owner")

    try:
        await stream_authority.join(
            websocket,
            user,
            guild_id=guild_id,
            initiative_id=resolved.initiative_id,
            resource_type=spec.resource_type,
            resource_id=resource_id,
            authorize=_authorize,
            satisfied_providers=satisfied_provider_ids(),
            meta={
                "name": collaborator_name,
                "can_write": can_write,
                "avatar_url": user.avatar_url,
            },
        )
    finally:
        room.release()

    try:
        # Ask what this connection has that the room does not. A client that
        # reconnects holding work the room never saw — because the room was
        # rebuilt from the row while it was away — can only hand it over if it
        # is asked. It answers with SYNC_STEP2, and sends its own SYNC_STEP1
        # for the other direction, so one connect settles both ways.
        await websocket.send_bytes(bytes([MSG_SYNC_STEP1]) + room.state_vector())

        # Send current collaborator list
        collaborators_message = json.dumps(
            {
                "type": "collaborators",
                "data": room_roster(guild_id, spec.resource_type, resource_id),
            }
        ).encode()
        await websocket.send_bytes(bytes([MSG_AWARENESS]) + collaborators_message)

        # Broadcast that a new user joined
        await broadcast_awareness(
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

        # Main message loop
        while True:
            data = await websocket.receive_bytes()
            if len(data) < 1:
                continue

            msg_type = data[0]
            payload = data[1:]

            if msg_type == MSG_SYNC_STEP1:
                # Client requesting sync with their state vector
                # Use state vector to compute diff - only send updates client is missing
                logger.info(
                    f"Collaboration: Received SYNC_STEP1 from {handle_of(user)}, state vector size: {len(payload)}"
                )
                state = room.get_state_diff(payload) if payload else room.get_state()
                sync_message = bytes([MSG_SYNC_STEP2]) + state
                logger.info(
                    f"Collaboration: Sending SYNC_STEP2 to {handle_of(user)}, diff size: {len(state)}"
                )
                await websocket.send_bytes(sync_message)

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
                    # Relayed under MSG_UPDATE whichever it arrived as: to every
                    # other connection this is simply state they do not have.
                    await stream_authority.emit_bytes(
                        guild_id,
                        spec.resource_type,
                        resource_id,
                        bytes([MSG_UPDATE]) + payload,
                        exclude=websocket,
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
                await stream_authority.emit_bytes(
                    guild_id,
                    spec.resource_type,
                    resource_id,
                    bytes([MSG_AWARENESS_BINARY]) + payload,
                    exclude=websocket,
                )

    except WebSocketDisconnect:
        logger.info(
            f"Collaboration: {handle_of(user)} disconnected from "
            f"{spec.resource_type} {resource_id}"
        )
    except Exception as e:
        logger.error(
            f"Collaboration error for {handle_of(user)} on "
            f"{spec.resource_type} {resource_id}: {e}"
        )
    finally:
        # Stop governing this socket (idempotent if the spine already closed it).
        await stream_authority.leave(websocket)

        # Tell the rest of the room only when this was the account's last
        # connection: the others keep a roster of people, and one of somebody's
        # two tabs closing does not take them out of the document.
        if not user_has_connection(guild_id, spec.resource_type, resource_id, user.id):
            await broadcast_awareness(
                guild_id,
                spec.resource_type,
                resource_id,
                {"type": "leave", "user_id": user.id},
                exclude=websocket,
            )

        # Save what this session added. The room is only retired afterwards,
        # and only once nothing is connected to it — another tab of the same
        # account is another connection, and keeps it.
        async with AsyncSessionLocal() as session:
            await set_rls_context(session, user_id=user.id, guild_id=guild_id)
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
    ``/g/{guild_id}`` path — the document being synced was open inside it.

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
    # membership-only check, so a break-glass admin or PAM grantee couldn't sync.
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
        permissions_service.DAC_RESOURCES[Tool.document], document, user.id
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
