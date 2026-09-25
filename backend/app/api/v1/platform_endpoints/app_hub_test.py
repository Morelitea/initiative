"""One installed app calling another through Initiative.

The caller holds ``apps:<target>`` and calls
``POST /app-platform/apps/{public_id}/endpoints/{endpoint_id}`` on its own
installation or member token. Initiative checks the call and makes it with a
context token naming the caller, the actor and, for a member, the target's own
reference for them.

The seam these tests stub is ``app_data._read_body``, where the call leaves for
the app called; everything above it runs for real.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import jwt
import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import seal_install_token
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.messages import AppDataMessages, AppHubMessages
from app.models.platform.guild import GuildRole
from app.models.tenant.app_member_consent import AppMemberConsent
from app.models.tenant.app_placement import AppPlacement
from app.models.tenant.guild_app import GuildApp
from app.models.tenant.guild_app_user_connection import GuildAppUserConnection
from app.services.marketplace import app_data as app_data_service
from app.services.marketplace.app_refs import ensure_app_ref
from app.services.marketplace.context_jwt_test import _PRIVATE_PEM
from app.testing import (
    create_app_service_registration,
    create_guild_app,
    emitted,
    route_session_to_guild,
)
from app.testing.app_clients import CLIENT, InstalledApp, install_app


TARGET = "tests.github"
TARGET_UID = "TESTGTHB000001"
TARGET_BASE = "http://127.0.0.1:9200"
APPS_SCOPE = f"apps:{TARGET}"
PURPOSE = "node-1"

#: A read either actor may call, the community's and a member's connection
#: either satisfying it.
ISSUES = f"app.{TARGET}.issues"
#: A write only a member may call.
COMMENT = f"app.{TARGET}.comment"
#: A write the community may call.
OPEN_ISSUE = f"app.{TARGET}.open_issue"
#: A read that is not part of the public surface.
PRIVATE = f"app.{TARGET}.private"


def _url(endpoint_id: str, public_id: str = TARGET) -> str:
    return f"/api/v1/app-platform/apps/{public_id}/endpoints/{endpoint_id}"


def _target_definition() -> dict[str, Any]:
    return {
        "app_kind": "service",
        "service": {"public_id": TARGET, "protocol": 1},
        "features": ["endpoints"],
        "connections": [
            {
                "id": "workspace",
                "scope": "static",
                "label": {"en": "Workspace"},
                "fields": [
                    {
                        "key": "org",
                        "type": "string",
                        "label": {"en": "Org"},
                        "required": True,
                    }
                ],
            },
            {
                "id": "account",
                "scope": "interactive",
                "label": {"en": "Account"},
                "fields": [{"key": "login", "type": "string", "label": {"en": "L"}}],
            },
        ],
        "endpoints": [
            {
                "id": ISSUES,
                "direction": "read",
                "public": True,
                "actors": ["installation", "member"],
                "requires": {"any_of": ["workspace", "account"]},
                "params": [{"key": "repo", "type": "string", "label": {"en": "R"}}],
                "cache_ttl_seconds": 60,
            },
            {
                "id": COMMENT,
                "direction": "write",
                "public": True,
                "actors": ["member"],
                "params": [{"key": "body", "type": "string", "label": {"en": "B"}}],
            },
            {
                "id": OPEN_ISSUE,
                "direction": "write",
                "public": True,
                "actors": ["installation"],
            },
            {
                "id": PRIVATE,
                "direction": "read",
                "actors": ["installation"],
            },
        ],
    }


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_PRIVATE_KEY_PEM", _PRIVATE_PEM)
    monkeypatch.setattr(settings, "APP_PLATFORM_SIGNING_KEY_ID", "app-platform-1")


@pytest.fixture(autouse=True)
def _clean_cache():
    app_data_service.clear_app_data_cache()
    app_data_service._inflight.clear()
    yield
    app_data_service.clear_app_data_cache()
    app_data_service._inflight.clear()


@pytest.fixture
def upstream(monkeypatch):
    """Stand in for the app called, recording every request it receives."""

    class Recorder:
        def __init__(self) -> None:
            self.calls: list[httpx.Request] = []

        def claims(self, index: int = -1) -> dict[str, Any]:
            header = self.calls[index].headers["Authorization"]
            return jwt.decode(
                header.removeprefix("Bearer "),
                options={"verify_signature": False},
                algorithms=["RS256"],
            )

    recorder = Recorder()

    async def _fake_read_body(request, *, transport=None):
        recorder.calls.append(request)
        return {"endpoint": "x", "actor": "installation", "result": {"number": 7}}

    monkeypatch.setattr(app_data_service, "_read_body", _fake_read_body)
    return recorder


async def _hub(
    session: AsyncSession,
    acting_user,
    role_session,
    *,
    granted: tuple[str, ...] = (APPS_SCOPE,),
    place_target: bool = True,
    install_target: bool = True,
) -> tuple[InstalledApp, Optional[GuildApp]]:
    """A caller asking for ``apps:tests.github``, and the target installed in
    the same community, placed where the caller is unless told otherwise."""
    installed = await install_app(
        session,
        acting_user,
        role_session,
        granted=list(granted),
        requested=[APPS_SCOPE, "documents:read"],
    )
    await create_app_service_registration(
        session, public_id=TARGET, listing_uid=TARGET_UID, base_url=TARGET_BASE
    )
    if not install_target:
        return installed, None
    target = await create_guild_app(
        session,
        installed.guild,
        installed.seat.user,
        definition=_target_definition(),
        listing_uid=TARGET_UID,
        name="GitHub",
        config={"workspace": {"org": "acme"}},
        connection_refs={"workspace": "gcr_workspace"},
    )
    if place_target:
        await route_session_to_guild(session, installed.guild.id)
        session.add(
            AppPlacement(install_id=target.id, initiative_id=installed.placed.id)
        )
        await session.commit()
    return installed, target


def _installation_headers(
    installed: InstalledApp,
    scopes: tuple[str, ...] = (APPS_SCOPE,),
    initiative_id: Optional[int] = None,
) -> dict[str, str]:
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=installed.app.id,
        client_id=CLIENT,
        scopes=frozenset(scopes),
        initiative_id=initiative_id,
    )
    return {"Authorization": f"Bearer {token}"}


async def _member(
    session: AsyncSession,
    acting_user,
    installed: InstalledApp,
    *,
    access: str = "read_write",
):
    """A member of the placed initiative who let the caller act as them."""
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=installed.guild,
        initiative=installed.placed,
        initiative_role="member",
    )
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        AppMemberConsent(
            install_id=installed.app.id,
            user_id=member.user.id,
            purpose=PURPOSE,
            label="Comment as you",
            requested_access="read_write",
            granted_access=access,
            granted_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    return member


def _member_headers(installed: InstalledApp, member) -> dict[str, str]:
    token, _exp = seal_install_token(
        guild_id=installed.guild.id,
        install_id=installed.app.id,
        client_id=CLIENT,
        scopes=frozenset({APPS_SCOPE}),
        initiative_id=None,
        user_id=member.user.id,
        purpose=PURPOSE,
    )
    return {"Authorization": f"Bearer {token}"}


async def _connect(session: AsyncSession, installed, target, member) -> None:
    """The member's own account on the target."""
    await route_session_to_guild(session, installed.guild.id)
    session.add(
        GuildAppUserConnection(
            app_id=target.id,
            connection_id="account",
            user_id=member.user.id,
            connection_ref="cr_member_account",
            config={"login": "alice"},
            status="connected",
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


async def test_a_caller_without_the_scope_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(ISSUES),
        json={"params": {}},
        headers=_installation_headers(installed, scopes=("documents:read",)),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppHubMessages.INSUFFICIENT_SCOPE
    assert upstream.calls == []


async def test_a_scope_the_seat_took_back_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    """The token still carries it; the grant no longer does."""
    installed, _target = await _hub(
        session, acting_user, role_session, granted=("documents:read",)
    )

    response = await client.post(
        _url(ISSUES), json={}, headers=_installation_headers(installed)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppHubMessages.INSUFFICIENT_SCOPE
    assert upstream.calls == []


async def test_a_target_not_installed_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(
        session, acting_user, role_session, install_target=False
    )

    response = await client.post(
        _url(ISSUES), json={}, headers=_installation_headers(installed)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == AppHubMessages.TARGET_NOT_INSTALLED


async def test_an_endpoint_that_is_not_public_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(PRIVATE), json={}, headers=_installation_headers(installed)
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppHubMessages.ENDPOINT_NOT_PUBLIC
    assert upstream.calls == []


async def test_a_member_only_endpoint_refuses_an_installation_token(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(COMMENT),
        json={"params": {"body": "Done"}},
        headers=_installation_headers(installed),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppHubMessages.ACTOR_NOT_SUPPORTED
    assert upstream.calls == []


async def test_a_target_not_placed_in_the_narrowed_initiative_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(
        session, acting_user, role_session, place_target=False
    )

    response = await client.post(
        _url(OPEN_ISSUE),
        json={},
        headers=_installation_headers(installed, initiative_id=installed.placed.id),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppHubMessages.TARGET_NOT_PLACED
    assert upstream.calls == []


async def test_a_target_placed_in_the_narrowed_initiative_is_called(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(OPEN_ISSUE),
        json={},
        headers=_installation_headers(installed, initiative_id=installed.placed.id),
    )

    assert response.status_code == 200, response.text
    assert upstream.claims()["initiative_id"] == installed.placed.id


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


async def test_an_installation_call_names_the_caller_and_passes_the_answer_back(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None

    response = await client.post(
        _url(ISSUES),
        json={"params": {"repo": "acme/web"}},
        headers=_installation_headers(installed),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "endpoint": "x",
        "actor": "installation",
        "result": {"number": 7},
    }
    (request,) = upstream.calls
    assert str(request.url) == f"{TARGET_BASE}/v1/endpoints"
    claims = upstream.claims()
    assert claims["aud"] == f"initiative-app:{TARGET}"
    assert claims["app_install_id"] == target.id
    assert claims["endpoint_id"] == ISSUES
    assert claims["act"] == {"sub": CLIENT}
    assert claims["actor"] == "installation"
    assert "member" not in claims
    assert "initiative_id" not in claims
    # The community's handle only.
    assert claims["connection_refs"] == {"workspace": "gcr_workspace"}


async def test_a_member_call_carries_the_targets_reference_never_the_callers(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)

    response = await client.post(
        _url(COMMENT),
        json={"params": {"body": "Done"}},
        headers=_member_headers(installed, member),
    )

    assert response.status_code == 200, response.text
    claims = upstream.claims()
    target_ref = await ensure_app_ref(
        guild_id=installed.guild.id, app_install_id=target.id, user_id=member.user.id
    )
    caller_ref = await ensure_app_ref(
        guild_id=installed.guild.id,
        app_install_id=installed.app.id,
        user_id=member.user.id,
    )
    assert claims["actor"] == "member"
    assert claims["member"] == target_ref
    assert target_ref != caller_ref
    assert caller_ref not in upstream.calls[0].headers["Authorization"]
    assert caller_ref.encode() not in upstream.calls[0].content


async def test_a_member_call_hands_on_only_the_members_connections(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)

    response = await client.post(
        _url(ISSUES), json={}, headers=_member_headers(installed, member)
    )

    assert response.status_code == 200, response.text
    assert upstream.claims()["connection_refs"] == {"account": "cr_member_account"}


async def test_a_read_only_consent_does_not_write_as_the_member(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)
    member = await _member(session, acting_user, installed, access="read")

    response = await client.post(
        _url(COMMENT),
        json={"params": {"body": "Done"}},
        headers=_member_headers(installed, member),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == AppHubMessages.INSUFFICIENT_SCOPE
    assert upstream.calls == []


async def test_a_parameter_the_endpoint_does_not_declare_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)

    response = await client.post(
        _url(ISSUES),
        json={"params": {"nope": "x"}},
        headers=_installation_headers(installed),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == AppDataMessages.INVALID_PARAMS


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


async def test_a_write_is_not_cached(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, _target = await _hub(session, acting_user, role_session)
    headers = _installation_headers(installed)

    for _ in range(2):
        response = await client.post(_url(OPEN_ISSUE), json={}, headers=headers)
        assert response.status_code == 200, response.text

    assert len(upstream.calls) == 2


async def test_a_read_is_cached_per_actor(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    installed, target = await _hub(session, acting_user, role_session)
    assert target is not None
    member = await _member(session, acting_user, installed)
    await _connect(session, installed, target, member)
    body = {"params": {"repo": "acme/web"}}

    for _ in range(2):
        response = await client.post(
            _url(ISSUES), json=body, headers=_installation_headers(installed)
        )
        assert response.status_code == 200, response.text
    assert len(upstream.calls) == 1

    response = await client.post(
        _url(ISSUES), json=body, headers=_member_headers(installed, member)
    )
    assert response.status_code == 200, response.text
    assert len(upstream.calls) == 2


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def test_every_call_is_written_to_the_audit_stream_without_its_params(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    role_session,
    upstream,
    capfd,
):
    installed, _target = await _hub(session, acting_user, role_session)
    capfd.readouterr()

    await client.post(
        _url(ISSUES),
        json={"params": {"repo": "secret-repo-name"}},
        headers=_installation_headers(installed),
    )
    await client.post(_url(PRIVATE), json={}, headers=_installation_headers(installed))

    answered, refused = emitted(capfd, AuditEventType.APP_HUB_CALL)
    assert answered["guild_id"] == installed.guild.id
    assert answered["detail"] == {
        "caller": CLIENT,
        "target": TARGET,
        "endpoint": ISSUES,
        "actor": "installation",
        "outcome": "ok",
        "direction": "read",
    }
    assert refused["detail"]["outcome"] == AppHubMessages.ENDPOINT_NOT_PUBLIC
    assert "secret-repo-name" not in str(answered)


async def test_a_member_token_for_a_member_who_left_is_refused(
    client: AsyncClient, session: AsyncSession, acting_user, role_session, upstream
):
    """The install seam still stands the token up first: a withdrawn consent
    leaves the member token nothing to act with."""
    installed, _target = await _hub(session, acting_user, role_session)
    member = await _member(session, acting_user, installed)
    await route_session_to_guild(session, installed.guild.id)
    consent = (
        await session.exec(
            select(AppMemberConsent).where(AppMemberConsent.user_id == member.user.id)
        )
    ).one()
    consent.revoked_at = datetime.now(timezone.utc)
    session.add(consent)
    await session.commit()

    response = await client.post(
        _url(ISSUES), json={}, headers=_member_headers(installed, member)
    )

    assert response.status_code == 401
    assert upstream.calls == []
