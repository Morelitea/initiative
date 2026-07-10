"""Delegated run endpoint tests.

``POST /g/{guild_id}/advanced-tools/{id}/run`` is the automation service's
execution call: it must accept only delegation-token callers, apply the
standard DAC path as the delegated user, answer 404 for a tool that is gone
(trashed / invisible / never existed), and hand back the current definition
blob for the service to execute.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import config as config_module
from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import Initiative
from app.testing import route_session_to_guild

pytestmark = pytest.mark.integration

_keypair = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _keypair.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = (
    _keypair.public_key()
    .public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)


def _delegation_headers(*, user_id: int, guild_id: int) -> dict[str, str]:
    """Mint a fresh (one-shot) delegation JWT for the user + guild."""
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "jti": secrets.token_hex(8),
            "sub": str(user_id),
            "aud": "initiative:auto-delegation",
            "iss": "initiative-auto",
            "iat": int(now.timestamp()),
            "exp": now + timedelta(seconds=900),
            "guild_id": guild_id,
        },
        _PRIVATE_PEM,
        algorithm="RS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _enable_delegation(monkeypatch):
    monkeypatch.setattr(
        config_module.settings, "AUTO_DELEGATION_PUBLIC_KEY_PEM", _PUBLIC_PEM
    )


async def _enable_advanced_tool(session: AsyncSession, initiative) -> None:
    await route_session_to_guild(session, initiative.guild_id)
    init = await session.get(Initiative, initiative.id)
    assert init is not None
    init.advanced_tools_enabled = True
    session.add(init)
    await session.commit()


async def _create_tool(client: AsyncClient, actor, *, initiative_id=None, data=None):
    payload: dict = {"name": "Runner target", "data": data or {"nodes": []}}
    if initiative_id is not None:
        payload["initiative_id"] = initiative_id
    response = await client.post(
        actor.g("/advanced-tools/"), headers=actor.headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_run_refuses_non_delegated_callers(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Even the tool's owner on a normal session can't hit the run endpoint —
    it exists solely for the automation service's delegation tokens."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)
    tool = await _create_tool(client, a, initiative_id=a.initiative.id)

    response = await client.post(
        a.g(f"/advanced-tools/{tool['id']}/run"), headers=a.headers, json={}
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "ADVANCED_TOOL_DELEGATED_RUN_ONLY"


async def test_delegated_run_returns_current_definition(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)
    blob = {"nodes": [{"key": "digest", "type": "action", "action": "run_report"}]}
    tool = await _create_tool(client, a, initiative_id=a.initiative.id, data=blob)

    response = await client.post(
        a.g(f"/advanced-tools/{tool['id']}/run"),
        headers=_delegation_headers(user_id=a.user.id, guild_id=a.guild.id),
        json={"node_key": "digest", "cause": "schedule", "source_event_id": "evt-7"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["advanced_tool_id"] == tool["id"]
    assert body["guild_id"] == a.guild.id
    assert body["initiative_id"] == a.initiative.id
    # The definition comes back verbatim, with the run context echoed.
    assert body["data"] == blob
    assert body["node_key"] == "digest"
    assert body["cause"] == "schedule"
    assert body["source_event_id"] == "evt-7"


async def test_delegated_run_missing_tool_404(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    response = await client.post(
        a.g("/advanced-tools/999999/run"),
        headers=_delegation_headers(user_id=a.user.id, guild_id=a.guild.id),
        json={},
    )
    assert response.status_code == 404


async def test_delegated_run_trashed_tool_404(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A trashed tool is gone for the runner — 404 is its cancel signal, so
    the soft-delete filter must apply here too."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)
    tool = await _create_tool(client, a, initiative_id=a.initiative.id)

    deleted = await client.delete(
        a.g(f"/advanced-tools/{tool['id']}"), headers=a.headers
    )
    assert deleted.status_code == 204

    response = await client.post(
        a.g(f"/advanced-tools/{tool['id']}/run"),
        headers=_delegation_headers(user_id=a.user.id, guild_id=a.guild.id),
        json={},
    )
    assert response.status_code == 404


async def test_delegated_run_requires_write_access(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """The default create grant gives initiative members read — a delegated
    run as such a member must fail the DAC write check, not sneak through."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)
    tool = await _create_tool(client, a, initiative_id=a.initiative.id)

    member = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    response = await client.post(
        member.g(f"/advanced-tools/{tool['id']}/run"),
        headers=_delegation_headers(user_id=member.user.id, guild_id=a.guild.id),
        json={},
    )
    assert response.status_code == 403


async def test_delegated_run_feature_disabled_403(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Disabling advanced tools on the initiative blocks delegated runs of its
    tools (403, the runner's retry-then-fail path)."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_advanced_tool(session, a.initiative)
    tool = await _create_tool(client, a, initiative_id=a.initiative.id)

    await route_session_to_guild(session, a.guild.id)
    init = await session.get(Initiative, a.initiative.id)
    assert init is not None
    init.advanced_tools_enabled = False
    session.add(init)
    await session.commit()

    response = await client.post(
        a.g(f"/advanced-tools/{tool['id']}/run"),
        headers=_delegation_headers(user_id=a.user.id, guild_id=a.guild.id),
        json={},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "ADVANCED_TOOL_NOT_ENABLED"


async def test_delegated_run_guild_wide_tool(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Guild-wide tools run for a delegated guild admin; a plain member never
    even sees the row (RLS), so their delegated run answers 404."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    tool = await _create_tool(client, admin)  # no initiative_id → guild-wide
    assert tool["initiative_id"] is None

    ok = await client.post(
        admin.g(f"/advanced-tools/{tool['id']}/run"),
        headers=_delegation_headers(user_id=admin.user.id, guild_id=admin.guild.id),
        json={"cause": "event"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["initiative_id"] is None

    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    hidden = await client.post(
        member.g(f"/advanced-tools/{tool['id']}/run"),
        headers=_delegation_headers(user_id=member.user.id, guild_id=admin.guild.id),
        json={},
    )
    assert hidden.status_code == 404
