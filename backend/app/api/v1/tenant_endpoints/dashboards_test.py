"""Tests for the dashboard endpoints — CRUD, sharing, and the authorization
gates (feature gate, role create gate, DAC levels, initiative isolation).

The dashboard-specific concern beyond the usual tool contract: sharing a
dashboard shares the canvas, never the data it displays, and no endpoint
accepts anything that would let a definition write.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import delete as sa_delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.resource_grant import ResourceGrant
from app.testing import create_dashboard


def _kpi_definition() -> dict:
    return {
        "widgets": [
            {
                "id": "w1",
                "type": "kpi",
                "title": "Open bugs",
                "binding": {"source": "counter", "counter_id": None},
            }
        ]
    }


async def _dashboards_enabled(session: AsyncSession, initiative) -> None:
    initiative.dashboards_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _strip_non_owner_grants(session, dashboard, owner_id: int) -> None:
    """Remove every grant except the owner's own — the dashboard becomes
    invisible to other members."""
    await session.exec(
        sa_delete(ResourceGrant).where(
            ResourceGrant.resource_type == "dashboard",
            ResourceGrant.resource_id == dashboard.id,
            ResourceGrant.user_id.is_distinct_from(owner_id),
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_create_dashboard(client: AsyncClient, acting_user, session):
    """Creating a dashboard stores a normalized definition and seeds the
    creator's owner grant plus the default all-members read grant."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)

    response = await client.post(
        a.g("/dashboards/"),
        headers=a.headers,
        json={
            "name": "Delivery",
            "description": "Release health",
            "initiative_id": a.initiative.id,
            "definition": _kpi_definition(),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Delivery"
    # Canonicalized on the way in.
    assert body["definition"]["schema_version"] == 1
    assert body["definition"]["kind"] == "dashboard"
    assert body["definition"]["widgets"][0]["type"] == "kpi"
    assert body["my_permission_level"] == "owner"
    assert body["listing_uid"] is None


@pytest.mark.integration
async def test_create_rejects_unknown_widget_type(
    client: AsyncClient, acting_user, session
):
    """A definition naming a widget we don't render is refused, not stored."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)

    response = await client.post(
        a.g("/dashboards/"),
        headers=a.headers,
        json={
            "name": "Bad",
            "initiative_id": a.initiative.id,
            "definition": {
                "widgets": [{"type": "iframe", "binding": {"source": "tasks"}}]
            },
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "DASHBOARD_WIDGET_TYPE_UNKNOWN"


@pytest.mark.integration
async def test_create_requires_feature_enabled(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    # dashboards_enabled defaults to False.

    response = await client.post(
        a.g("/dashboards/"),
        headers=a.headers,
        json={"name": "Nope", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "DASHBOARDS_NOT_ENABLED"


@pytest.mark.integration
async def test_list_and_read_dashboard(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user, name="Ops")

    listing = await client.get(a.g("/dashboards/"), headers=a.headers)
    assert listing.status_code == 200
    assert [d["name"] for d in listing.json()["items"]] == ["Ops"]
    # The list omits the canvas body — only the detail read carries it.
    assert "definition" not in listing.json()["items"][0]

    detail = await client.get(a.g(f"/dashboards/{dashboard.id}"), headers=a.headers)
    assert detail.status_code == 200
    assert detail.json()["definition"]["widgets"][0]["type"] == "kpi"


@pytest.mark.integration
async def test_update_definition_revalidates(client: AsyncClient, acting_user, session):
    """Re-authoring the canvas is the one write a dashboard has, and it goes
    through the same validator as create."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    ok = await client.patch(
        a.g(f"/dashboards/{dashboard.id}"),
        headers=a.headers,
        json={
            "definition": {
                "widgets": [
                    {
                        "id": "chart1",
                        "type": "line_chart",
                        "binding": {"source": "task_counts"},
                    }
                ]
            }
        },
    )
    assert ok.status_code == 200, ok.text
    widget = ok.json()["definition"]["widgets"][0]
    # Presets are stored resolved: the renderer only ever sees a primitive.
    assert widget["type"] == "chart"
    assert widget["options"]["mark"] == "line"

    bad = await client.patch(
        a.g(f"/dashboards/{dashboard.id}"),
        headers=a.headers,
        json={
            "definition": {"widgets": [{"type": "kpi", "binding": {"source": "tasks"}}]}
        },
    )
    assert bad.status_code == 422
    assert bad.json()["detail"] == "DASHBOARD_BINDING_SOURCE_NOT_ALLOWED"


@pytest.mark.integration
async def test_config_for_removed_widget_is_dropped(
    client: AsyncClient, acting_user, session
):
    """Config can't outlive the widget it configures."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    response = await client.patch(
        a.g(f"/dashboards/{dashboard.id}"),
        headers=a.headers,
        json={
            "definition": {
                "widgets": [
                    {"id": "kept", "type": "kpi", "binding": {"source": "counter"}}
                ]
            },
            "config": {
                "widgets": {"kept": {"counter_id": 7}, "gone": {"counter_id": 9}}
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["config"] == {"widgets": {"kept": {"counter_id": 7}}}


@pytest.mark.integration
async def test_delete_dashboard(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    response = await client.delete(
        a.g(f"/dashboards/{dashboard.id}"), headers=a.headers
    )
    assert response.status_code == 204

    listing = await client.get(a.g("/dashboards/"), headers=a.headers)
    assert listing.json()["items"] == []


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_member_without_create_permission_is_refused(
    client: AsyncClient, acting_user, session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.post(
        b.g("/dashboards/"),
        headers=b.headers,
        json={"name": "Mine", "initiative_id": a.initiative.id},
    )

    assert response.status_code == 403


@pytest.mark.integration
async def test_unshared_dashboard_is_invisible_to_other_members(
    client: AsyncClient, acting_user, session
):
    """DAC is the final gate: a co-member who holds no grant can neither list
    nor read it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)
    await _strip_non_owner_grants(session, dashboard, a.user.id)

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    listing = await client.get(b.g("/dashboards/"), headers=b.headers)
    assert listing.status_code == 200
    assert listing.json()["items"] == []

    detail = await client.get(b.g(f"/dashboards/{dashboard.id}"), headers=b.headers)
    assert detail.status_code in (403, 404)


