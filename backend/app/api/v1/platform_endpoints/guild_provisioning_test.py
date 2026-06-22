"""Guild lifecycle wires schema-per-guild provisioning.

Creating a guild provisions its `guild_<id>` schema + role; deleting one drops
them. The `client` fixture points the provisioning engine at the test DB and
cleans up any schemas/roles created.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.api.v1.platform_endpoints.guilds as guilds_endpoint
from app.db.schema_provisioning import guild_role_name, guild_schema_name
from app.models.platform.guild import Guild
from app.testing.factories import (
    create_user,
    get_auth_headers,
)

pytestmark = pytest.mark.integration


async def _schema_exists(engine: AsyncEngine, schema: str) -> bool:
    async with engine.connect() as conn:
        return (
            await conn.scalar(
                text(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"
                ),
                {"s": schema},
            )
        ) == 1


async def _role_exists(engine: AsyncEngine, role: str) -> bool:
    async with engine.connect() as conn:
        return (
            await conn.scalar(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
            )
        ) == 1


async def test_create_guild_provisions_schema_and_role(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine
):
    user = await create_user(session, email="prov-create@example.com")
    headers = get_auth_headers(user)

    resp = await client.post(
        "/api/v1/guilds/", headers=headers, json={"name": "Prov Guild"}
    )
    assert resp.status_code == 201
    gid = resp.json()["id"]
    schema = guild_schema_name(gid)

    assert await _schema_exists(engine, schema)
    assert await _role_exists(engine, guild_role_name(gid))
    async with engine.connect() as conn:
        assert (
            await conn.scalar(text(f"SELECT to_regclass('{schema}.tasks')")) is not None
        )


async def test_delete_guild_deprovisions_schema_and_role(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine
):
    user = await create_user(session, email="prov-delete@example.com")
    headers = get_auth_headers(user)

    resp = await client.post(
        "/api/v1/guilds/", headers=headers, json={"name": "Del Prov"}
    )
    gid = resp.json()["id"]
    schema, role = guild_schema_name(gid), guild_role_name(gid)
    assert await _schema_exists(engine, schema), "precondition: schema provisioned"

    resp = await client.request(
        "DELETE",
        f"/api/v1/guilds/{gid}",
        headers=headers,
        json={
            "password": "testpassword123",
            "confirmation_text": "DELETE GUILD DEL PROV",
        },
    )
    assert resp.status_code == 204

    assert not await _schema_exists(engine, schema)
    assert not await _role_exists(engine, role)


async def test_create_guild_rolls_back_when_provisioning_fails(
    client: AsyncClient, session: AsyncSession, monkeypatch
):
    """If provisioning fails, the guild is rolled back (no orphaned row)."""

    async def boom(*args, **kwargs):
        raise RuntimeError("provisioning failed")

    # Provisioning + schema seeding now run inside the service helper.
    monkeypatch.setattr(guilds_endpoint.guilds_service, "seed_guild_content", boom)

    user = await create_user(session, email="rollback@example.com")
    headers = get_auth_headers(user)
    resp = await client.post(
        "/api/v1/guilds/", headers=headers, json={"name": "Rollback Guild"}
    )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "GUILD_PROVISION_FAILED"
    remaining = (
        await session.exec(select(Guild).where(Guild.name == "Rollback Guild"))
    ).all()
    assert remaining == [], "guild row must be rolled back when provisioning fails"


async def test_delete_guild_succeeds_even_if_deprovision_fails(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine, monkeypatch
):
    """The guild row is deleted FIRST (the guild is gone from the app), then the
    schema is dropped as best-effort cleanup. So a deprovision failure must NOT
    fail the deletion — the row is already gone; an orphaned empty schema is
    harmless (reclaimed on retry / next provision)."""
    user = await create_user(session, email="deprov-fail@example.com")
    headers = get_auth_headers(user)
    resp = await client.post(
        "/api/v1/guilds/", headers=headers, json={"name": "Teardown Fail"}
    )
    gid = resp.json()["id"]

    async def boom(_guild_id):
        raise RuntimeError("deprovisioning failed")

    monkeypatch.setattr(guilds_endpoint, "deprovision_guild", boom)
    resp = await client.request(
        "DELETE",
        f"/api/v1/guilds/{gid}",
        headers=headers,
        json={
            "password": "testpassword123",
            "confirmation_text": "DELETE GUILD TEARDOWN FAIL",
        },
    )

    assert resp.status_code == 204
    remaining = (await session.exec(select(Guild).where(Guild.id == gid))).all()
    assert remaining == [], "guild row is deleted even when schema cleanup fails"
