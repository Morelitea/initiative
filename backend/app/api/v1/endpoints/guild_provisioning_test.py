"""Guild lifecycle wires schema-per-guild provisioning.

Creating a guild provisions its `guild_<id>` schema + role; deleting one drops
them. The `client` fixture points the provisioning engine at the test DB and
cleans up any schemas/roles created.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.schema_provisioning import guild_role_name, guild_schema_name
from app.testing.factories import (
    create_user,
    get_auth_headers,
)

pytestmark = pytest.mark.integration


async def _schema_exists(engine: AsyncEngine, schema: str) -> bool:
    async with engine.connect() as conn:
        return (
            await conn.scalar(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": schema},
            )
        ) == 1


async def _role_exists(engine: AsyncEngine, role: str) -> bool:
    async with engine.connect() as conn:
        return (
            await conn.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})
        ) == 1


async def test_create_guild_provisions_schema_and_role(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine
):
    user = await create_user(session, email="prov-create@example.com")
    headers = get_auth_headers(user)

    resp = await client.post("/api/v1/guilds/", headers=headers, json={"name": "Prov Guild"})
    assert resp.status_code == 201
    gid = resp.json()["id"]
    schema = guild_schema_name(gid)

    assert await _schema_exists(engine, schema)
    assert await _role_exists(engine, guild_role_name(gid))
    async with engine.connect() as conn:
        assert await conn.scalar(text(f"SELECT to_regclass('{schema}.tasks')")) is not None


async def test_delete_guild_deprovisions_schema_and_role(
    client: AsyncClient, session: AsyncSession, engine: AsyncEngine
):
    user = await create_user(session, email="prov-delete@example.com")
    headers = get_auth_headers(user)

    resp = await client.post("/api/v1/guilds/", headers=headers, json={"name": "Del Prov"})
    gid = resp.json()["id"]
    schema, role = guild_schema_name(gid), guild_role_name(gid)
    assert await _schema_exists(engine, schema), "precondition: schema provisioned"

    resp = await client.request(
        "DELETE",
        f"/api/v1/guilds/{gid}",
        headers=headers,
        json={"password": "testpassword123", "confirmation_text": "DELETE GUILD DEL PROV"},
    )
    assert resp.status_code == 204

    assert not await _schema_exists(engine, schema)
    assert not await _role_exists(engine, role)
