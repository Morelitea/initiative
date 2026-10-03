"""Integration tests for the collaboration HTTP endpoints.

Focused on the handover — ``POST`` on a body's ``…/collaborate`` path — which a
leaving tab fires as a ``keepalive`` fetch when its socket is already gone,
carrying the Yjs edits the room never saw. It authenticates as every other
write does: the HttpOnly session cookie on web, the Authorization header on
native. A ``?token=`` in the URL authenticates nothing here.
"""

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from pycrdt import Doc, Text
from sqlalchemy.orm import undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.content_socket import MSG_AUTH
from app.api.v1.tenant_endpoints.collaboration import MSG_AWARENESS
from app.core.security import create_upload_token
from app.core.user_display import handle_of
from app.models.platform.access_grant import AccessGrant
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.tenant.document import Document, DocumentType
from app.models.tenant.wiki import WikiPage
from app.testing import (
    create_document,
    create_user,
    create_wiki,
    create_wiki_page,
    get_auth_headers,
    get_auth_token,
)
from app.core.search import SearchEntityType
from app.services import editor_engine
from app.services.tenant.collaboration import (
    CollaborationManager,
    collaboration_manager,
)
from app.services.tenant.collaborative_resources import resource_for
from app.models.platform.guild import CommunityRole
from app.models.platform.user import UserRole
from app.services import permissions as permissions_service
from app.testing import route_as

CONTENT = {"root": {"children": [{"type": "paragraph"}]}}
WHITEBOARD = {"elements": [], "appState": {}, "files": {}}


def _lexical(words: str) -> dict:
    """A document holding one paragraph of ``words``."""
    return {
        "root": {
            "type": "root",
            "version": 1,
            "children": [
                {
                    "type": "paragraph",
                    "version": 1,
                    "children": [{"type": "text", "text": words, "version": 1}],
                }
            ],
        }
    }


def _words(content: dict) -> str:
    return "".join(
        node.get("text", "")
        for block in content["root"]["children"]
        for node in block.get("children", [])
    )


def _document_url(guild_id: int, document_id: int) -> str:
    return f"/api/v1/c/{guild_id}/collaboration/documents/{document_id}/collaborate"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _typed(text: str, doc: Doc | None = None) -> Doc:
    """A Yjs doc holding ``text``, as a tab's would after typing it."""
    doc = doc or Doc()
    body = doc.get("body", type=Text)
    body += text
    return doc


def _handover(doc: Doc, content: dict | None = CONTENT) -> dict:
    return {
        "update": _b64(doc.get_update()),
        "state_vector": _b64(doc.get_state()),
        "content": content,
    }


def _text_of(yjs_state: bytes) -> str:
    doc = Doc()
    doc.apply_update(yjs_state)
    return str(doc.get("body", type=Text))


async def test_collaboration_guild_admin_gets_full_access(
    session: AsyncSession, acting_user, role_session
) -> None:
    """A guild admin must get full collaboration access to a restricted document
    they hold no grant on and aren't an initiative member of — mirroring the REST
    guild-admin bypass. The collaboration paths resolve access straight through
    the shared DAC engine (``permissions.allows``), which reads the
    active guild-role context that ``establish_guild_access`` records."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    # admin is deliberately NOT a member of this initiative and holds no grant.
    admin = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    doc = await create_document(session, owner.initiative, owner.user)
    # The socket resolves a body through the resource registry, so the test
    # asks the same way the endpoint does: on the request login, routed
    # through the seam as the admin, the row arrives with the level the
    # standing gives — owner, grant or no grant.
    s = await role_session("app_user")
    await route_as(s, user_id=admin.user.id, guild_id=owner.guild.id)
    resolved = await resource_for(SearchEntityType.document.value).load(
        s, doc.id, owner.guild.id
    )
    assert resolved is not None
    assert permissions_service.allows(resolved.body, permissions_service.Action.edit)


async def test_a_handover_merges_into_the_room_and_saves_both_views(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """The edits land in the Yjs state and the tab's rendering in the content
    column, together, for a body the browser renders."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(
        session,
        owner.initiative,
        owner.user,
        document_type=DocumentType.whiteboard,
        content=WHITEBOARD,
    )
    drawn = {**WHITEBOARD, "elements": [{"id": "drawn offline"}]}

    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("written offline"), content=drawn),
        headers=owner.headers,
    )

    assert response.status_code == 204, response.text
    saved = (
        await session.exec(
            select(Document)
            .where(Document.id == doc.id)
            .options(undefer(Document.content), undefer(Document.yjs_state))
        )
    ).one()
    assert saved.content == drawn
    assert saved.yjs_state is not None
    assert _text_of(saved.yjs_state) == "written offline"


