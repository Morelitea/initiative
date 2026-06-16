"""Initiative-scope enforcement for document access.

The schema-per-guild cutover removed the DB-level RESTRICTIVE
``is_initiative_member`` policies; these tests pin the app-level replacement:
removal from an initiative must end document access — the permission rows are
cleaned up, and a stale row alone would not grant access anyway
(``initiative_scope_ok`` gate, unit-tested in ``services/permissions_test``).
"""

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.guild import GuildRole
from app.testing.factories import (
    create_guild,
    create_guild_membership,
    create_initiative,
    create_initiative_member,
    create_user,
    get_guild_headers,
)


async def _setup(session: AsyncSession):
    admin = await create_user(session, email="admin@example.com")
    member = await create_user(session, email="member@example.com")
    guild = await create_guild(session, creator=admin)
    await create_guild_membership(
        session, user=admin, guild=guild, role=GuildRole.admin
    )
    await create_guild_membership(
        session, user=member, guild=guild, role=GuildRole.member
    )
    initiative = await create_initiative(session, guild, admin)
    await create_initiative_member(session, initiative, member)
    return admin, member, guild, initiative


@pytest.mark.integration
async def test_initiative_removal_ends_document_access(
    client: AsyncClient, session: AsyncSession
):
    admin, member, guild, initiative = await _setup(session)
    admin_headers = await get_guild_headers(session, guild, admin)
    member_headers = await get_guild_headers(session, guild, member)

    # Admin creates a document and shares it with the member.
    response = await client.post(
        f"/api/v1/g/{guild.id}/documents/",
        headers=admin_headers,
        json={"title": "Shared Doc", "initiative_id": initiative.id},
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    response = await client.post(
        f"/api/v1/g/{guild.id}/documents/{doc_id}/members",
        headers=admin_headers,
        json={"user_id": member.id, "level": "write"},
    )
    assert response.status_code == 201

    # Member can open and list the document while in the initiative.
    response = await client.get(
        f"/api/v1/g/{guild.id}/documents/{doc_id}", headers=member_headers
    )
    assert response.status_code == 200
    response = await client.get(
        f"/api/v1/g/{guild.id}/documents/", headers=member_headers
    )
    assert doc_id in {d["id"] for d in response.json()["items"]}

    # Remove the member from the initiative.
    response = await client.delete(
        f"/api/v1/g/{guild.id}/initiatives/{initiative.id}/members/{member.id}",
        headers=admin_headers,
    )
    assert response.status_code == 200

    # Access is gone: open is 403, the list no longer contains the doc.
    response = await client.get(
        f"/api/v1/g/{guild.id}/documents/{doc_id}", headers=member_headers
    )
    assert response.status_code == 403
    response = await client.get(
        f"/api/v1/g/{guild.id}/documents/", headers=member_headers
    )
    assert doc_id not in {d["id"] for d in response.json()["items"]}

    # The admin (initiative PM here) is unaffected.
    response = await client.get(
        f"/api/v1/g/{guild.id}/documents/{doc_id}", headers=admin_headers
    )
    assert response.status_code == 200
