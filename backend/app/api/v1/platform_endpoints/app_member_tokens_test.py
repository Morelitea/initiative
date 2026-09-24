"""An installed app asking to act as a member, the member answering, and the
member token that follows.

An app asks on its installation token (``POST /app-platform/consent-requests``)
for one purpose; the member is notified and answers on their consent screen
(``/g/{guild_id}/apps/{app_id}/consents``); the app then presents a JWT-bearer
assertion at the token endpoint and is issued a member token only while that
answer stands. The token's reach is the install standing's member branch
(``app/db/member_standing_test.py``); here the probe route reads through it.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from fastapi import APIRouter, Depends
from httpx import AsyncClient
from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.actor_route import ActorRoute
from app.api.deps import ActorContext, ActorSessionDep, app_scope
from app.core.app_access_token import (
    InstallAccessToken,
    seal_install_token,
    unseal_access_token,
)
from app.core.messages import AppMessages, AuthMessages, GuildAppMessages
from app.db.guild_standing import InstallContext
from app.main import app
from app.models.platform.guild import GuildRole
from app.models.platform.notification import Notification, NotificationType
from app.models.tenant.document import Document
from app.models.tenant.initiative import InitiativeMember
from app.services.marketplace import app_oauth
from app.services.marketplace.app_refs import ensure_app_guild_ref, ensure_app_ref
from app.testing import create_document, route_session_to_guild
from app.testing.app_clients import (
    CLIENT,
    InstalledApp,
    install_app,
    mint_client_assertion,
)

CONSENT_URL = "/api/v1/app-platform/consent-requests"
TOKEN_URL = "/api/v1/app-platform/oauth/token"
JWT_BEARER = "urn:ietf:params:oauth:grant-type:jwt-bearer"

_PROBE_PATH = "/api/v1/g/{guild_id}/member-token-probe/documents"
_read_documents = app_scope("documents:read")
_probe = APIRouter(route_class=ActorRoute)


@_probe.get(_PROBE_PATH)
async def _probe_documents(
    actor: Annotated[ActorContext, Depends(_read_documents)],
    session: ActorSessionDep,
) -> dict[str, Any]:
    names = sorted((await session.exec(select(Document.name))).all())
    member = actor.member_user_id if isinstance(actor, InstallContext) else None
    return {"member": member, "documents": names}


@pytest.fixture(autouse=True)
def _mounted():
    routes = list(_probe.routes)
    app.router.routes[0:0] = routes
    try:
        yield
    finally:
        for route in routes:
            app.router.routes.remove(route)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _installation_token(installed: InstalledApp, **overrides) -> str:
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=installed.app.id,
        client_id=CLIENT,
        scopes=frozenset(overrides.pop("scopes", ["documents:read"])),
        initiative_id=overrides.pop("initiative_id", None),
        **overrides,
    )
    return token


async def _member(acting_user, installed: InstalledApp):
    return await acting_user(
        guild_role=GuildRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )


async def _ref(installed: InstalledApp, user_id: int) -> str:
    return await ensure_app_ref(
        guild_id=installed.guild.id, app_install_id=installed.app.id, user_id=user_id
    )


async def _ask(client: AsyncClient, installed: InstalledApp, **body):
    token = body.pop("token", None) or _installation_token(installed)
    body.setdefault("label", "Comment on the linked issue as you")
    body.setdefault("access", "read_write")
    return await client.post(CONSENT_URL, json=body, headers=_bearer(token))


async def _grant_token(
    client: AsyncClient,
    installed: InstalledApp,
    member_ref: str,
    *,
    purpose: str | None = "node-1",
    **form,
):
    extra: dict[str, Any] = {
        "installation": await ensure_app_guild_ref(
            guild_id=installed.guild.id, app_install_id=installed.app.id
        )
    }
    if purpose is not None:
        extra["purpose"] = purpose
    assertion = mint_client_assertion(
        audience=app_oauth.token_endpoint_url(), subject=member_ref, extra=extra
    )
    return await client.post(
        TOKEN_URL,
        data={"grant_type": JWT_BEARER, "assertion": assertion, **form},
    )


async def _answer(client, member, installed, consent_id: int, access: str):
    return await client.put(
        member.g(f"/apps/{installed.app.id}/consents/{consent_id}"),
        headers=member.headers,
        json={"access": access},
    )


async def _consent_id(client, member, installed) -> int:
    listed = await client.get(
        member.g(f"/apps/{installed.app.id}/consents"), headers=member.headers
    )
    assert listed.status_code == 200, listed.text
    (row,) = listed.json()
    return row["id"]


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_request_notifies_the_member_once_and_repeats_as_it_stands(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:write"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    first = await _ask(client, installed, member=member_ref, purpose="node-1")
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["member"] == member_ref
    assert body["purpose"] == "node-1"
    assert body["status"] == "pending"
    assert body["requested_access"] == "read_write"
    assert body["granted_access"] is None

    again = await _ask(
        client, installed, member=member_ref, purpose="node-1", access="read"
    )
    assert again.status_code == 200, again.text
    assert again.json()["requested_access"] == "read_write"
    assert again.json()["requested_at"] == body["requested_at"]

    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.user.id,
                Notification.type == NotificationType.app_consent_requested,
            )
        )
    ).all()
    assert len(notices) == 1
    assert notices[0].guild_id == installed.guild.id
    assert notices[0].data["app_id"] == installed.app.id
    assert notices[0].data["target_path"] == f"/?app={installed.app.id}"

    # Another purpose is another request.
    other = await _ask(client, installed, member=member_ref, purpose="node-2")
    assert other.status_code == 201, other.text


@pytest.mark.integration
async def test_a_request_names_a_member_by_this_install_s_reference(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    elsewhere = await ensure_app_ref(
        guild_id=installed.guild.id,
        app_install_id=installed.app.id + 1000,
        user_id=member.user.id,
    )

    response = await _ask(client, installed, member=elsewhere)

    assert response.status_code == 422
    assert response.json()["detail"] == AppMessages.REFERENCE_UNKNOWN


@pytest.mark.integration
async def test_a_request_is_bound_only_where_the_install_and_token_reach(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    unplaced = await _ask(
        client, installed, member=member_ref, initiative_id=installed.unplaced.id
    )
    assert unplaced.status_code == 422
    assert unplaced.json()["detail"] == AppMessages.CONSENT_INITIATIVE_NOT_PLACED

    narrowed = _installation_token(installed, initiative_id=installed.placed.id)
    beyond = await _ask(client, installed, member=member_ref, token=narrowed)
    assert beyond.status_code == 403
    assert beyond.json()["detail"] == AppMessages.CONSENT_OUTSIDE_TOKEN

    within = await _ask(
        client,
        installed,
        member=member_ref,
        token=narrowed,
        initiative_id=installed.placed.id,
    )
    assert within.status_code == 201, within.text


@pytest.mark.integration
async def test_a_member_token_cannot_ask(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    token = _installation_token(installed, user_id=member.user.id, purpose="node-1")

    response = await _ask(client, installed, member=member_ref, token=token)

    assert response.status_code == 401
    assert response.json()["detail"] == AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


# ---------------------------------------------------------------------------
# The member's answer
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_member_answers_and_nobody_else_sees_it(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    other = await _member(acting_user, installed)
    await _ask(
        client,
        installed,
        member=await _ref(installed, member.user.id),
        purpose="node-1",
        access="read",
    )
    consent_id = await _consent_id(client, member, installed)

    theirs = await client.get(
        other.g(f"/apps/{installed.app.id}/consents"), headers=other.headers
    )
    assert theirs.json() == []
    not_theirs = await _answer(client, other, installed, consent_id, "read")
    assert not_theirs.status_code == 404
    assert not_theirs.json()["detail"] == GuildAppMessages.CONSENT_NOT_FOUND

    more = await _answer(client, member, installed, consent_id, "read_write")
    assert more.status_code == 400
    assert more.json()["detail"] == GuildAppMessages.CONSENT_EXCEEDS_REQUEST

    granted = await _answer(client, member, installed, consent_id, "read")
    assert granted.status_code == 200, granted.text
    assert granted.json()["status"] == "granted"
    assert granted.json()["granted_access"] == "read"

    detail = await client.get(
        member.g(f"/apps/{installed.app.id}"), headers=member.headers
    )
    assert [c["status"] for c in detail.json()["consents"]] == ["granted"]

    withdrawn = await client.delete(
        member.g(f"/apps/{installed.app.id}/consents/{consent_id}"),
        headers=member.headers,
    )
    assert withdrawn.status_code == 204
    listed = await client.get(
        member.g(f"/apps/{installed.app.id}/consents"), headers=member.headers
    )
    assert listed.json()[0]["status"] == "revoked"


@pytest.mark.integration
async def test_an_api_key_cannot_answer(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    from app.services.platform import api_keys as api_keys_service

    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    await _ask(client, installed, member=await _ref(installed, member.user.id))
    consent_id = await _consent_id(client, member, installed)
    secret, _row = await api_keys_service.create_api_key(
        session, user=member.user, name="script"
    )
    await session.commit()

    response = await client.put(
        member.g(f"/apps/{installed.app.id}/consents/{consent_id}"),
        headers={"Authorization": f"Bearer {secret}"},
        json={"access": "read"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "SESSION_REQUIRED"


@pytest.mark.integration
async def test_the_seat_revokes_every_answer_at_once(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await _ask(client, installed, member=member_ref, purpose="node-1", access="read")
    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read")
    assert (await _grant_token(client, installed, member_ref)).status_code == 200

    stopped = await client.post(
        installed.seat.g(f"/apps/{installed.app.id}/delegations/revoke-all"),
        headers=installed.seat.headers,
    )
    assert stopped.status_code == 204, stopped.text

    response = await _grant_token(client, installed, member_ref)
    assert response.status_code == 400
    assert response.json()["error"] == "consent_required"


# ---------------------------------------------------------------------------
# The member token
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_a_member_token_waits_for_the_answer(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:write"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await create_document(session, installed.placed, member.user, name="Theirs")

    never_asked = await _grant_token(client, installed, member_ref)
    assert never_asked.status_code == 400
    assert never_asked.json()["error"] == "consent_required"

    await _ask(client, installed, member=member_ref, purpose="node-1")
    unanswered = await _grant_token(client, installed, member_ref)
    assert unanswered.json()["error"] == "consent_required"

    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read")

    # Another purpose, and app-wide, are still unanswered.
    other = await _grant_token(client, installed, member_ref, purpose="node-2")
    assert other.json()["error"] == "consent_required"
    app_wide = await _grant_token(client, installed, member_ref, purpose=None)
    assert app_wide.json()["error"] == "consent_required"

    issued = await _grant_token(client, installed, member_ref)
    assert issued.status_code == 200, issued.text
    # Read was allowed, so the write scope is issued as read.
    assert issued.json()["scope"] == "documents:read"
    token = unseal_access_token(issued.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert (token.user_id, token.purpose) == (member.user.id, "node-1")

    read = await client.get(
        _PROBE_PATH.format(guild_id=installed.guild.id),
        headers=_bearer(issued.json()["access_token"]),
    )
    assert read.status_code == 200, read.text
    assert read.json() == {"member": member.user.id, "documents": ["Theirs"]}


@pytest.mark.integration
async def test_a_consent_bound_to_an_initiative_issues_only_narrowed_tokens(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await _ask(
        client,
        installed,
        member=member_ref,
        purpose="node-1",
        initiative_id=installed.placed.id,
    )
    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read_write")

    unnarrowed = await _grant_token(client, installed, member_ref)
    assert unnarrowed.status_code == 400
    assert unnarrowed.json()["error"] == "invalid_target"

    narrowed = await _grant_token(
        client,
        installed,
        member_ref,
        resource=f"urn:initiative:initiative:{installed.placed.id}",
    )
    assert narrowed.status_code == 200, narrowed.text
    token = unseal_access_token(narrowed.json()["access_token"])
    assert isinstance(token, InstallAccessToken)
    assert token.initiative_id == installed.placed.id


@pytest.mark.integration
async def test_leaving_the_initiative_or_revoking_stops_the_member_token(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)
    await create_document(session, installed.placed, member.user, name="Theirs")
    await _ask(
        client,
        installed,
        member=member_ref,
        purpose="node-1",
        initiative_id=installed.placed.id,
    )
    consent_id = await _consent_id(client, member, installed)
    await _answer(client, member, installed, consent_id, "read")
    resource = f"urn:initiative:initiative:{installed.placed.id}"
    issued = await _grant_token(client, installed, member_ref, resource=resource)
    token = issued.json()["access_token"]
    url = _PROBE_PATH.format(guild_id=installed.guild.id)

    assert (await client.get(url, headers=_bearer(token))).json()["documents"] == [
        "Theirs"
    ]

    await route_session_to_guild(session, installed.guild.id)
    await session.exec(
        delete(InitiativeMember).where(
            InitiativeMember.initiative_id == installed.placed.id,  # type: ignore[arg-type]
            InitiativeMember.user_id == member.user.id,  # type: ignore[arg-type]
        )
    )
    await session.commit()

    after_leaving = await client.get(url, headers=_bearer(token))
    assert after_leaving.status_code == 200
    assert after_leaving.json()["documents"] == []
    regrant = await _grant_token(client, installed, member_ref, resource=resource)
    assert regrant.json()["error"] == "consent_required"

    await client.delete(
        member.g(f"/apps/{installed.app.id}/consents/{consent_id}"),
        headers=member.headers,
    )
    after_revoking = await client.get(url, headers=_bearer(token))
    assert after_revoking.status_code == 401


@pytest.mark.integration
async def test_the_member_grant_is_its_own_client_authentication(
    client: AsyncClient, session: AsyncSession, acting_user, role_session
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    beside = await _grant_token(
        client,
        installed,
        member_ref,
        client_assertion_type=app_oauth.ASSERTION_TYPE,
        client_assertion=mint_client_assertion(audience=app_oauth.token_endpoint_url()),
    )
    assert beside.status_code == 400
    assert beside.json()["error"] == "invalid_request"

    unknown = await _grant_token(client, installed, "app_unknown_member")
    assert unknown.status_code == 400
    assert unknown.json()["error"] == "invalid_grant"

    no_installation = await client.post(
        TOKEN_URL,
        data={
            "grant_type": JWT_BEARER,
            "assertion": mint_client_assertion(
                audience=app_oauth.token_endpoint_url(), subject=member_ref
            ),
        },
    )
    assert no_installation.status_code == 400
    assert no_installation.json()["error"] == "invalid_grant"


# ---------------------------------------------------------------------------
# How often an app may ask
# ---------------------------------------------------------------------------


@pytest.fixture
def limits_on(client, monkeypatch):
    """The limiter on, with no global default in the way. Takes ``client``,
    whose setup switches the limiter off."""
    from app.core.rate_limit import limiter

    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(limiter, "_default_limits", [])
    limiter.reset()
    yield
    limiter.reset()


@pytest.mark.integration
async def test_new_requests_of_one_member_are_limited_and_repeats_are_not(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, limits_on
):
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    for n in range(5):
        made = await _ask(client, installed, member=member_ref, purpose=f"node-{n}")
        assert made.status_code == 201, made.text

    sixth = await _ask(client, installed, member=member_ref, purpose="node-5")
    assert sixth.status_code == 429
    assert sixth.json()["detail"] == AppMessages.CONSENT_RATE_LIMITED

    repeat = await _ask(client, installed, member=member_ref, purpose="node-0")
    assert repeat.status_code == 200, repeat.text

    # Another member has an allowance of their own.
    other = await _member(acting_user, installed)
    fresh = await _ask(
        client,
        installed,
        member=await _ref(installed, other.user.id),
        purpose="node-5",
    )
    assert fresh.status_code == 201, fresh.text

    notices = (
        await session.exec(
            select(Notification).where(
                Notification.user_id == member.user.id,
                Notification.type == NotificationType.app_consent_requested,
            )
        )
    ).all()
    assert len(notices) == 5


@pytest.mark.integration
async def test_an_install_is_limited_however_it_asks(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    limits_on,
    monkeypatch,
):
    from limits import parse

    from app.api.v1.platform_endpoints import app_consent_requests

    monkeypatch.setattr(
        app_consent_requests, "CONSENT_REQUESTS_PER_INSTALL", parse("3/minute")
    )
    installed = await install_app(
        session, acting_user, role_session, granted=["documents:read"]
    )
    member = await _member(acting_user, installed)
    member_ref = await _ref(installed, member.user.id)

    for _ in range(3):
        asked = await _ask(client, installed, member=member_ref, purpose="node-1")
        assert asked.status_code in (200, 201), asked.text

    refused = await _ask(client, installed, member=member_ref, purpose="node-1")
    assert refused.status_code == 429
    assert refused.json()["detail"] == AppMessages.CONSENT_RATE_LIMITED
