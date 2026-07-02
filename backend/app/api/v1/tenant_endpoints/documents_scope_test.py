"""Initiative-scope enforcement for document access.

The schema-per-guild cutover removed the DB-level RESTRICTIVE
``is_initiative_member`` policies; these tests pin the app-level replacement:
removal from an initiative must end document access — the permission rows are
cleaned up, and a stale row alone would not grant access anyway
(``initiative_scope_ok`` gate, unit-tested in ``services/permissions_test``).
"""

import pytest
from httpx import AsyncClient

from app.models.platform.guild import GuildRole


@pytest.mark.integration
async def test_initiative_removal_ends_document_access(
    client: AsyncClient, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    initiative = admin.initiative
    admin_headers = admin.headers
    member_headers = member.headers

    # Admin creates a document and shares it with the member.
    response = await client.post(
        admin.g("/documents/"),
        headers=admin_headers,
        json={"title": "Shared Doc", "initiative_id": initiative.id},
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    response = await client.put(
        admin.g(f"/documents/{doc_id}/grants"),
        headers=admin_headers,
        json=[{"user_id": member.user.id, "level": "write"}],
    )
    assert response.status_code == 200

    # Member can open and list the document while in the initiative.
    response = await client.get(
        member.g(f"/documents/{doc_id}"), headers=member_headers
    )
    assert response.status_code == 200
    response = await client.get(member.g("/documents/"), headers=member_headers)
    assert doc_id in {d["id"] for d in response.json()["items"]}

    # Remove the member from the initiative.
    response = await client.delete(
        admin.g(f"/initiatives/{initiative.id}/members/{member.user.id}"),
        headers=admin_headers,
    )
    assert response.status_code == 200

    # Access is gone: once out of the initiative, the initiative RLS hides the
    # document entirely — open is 404 (not a 403 existence leak), and the list no
    # longer contains it.
    response = await client.get(
        member.g(f"/documents/{doc_id}"), headers=member_headers
    )
    assert response.status_code == 404
    response = await client.get(member.g("/documents/"), headers=member_headers)
    assert doc_id not in {d["id"] for d in response.json()["items"]}

    # The admin (initiative PM here) is unaffected.
    response = await client.get(admin.g(f"/documents/{doc_id}"), headers=admin_headers)
    assert response.status_code == 200
