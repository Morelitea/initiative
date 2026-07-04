"""Integration tests for calendar-event custom-property endpoints.

Mirrors documents_properties_test.py / tasks_properties_test.py for the
event side:
- PUT /calendar-events/{id}/properties replace-all semantics
- Type validation per property type (representative sample)
- user_reference non-initiative-member rejection
- Cross-initiative definition rejection
- RLS isolation between initiatives
- ``property_filters`` query-param filtering on the events list
"""

import json

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.property import (
    CalendarEventPropertyValue,
    PropertyType,
)
from app.testing import (
    create_calendar_event,
    create_guild_membership,
    create_initiative,
    create_property_definition,
    create_user,
)


async def _enable_events(session: AsyncSession, initiative):
    """Toggle the events feature flag on and persist it."""
    initiative.calendar_events_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)


async def _setup_event(session, acting_user):
    """Boilerplate: admin user, guild, events-enabled initiative, event.

    Returns ``(actor, initiative, event)`` — ``actor`` carries user/guild/headers.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await _enable_events(session, a.initiative)
    event = await create_calendar_event(session, a.initiative, a.user, title="E")
    return a, a.initiative, event


# ---------------------------------------------------------------------------
# PUT replace-all
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_event_properties_sets_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative, event = await _setup_event(session, acting_user)

    text_defn = await create_property_definition(
        session, initiative, name="Note", type=PropertyType.text
    )
    number_defn = await create_property_definition(
        session, initiative, name="Score", type=PropertyType.number
    )

    response = await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={
            "values": [
                {"property_id": text_defn.id, "value": "alpha"},
                {"property_id": number_defn.id, "value": 7.5},
            ]
        },
    )

    assert response.status_code == 200
    props = {p["property_id"]: p for p in response.json()["property_values"]}
    assert props[text_defn.id]["value"] == "alpha"
    assert float(props[number_defn.id]["value"]) == 7.5


@pytest.mark.integration
async def test_put_event_properties_empty_clears_existing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative, event = await _setup_event(session, acting_user)

    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )

    await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "seed"}]},
    )
    response = await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={"values": []},
    )

    assert response.status_code == 200
    assert response.json()["property_values"] == []
    rows = await session.exec(
        select(CalendarEventPropertyValue).where(
            CalendarEventPropertyValue.event_id == event.id
        )
    )
    assert rows.all() == []


@pytest.mark.integration
async def test_put_event_properties_attach_without_value_persists_row(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Attaching without a value should still create the attached-empty row."""
    a, initiative, event = await _setup_event(session, acting_user)
    defn = await create_property_definition(
        session, initiative, name="Empty", type=PropertyType.text
    )

    response = await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": None}]},
    )
    assert response.status_code == 200
    rows = (
        await session.exec(
            select(CalendarEventPropertyValue).where(
                CalendarEventPropertyValue.event_id == event.id
            )
        )
    ).all()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Type validation (sample)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_event_date_rejects_garbage(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative, event = await _setup_event(session, acting_user)
    defn = await create_property_definition(
        session, initiative, name="D", type=PropertyType.date
    )

    response = await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "not-a-date"}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"


@pytest.mark.integration
async def test_put_event_user_reference_non_initiative_member_rejected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative, event = await _setup_event(session, acting_user)

    outsider = await create_user(session, email="outsider@example.com")
    await create_guild_membership(
        session, user=outsider, guild=a.guild, role=GuildRole.member
    )

    defn = await create_property_definition(
        session, initiative, name="Owner", type=PropertyType.user_reference
    )

    response = await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": outsider.id}]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_USER_NOT_IN_INITIATIVE"


