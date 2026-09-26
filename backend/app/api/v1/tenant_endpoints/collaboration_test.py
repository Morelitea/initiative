"""Integration tests for the collaboration HTTP endpoints.

Focused on the handover — ``POST`` on a body's ``…/collaborate`` path — which a
leaving tab fires as a ``keepalive`` fetch when its socket is already gone,
carrying the Yjs edits the room never saw. It shares the header-less auth of
``/uploads/*`` and downloads (``UploadUserDep``): the HttpOnly session cookie on
web, a short-lived uploads-scoped ``?token=`` on native. The long-lived session
JWT must never authenticate via the URL (SEC-12).
"""

import base64
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from pycrdt import Doc, Text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.security import create_upload_token
from app.models.platform.access_grant import AccessGrant
from app.models.platform.guild_auth_policy import GuildAuthPolicy
from app.models.tenant.document import Document
from app.models.tenant.wiki import WikiPage
from app.testing import (
    create_document,
    create_user,
    create_wiki,
    create_wiki_page,
    get_auth_token,
)
from app.core.search import SearchEntityType
from app.services.tenant.collaborative_resources import resource_for
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.services import permissions as permissions_service
from app.testing import route_as

CONTENT = {"root": {"children": [{"type": "paragraph"}]}}


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
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    # admin is deliberately NOT a member of this initiative and holds no grant.
    admin = await acting_user(guild_role=GuildRole.admin, guild=owner.guild)
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
    """A short-lived, uploads-scoped ?token= authenticates the handover (the
    credential native WebViews carry in the URL). The edits land in the Yjs
    state and the rendering in the content column, together."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    token, _ = create_upload_token(user_id=owner.user.id)
    response = await client.post(
        f"{_document_url(owner.guild.id, doc.id)}?token={token}",
        json=_handover(_typed("written offline")),
    )

    assert response.status_code == 204, response.text
    session.expire_all()
    saved = (await session.exec(select(Document).where(Document.id == doc.id))).one()
    assert saved.content == CONTENT
    assert saved.yjs_state is not None
    assert _text_of(saved.yjs_state) == "written offline"


async def test_a_rendering_missing_the_rooms_edits_is_not_taken(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """The room holds edits the tab never saw: its edits merge in, but its
    rendering describes an older document, so the column keeps what it had."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    elsewhere = _typed("from a peer. ")
    doc = await create_document(
        session,
        owner.initiative,
        owner.user,
        yjs_state=elsewhere.get_update(),
        content={"root": {"children": []}},
    )

    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json=_handover(_typed("offline")),
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 204, response.text
    session.expire_all()
    saved = (await session.exec(select(Document).where(Document.id == doc.id))).one()
    assert saved.content == {"root": {"children": []}}
    merged = _text_of(saved.yjs_state or b"")
    assert "from a peer." in merged and "offline" in merged


async def test_a_wiki_page_takes_a_handover_too(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    owner.initiative.wikis_enabled = True
    session.add(owner.initiative)
    await session.commit()
    wiki = await create_wiki(session, owner.initiative, owner.user)
    page = await create_wiki_page(session, wiki, owner.user)

    response = await client.post(
        f"/api/v1/c/{owner.guild.id}/collaboration/wikis/{wiki.id}/pages/{page.id}"
        "/collaborate",
        json=_handover(_typed("a page written offline")),
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 204, response.text
    session.expire_all()
    saved = (await session.exec(select(WikiPage).where(WikiPage.id == page.id))).one()
    assert _text_of(saved.yjs_state or b"") == "a page written offline"


async def test_an_unreadable_update_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    response = await client.post(
        _document_url(owner.guild.id, doc.id),
        json={"update": _b64(b"not yjs"), "state_vector": _b64(b"\x00")},
        headers={"Authorization": f"Bearer {get_auth_token(owner.user)}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "DOCUMENT_COLLABORATION_UPDATE_INVALID"


async def test_a_session_jwt_is_refused_in_the_query(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """Only the uploads-scoped token is accepted in ?token=; the session JWT
    is not. SEC-12."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)

    response = await client.post(
        f"{_document_url(owner.guild.id, doc.id)}?token={get_auth_token(owner.user)}",
        json=_handover(_typed("x")),
    )

    assert response.status_code == 401


async def test_a_handover_answers_a_community_that_asks_for_a_passkey(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """What the session proved about the person reaches the guild gate here as
    it does on a page: the session opened with a passkey writes, the one
    opened with a password is refused."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
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
    assert with_a_password.status_code == 403

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
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    outsider = await create_user(session)
    token, _ = create_upload_token(user_id=outsider.id)

    response = await client.post(
        f"{_document_url(owner.guild.id, doc.id)}?token={token}",
        json=_handover(_typed("x")),
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
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    grantee = await create_user(session, role=UserRole.operator)
    await _approved_grant(
        session, user=grantee, guild=owner.guild, owner=owner.user, level="read_write"
    )
    token, _ = create_upload_token(user_id=grantee.id)

    response = await client.post(
        f"{_document_url(owner.guild.id, doc.id)}?token={token}",
        json=_handover(_typed("x")),
    )

    assert response.status_code == 204, response.text


async def test_a_read_grant_cannot_hand_over(
    client: AsyncClient, session: AsyncSession, acting_user
) -> None:
    """A read grant reaches the guild but not the write level the handover
    needs."""
    owner = await acting_user(guild_role=GuildRole.member, initiative=True)
    doc = await create_document(session, owner.initiative, owner.user)
    grantee = await create_user(session)
    await _approved_grant(
        session, user=grantee, guild=owner.guild, owner=owner.user, level="read"
    )
    token, _ = create_upload_token(user_id=grantee.id)

    response = await client.post(
        f"{_document_url(owner.guild.id, doc.id)}?token={token}",
        json=_handover(_typed("x")),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "DOCUMENT_WRITE_ACCESS_REQUIRED"
