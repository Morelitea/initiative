"""Published views reaching the audit log.

Publishing over a resource hands one person's reach to everybody who can open
the dashboard, so it is a grant — recorded as one, with the dashboard as the
grantee. Adding a resource to the published list and taking one back are the
two ends of it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import GuildRole
from app.testing import create_project, recorded

pytestmark = pytest.mark.integration

COUNT_TASKS = "SELECT count(*) AS n FROM tasks"


async def _dashboards_on(session: AsyncSession, initiative) -> None:
    initiative.dashboards_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _dashboard(client: AsyncClient, actor) -> int:
    response = await client.post(
        actor.g("/dashboards/"),
        headers=actor.headers,
        json={
            "name": "Status",
            "initiative_id": actor.initiative.id,
            "definition": {
                "version": 1,
                "widgets": [
                    {
                        "id": "w1",
                        "type": "stat",
                        "grid": {"x": 0, "y": 0, "w": 4, "h": 2},
                        "binding": {"source": "query", "sql": COUNT_TASKS},
                    }
                ],
            },
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _published_rows(session: AsyncSession):
    """Only the grants made TO a dashboard — a creation's own default share is
    an ordinary grant and is recorded separately."""
    rows = await recorded(session, AuditEventType.SHARING_GRANT_CHANGED)
    return [
        row for row in rows if row.envelope["detail"]["grantee"]["kind"] == "dashboard"
    ]


async def test_publishing_over_a_resource_records_the_dashboard_as_the_grantee(
    client: AsyncClient, session: AsyncSession, acting_user
):
    author = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_on(session, author.initiative)
    project = await create_project(session, author.initiative, author.user)
    dashboard_id = await _dashboard(client, author)

    response = await client.put(
        author.g(f"/dashboards/{dashboard_id}/published"),
        headers=author.headers,
        json={"resources": [{"resource_type": "project", "resource_id": project.id}]},
    )
    assert response.status_code == 200, response.text

    (row,) = await _published_rows(session)
    assert row.actor_user_id == author.user.id
    assert row.target_user_id is None
    assert row.guild_id == author.guild.id
    assert (row.target_type, row.target_id) == ("project", project.id)
    assert row.envelope["detail"] == {
        "initiative_id": author.initiative.id,
        "grantee": {"kind": "dashboard", "id": dashboard_id},
        "from": None,
        "to": "read",
    }


async def test_republishing_the_same_list_records_nothing_further(
    client: AsyncClient, session: AsyncSession, acting_user
):
    author = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_on(session, author.initiative)
    project = await create_project(session, author.initiative, author.user)
    dashboard_id = await _dashboard(client, author)
    body = {"resources": [{"resource_type": "project", "resource_id": project.id}]}

    first = await client.put(
        author.g(f"/dashboards/{dashboard_id}/published"),
        headers=author.headers,
        json=body,
    )
    second = await client.put(
        author.g(f"/dashboards/{dashboard_id}/published"),
        headers=author.headers,
        json=body,
    )
    assert first.status_code == second.status_code == 200

    assert len(await _published_rows(session)) == 1


async def test_taking_a_published_view_back_records_the_withdrawal(
    client: AsyncClient, session: AsyncSession, acting_user
):
    author = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_on(session, author.initiative)
    project = await create_project(session, author.initiative, author.user)
    dashboard_id = await _dashboard(client, author)
    await client.put(
        author.g(f"/dashboards/{dashboard_id}/published"),
        headers=author.headers,
        json={"resources": [{"resource_type": "project", "resource_id": project.id}]},
    )

    revoked = await client.delete(
        author.g(f"/dashboards/{dashboard_id}/published/project/{project.id}"),
        headers=author.headers,
    )
    assert revoked.status_code == 204, revoked.text

    rows = await _published_rows(session)
    assert [
        (r.envelope["detail"]["from"], r.envelope["detail"]["to"]) for r in rows
    ] == [
        (None, "read"),
        ("read", None),
    ]
    assert rows[-1].actor_user_id == author.user.id
    assert (rows[-1].target_type, rows[-1].target_id) == ("project", project.id)