async def test_an_editor_body_is_rendered_by_the_server_not_the_tab(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A native document's content is what the server reads its Yjs state
    as, offline edits included; a rendering a tab sends along is not taken."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(
        session, owner.initiative, owner.user, content=_lexical("on the server")
    )
    # A paragraph the tab wrote while its socket was gone, as Lexical writes it.
    offline = Doc()
    offline.apply_update(await editor_engine.bootstrap(_lexical("written offline")))

    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(offline, content=_lexical("from the tab")),
        headers=owner.headers,
    )

    assert response.status_code == 204, response.text
    saved = (
        await session.exec(
            select(Document)
            .where(Document.id == doc.id)
            .options(undefer(Document.content))
        )
    ).one()
    words = _words(saved.content)
    assert "on the server" in words and "written offline" in words
    assert "from the tab" not in words


async def test_an_editor_body_with_no_state_has_it_made_once(
    session: AsyncSession, acting_user, role_session
) -> None:
    """Rooms opening a native document with no Yjs state together make it on
    the server once, from the document's content."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(
        session, owner.initiative, owner.user, content=_lexical("as it was saved")
    )

    async def open_room():
        routed = await role_session("app_user")
        await route_as(routed, user_id=owner.user.id, guild_id=owner.guild.id)
        return await CollaborationManager().get_or_create_room(
            owner.guild.id, SearchEntityType.document.value, doc.id, routed
        )

    first, second = await asyncio.gather(open_room(), open_room())

    saved = (
        await session.exec(
            select(Document)
            .where(Document.id == doc.id)
            .options(undefer(Document.yjs_state))
        )
    ).one()
    assert saved.yjs_state is not None
    assert first.get_state() == second.get_state() == saved.yjs_state
    assert _words(await editor_engine.render(saved.yjs_state)) == "as it was saved"


async def test_a_rendering_missing_the_rooms_edits_is_not_taken(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """The room holds edits the tab never saw: its edits merge in, but its
    rendering describes an older document, so the column keeps what it had."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    elsewhere = _typed("from a peer. ")
    doc = await create_document(
        session,
        owner.initiative,
        owner.user,
        document_type=DocumentType.whiteboard,
        yjs_state=elsewhere.get_update(),
        content=WHITEBOARD,
    )

    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(
            _typed("offline"), content={**WHITEBOARD, "elements": [{"id": "stale"}]}
        ),
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 204, response.text
    saved = (
        await session.exec(
            select(Document)
            .where(Document.id == doc.id)
            .options(undefer(Document.content), undefer(Document.yjs_state))
        )
    ).one()
    assert saved.content == WHITEBOARD
    merged = _text_of(saved.yjs_state or b"")
    assert "from a peer." in merged and "offline" in merged


async def test_a_wiki_page_takes_a_handover_too(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    owner.initiative.wikis_enabled = True
    session.add(owner.initiative)
    await session.commit()
    wiki = await create_wiki(session, owner.initiative, owner.user)
    page = await create_wiki_page(session, wiki, owner.user)

    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/collaboration/wiki-pages/{page.id}/collaborate",
        json=_handover(_typed("a page written offline")),
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 204, response.text
    saved = (await session.exec(select(WikiPage).where(WikiPage.id == page.id))).one()
    assert _text_of(saved.yjs_state or b"") == "a page written offline"


async def test_an_unreadable_update_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json={"update": _b64(b"not yjs"), "state_vector": _b64(b"\x00")},
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_COLLABORATION_UPDATE_INVALID"
    # The room it opened to try is not left behind for the next caller.
    key = (owner.guild.id, SearchEntityType.document.value, doc.id)
    assert key not in collaboration_manager._rooms


async def test_a_refused_handover_leaves_the_next_one_the_saved_document(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A handover that is refused loads the room and takes nothing; the next one
    still merges into what the row holds, not into a room left behind."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(
        session,
        owner.initiative,
        owner.user,
        yjs_state=_typed("from a peer. ").get_update(),
    )
    headers = {"Authorization": f"Bearer {get_auth_token(owner.user)}"}

    refused = await client.post(
        _document_url(owner.guild.id, doc.id),
        json={"update": _b64(b"not yjs"), "state_vector": _b64(b"\x00")},
        headers=headers,
    )
    assert refused.status_code == 400
    # The row changes underneath, as another tab's save would change it.
    doc.yjs_state = _typed("saved since. ").get_update()
    session.add(doc)
    await session.commit()

    taken = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("offline")),
        headers=headers,
    )

    assert taken.status_code == 204, taken.text
    saved = (
        await session.exec(
            select(Document)
            .where(Document.id == doc.id)
            .options(undefer(Document.yjs_state))
        )
    ).one()
    merged = _text_of(saved.yjs_state or b"")
    assert "saved since." in merged and "offline" in merged