# ---------------------------------------------------------------------------
# Cross-initiative / RLS
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_put_event_cross_initiative_definition_rejected(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A definition from initiative B can't be attached to an event in A."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    init_a = a.initiative
    await _enable_events(session, init_a)
    init_b = await create_initiative(session, a.guild, a.user, name="B")
    event_a = await create_calendar_event(session, init_a, a.user, title="Ea")

    defn_b = await create_property_definition(session, init_b, name="Foreign")

    response = await client.put(
        a.g(f"/calendar-events/{event_a.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn_b.id, "value": "x"}]},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


# ---------------------------------------------------------------------------
# property_values serialization on list/read
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_event_read_embeds_property_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative, event = await _setup_event(session, acting_user)
    defn = await create_property_definition(
        session, initiative, name="Topic", type=PropertyType.text
    )

    await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "onboarding"}]},
    )

    read_resp = await client.get(a.g(f"/calendar-events/{event.id}"), headers=a.headers)
    assert read_resp.status_code == 200
    body = read_resp.json()
    assert body["property_values"][0]["value"] == "onboarding"


@pytest.mark.integration
async def test_list_events_filter_by_property_text_eq(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative, _ = await _setup_event(session, acting_user)

    match = await create_calendar_event(session, initiative, a.user, title="Match")
    skip = await create_calendar_event(session, initiative, a.user, title="Skip")

    defn = await create_property_definition(
        session, initiative, name="Topic", type=PropertyType.text
    )

    await client.put(
        a.g(f"/calendar-events/{match.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "findme"}]},
    )
    await client.put(
        a.g(f"/calendar-events/{skip.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "other"}]},
    )

    property_filters = json.dumps(
        [{"property_id": defn.id, "op": "eq", "value": "findme"}]
    )
    response = await client.get(
        a.g(
            f"/calendar-events/?initiative_id={initiative.id}"
            f"&property_filters={property_filters}"
        ),
        headers=a.headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert match.id in ids
    assert skip.id not in ids


@pytest.mark.integration
async def test_list_events_filter_is_empty_matches_unset(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative, _ = await _setup_event(session, acting_user)

    with_value = await create_calendar_event(
        session, initiative, a.user, title="WithVal"
    )
    without_value = await create_calendar_event(
        session, initiative, a.user, title="Blank"
    )

    defn = await create_property_definition(
        session, initiative, name="Topic", type=PropertyType.text
    )

    await client.put(
        a.g(f"/calendar-events/{with_value.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "yes"}]},
    )

    property_filters = json.dumps(
        [{"property_id": defn.id, "op": "is_null", "value": True}]
    )
    response = await client.get(
        a.g(
            f"/calendar-events/?initiative_id={initiative.id}"
            f"&property_filters={property_filters}"
        ),
        headers=a.headers,
    )
    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["items"]}
    assert without_value.id in ids
    assert with_value.id not in ids


# ---------------------------------------------------------------------------
# Initiative delete cascades event property values
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_initiative_purge_cascades_event_property_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """Soft-deleting then hard-purging an initiative should cascade-delete
    event property values via FK CASCADE. (Soft-delete alone keeps the
    rows so a restore brings everything back.)"""
    a, initiative, event = await _setup_event(session, acting_user)
    defn = await create_property_definition(
        session, initiative, name="Topic", type=PropertyType.text
    )

    await client.put(
        a.g(f"/calendar-events/{event.id}/properties"),
        headers=a.headers,
        json={"values": [{"property_id": defn.id, "value": "hold"}]},
    )

    # 1. Soft-delete the initiative — property values must still exist so
    # a restore brings them back.
    delete_resp = await client.delete(
        a.g(f"/initiatives/{initiative.id}"), headers=a.headers
    )
    assert delete_resp.status_code in (200, 204)
    rows = await session.exec(
        select(CalendarEventPropertyValue).where(
            CalendarEventPropertyValue.property_id == defn.id
        )
    )
    assert len(rows.all()) == 1

    # 2. Hard-purge via the admin trash endpoint — FK CASCADE drops the
    # event property values along with the initiative + descendants.
    purge_resp = await client.delete(
        a.g(f"/trash/initiative/{initiative.id}/purge"), headers=a.headers
    )
    assert purge_resp.status_code == 204
    rows = await session.exec(
        select(CalendarEventPropertyValue).where(
            CalendarEventPropertyValue.property_id == defn.id
        )
    )
    assert rows.all() == []