@pytest.mark.integration
async def test_read_grant_cannot_write(client: AsyncClient, acting_user, session):
    """A viewer may look at the canvas but not re-author it."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    assert (
        await client.get(b.g(f"/dashboards/{dashboard.id}"), headers=b.headers)
    ).status_code == 200

    response = await client.patch(
        b.g(f"/dashboards/{dashboard.id}"),
        headers=b.headers,
        json={"name": "Hijacked"},
    )
    assert response.status_code == 403


@pytest.mark.integration
async def test_non_member_of_initiative_cannot_see_dashboard(
    client: AsyncClient, acting_user, session
):
    """Initiative isolation is the hard boundary — a guild member outside the
    initiative gets nothing, even with a guild role."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)

    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)

    response = await client.get(b.g(f"/dashboards/{dashboard.id}"), headers=b.headers)
    assert response.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Sharing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_set_grants_replaces_sharing(client: AsyncClient, acting_user, session):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _dashboards_enabled(session, a.initiative)
    dashboard = await create_dashboard(session, a.initiative, a.user)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )

    response = await client.put(
        a.g(f"/dashboards/{dashboard.id}/grants"),
        headers=a.headers,
        json=[{"user_id": b.user.id, "level": "write"}],
    )
    assert response.status_code == 200, response.text

    # b can now re-author it; the all-members read grant is gone.
    patched = await client.patch(
        b.g(f"/dashboards/{dashboard.id}"),
        headers=b.headers,
        json={"name": "Co-owned"},
    )
    assert patched.status_code == 200