async def test_a_token_in_the_query_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """The handover is a write: a ``?token=`` authenticates none, the
    uploads-scoped one included."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    token, _ = create_upload_token(user_id=owner.user.id)

    response = await client.post(
        f"{_document_url(owner.guild.id, doc.id)}?token={token}",
        json=_handover(_typed("x")),
    )

    assert response.status_code == 401


async def test_a_handover_answers_a_community_that_asks_for_a_passkey(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """What the session proved about the person reaches the guild gate here as
    it does on a page: the session opened with a passkey writes, the one
    opened with a password is refused."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    session.add(
        GuildAuthPolicy(
            guild_id=owner.guild.id, policy="required", require_methods=["passkey"]
        )
    )
    await session.commit()

    with_a_password = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers={"Authorization": f"Bearer {get_auth_token(owner.user, amr=['pwd'])}"},
    )
    assert with_a_password.status_code == 401, with_a_password.text

    with_a_passkey = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers={
            "Authorization": (
                f"Bearer {get_auth_token(owner.user, amr=['pwd', 'hwk', 'mfa'])}"
            )
        },
    )
    assert with_a_passkey.status_code == 204, with_a_passkey.text


async def test_a_non_member_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    outsider = await create_user(session)
    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers=get_auth_headers(outsider),
    )

    assert response.status_code == 403


async def _approved_grant(session, *, user, guild, owner, level: str) -> AccessGrant:
    """An approved, currently-live access grant for ``user`` on ``guild``."""
    now = datetime.now(timezone.utc)
    grant = AccessGrant(
        user_id=user.id,
        guild_id=guild.id,
        access_level=level,
        status="approved",
        reason="test",
        requested_duration_minutes=60,
        requested_by_id=user.id,
        approved_by_id=owner.id,
        decided_at=now,
        expires_at=now + timedelta(hours=1),
    )
    session.add(grant)
    await session.commit()
    return grant


async def test_a_break_glass_grantee_can_hand_over(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A platform operator who is not a member but holds a live ``read_write``
    break-glass grant edits existing content for the grant's window."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    grantee = await create_user(session, role=UserRole.operator)
    await _approved_grant(
        session, user=grantee, guild=owner.guild, owner=owner.user, level="read_write"
    )
    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers=get_auth_headers(grantee),
    )

    assert response.status_code == 204, response.text


async def test_a_read_grant_cannot_hand_over(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A read grant reaches the guild but not the write level the handover
    needs."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    grantee = await create_user(session)
    await _approved_grant(
        session, user=grantee, guild=owner.guild, owner=owner.user, level="read"
    )
    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("x")),
        headers=get_auth_headers(grantee),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "DOCUMENT_WRITE_ACCESS_REQUIRED"


async def test_the_roster_names_a_collaborator_as_their_community_does(
    session: AsyncSession, acting_user, socket_client
) -> None:
    """Who is editing reads the same as everywhere else in the community: the
    name set there, the handle where there is none."""
    owner = await acting_user(guild_role=CommunityRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    path = _document_url(owner.guild.id, doc.id)

    def roster_name() -> str:
        with socket_client.websocket_connect(path) as ws:
            auth = {"token": get_auth_token(owner.user)}
            ws.send_bytes(bytes([MSG_AUTH]) + json.dumps(auth).encode())
            while True:
                frame = ws.receive().get("bytes") or b""
                if frame[:1] == bytes([MSG_AWARENESS]):
                    return json.loads(frame[1:])["data"][0]["name"]

    assert roster_name() == handle_of(owner.user)
    owner.membership.display_name = "Quill"
    session.add(owner.membership)
    await session.commit()
    assert roster_name() == "Quill"
