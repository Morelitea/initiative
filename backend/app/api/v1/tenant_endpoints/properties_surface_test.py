"""The custom-property surface, proved once for every entity that carries it.

Tasks, documents and calendar events each expose ``PUT …/{id}/properties``
with replace-all semantics, hold a value to its definition's type, keep a
definition inside its initiative, and filter their list by a value. The rules
are the property engine's (``services/tenant/properties_test.py``); what this
file pins is that each entity's endpoint surfaces them the same way. A fourth
entity that grows properties gets the same proof by adding a ``Surface``.

What only one entity does — a task moving between initiatives, a document
being copied, an event outliving its initiative — sits at the bottom under
that entity's name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.guild import GuildRole
from app.models.tenant.initiative import Initiative
from app.models.tenant.property import (
    CalendarEventPropertyValue,
    DocumentPropertyValue,
    PropertyType,
    TaskPropertyValue,
)
from app.testing import (
    Actor,
    create_calendar,
    create_calendar_event,
    create_document,
    create_guild,
    create_guild_membership,
    create_initiative,
    create_project,
    create_property_definition,
    create_task,
    create_user,
)

# ---------------------------------------------------------------------------
# The surfaces
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Surface:
    """One entity's property endpoints, and how a test gets an entity to hit."""

    kind: str
    #: Path segment under ``/c/{guild}/``.
    path: str
    #: Key the entity's read schema keeps its values under.
    values_key: str
    #: What the endpoint answers for an entity it cannot see.
    not_found_code: str
    value_model: type
    #: The value row's column naming the entity.
    entity_column: str
    #: Whatever ``make`` needs in place inside an initiative.
    parent: Callable[[AsyncSession, Actor, Initiative], Awaitable[Any]]
    #: One entity under that parent, by id.
    make: Callable[[AsyncSession, Actor, Any, str], Awaitable[int]]
    #: The list query keeping only entities whose value equals ``value``.
    filter_query: Callable[[Actor, Any, int, Any], str]


async def _project_in(session, a, initiative):
    return await create_project(session, initiative, a.user, name="P")


async def _make_task(session, a, project, title):
    return (await create_task(session, project, title=title)).id


def _conditions_filter(a, project, property_id, value):
    conditions = json.dumps(
        [
            {"field": "project_id", "op": "eq", "value": project.id},
            {
                "field": "property_values",
                "op": "eq",
                "value": {"property_id": property_id, "value": value},
            },
        ]
    )
    return f"conditions={conditions}"


async def _initiative_itself(session, a, initiative):
    return initiative


async def _make_document(session, a, initiative, title):
    return (await create_document(session, initiative, a.user, name=title)).id


def _property_filters(a, _parent, property_id, value):
    filters = json.dumps([{"property_id": property_id, "op": "eq", "value": value}])
    return f"initiative_id={a.initiative.id}&property_filters={filters}"


async def _calendar_in(session, a, initiative):
    initiative.calendars_enabled = True
    session.add(initiative)
    await session.commit()
    await session.refresh(initiative)
    return await create_calendar(session, initiative, a.user)


async def _make_event(session, a, calendar, title):
    return (await create_calendar_event(session, calendar, a.user, title=title)).id


TASKS = Surface(
    kind="task",
    path="tasks",
    values_key="properties",
    not_found_code="TASK_NOT_FOUND",
    value_model=TaskPropertyValue,
    entity_column="task_id",
    parent=_project_in,
    make=_make_task,
    filter_query=_conditions_filter,
)
DOCUMENTS = Surface(
    kind="document",
    path="documents",
    values_key="properties",
    not_found_code="DOCUMENT_NOT_FOUND",
    value_model=DocumentPropertyValue,
    entity_column="document_id",
    parent=_initiative_itself,
    make=_make_document,
    filter_query=_property_filters,
)
EVENTS = Surface(
    kind="event",
    path="calendar-events",
    values_key="property_values",
    not_found_code="CALENDAR_EVENT_NOT_FOUND",
    value_model=CalendarEventPropertyValue,
    entity_column="event_id",
    parent=_calendar_in,
    make=_make_event,
    filter_query=_property_filters,
)

SURFACES = [TASKS, DOCUMENTS, EVENTS]
surfaces = pytest.mark.parametrize("surface", SURFACES, ids=[s.kind for s in SURFACES])


async def _scene(surface: Surface, session, acting_user) -> tuple[Actor, Any]:
    """An initiative admin and the parent the surface's entities hang off."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    return a, await surface.parent(session, a, a.initiative)


async def _put(client, a: Actor, surface: Surface, entity_id: int, values: list):
    return await client.put(
        a.g(f"/{surface.path}/{entity_id}/properties"),
        headers=a.headers,
        json={"values": values},
    )


def _values(response, surface: Surface) -> dict[int, Any]:
    return {p["property_id"]: p["value"] for p in response.json()[surface.values_key]}


async def _stored(session, surface: Surface, entity_id: int) -> list:
    column = getattr(surface.value_model, surface.entity_column)
    return (
        await session.exec(select(surface.value_model).where(column == entity_id))
    ).all()


async def _listed(client, a: Actor, surface: Surface, parent, defn_id, value) -> set:
    query = surface.filter_query(a, parent, defn_id, value)
    response = await client.get(a.g(f"/{surface.path}/?{query}"), headers=a.headers)
    assert response.status_code == 200
    return {item["id"] for item in response.json()["items"]}


# ---------------------------------------------------------------------------
# Replace-all
# ---------------------------------------------------------------------------


@surfaces
async def test_put_sets_values(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    text = await create_property_definition(
        session, a.initiative, name="Note", type=PropertyType.text
    )
    number = await create_property_definition(
        session, a.initiative, name="Score", type=PropertyType.number
    )

    response = await _put(
        client,
        a,
        surface,
        entity,
        [
            {"property_id": text.id, "value": "alpha"},
            {"property_id": number.id, "value": 7.5},
        ],
    )

    assert response.status_code == 200
    values = _values(response, surface)
    assert values[text.id] == "alpha"
    assert float(values[number.id]) == 7.5


@surfaces
async def test_put_of_nothing_clears_what_was_there(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _put(client, a, surface, entity, [{"property_id": defn.id, "value": "seed"}])

    response = await _put(client, a, surface, entity, [])

    assert response.status_code == 200
    assert response.json()[surface.values_key] == []
    assert await _stored(session, surface, entity) == []


# ---------------------------------------------------------------------------
# Values are held to their definition
# ---------------------------------------------------------------------------


@surfaces
async def test_put_refuses_a_value_the_type_cannot_read(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Count", type=PropertyType.number
    )

    response = await _put(
        client, a, surface, entity, [{"property_id": defn.id, "value": "not a number"}]
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"


@pytest.mark.parametrize(
    ("type_", "value", "accepted"),
    [
        (PropertyType.text, 12345, None),
        (PropertyType.number, "3.14", 3.14),
        (PropertyType.date, "2026-04-22", "2026-04-22"),
        (PropertyType.date, "not-a-date", None),
        (PropertyType.url, "https://example.com", "https://example.com"),
        (PropertyType.url, "not a url", None),
    ],
    ids=["text-number", "number-string", "date", "date-garbage", "url", "url-garbage"],
)
async def test_put_holds_a_value_to_its_type(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    type_: PropertyType,
    value: Any,
    accepted: Any,
):
    """One surface stands for all here: the reading is the engine's."""
    a, parent = await _scene(DOCUMENTS, session, acting_user)
    entity = await DOCUMENTS.make(session, a, parent, "E")
    defn = await create_property_definition(session, a.initiative, name="V", type=type_)

    response = await _put(
        client, a, DOCUMENTS, entity, [{"property_id": defn.id, "value": value}]
    )

    if accepted is None:
        assert response.status_code == 400
        assert response.json()["detail"] == "PROPERTY_INVALID_VALUE_FOR_TYPE"
        return
    assert response.status_code == 200
    stored = _values(response, DOCUMENTS)[defn.id]
    if type_ is PropertyType.number:
        stored = float(stored)
    assert stored == accepted


@pytest.mark.parametrize(
    ("surface", "type_", "value"),
    [
        (TASKS, PropertyType.multi_select, ["a", "ghost"]),
        (DOCUMENTS, PropertyType.multi_select, ["a", "ghost"]),
        (EVENTS, PropertyType.multi_select, ["a", "ghost"]),
        (DOCUMENTS, PropertyType.select, "ghost"),
    ],
    ids=["task-multi_select", "document-multi_select", "event-multi_select", "select"],
)
async def test_put_refuses_an_option_the_definition_lacks(
    client: AsyncClient,
    session: AsyncSession,
    acting_user,
    surface: Surface,
    type_: PropertyType,
    value: Any,
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    defn = await create_property_definition(
        session,
        a.initiative,
        name="Choice",
        type=type_,
        options=[{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
    )

    response = await _put(
        client, a, surface, entity, [{"property_id": defn.id, "value": value}]
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "PROPERTY_OPTION_NOT_IN_DEFINITION"


@surfaces
async def test_put_refuses_a_person_who_cannot_open_it(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    # In the community, not in the initiative.
    outsider = await create_user(session)
    await create_guild_membership(
        session, user=outsider, guild=a.guild, role=GuildRole.member
    )
    defn = await create_property_definition(
        session, a.initiative, name="Owner", type=PropertyType.user_reference
    )

    response = await _put(
        client, a, surface, entity, [{"property_id": defn.id, "value": outsider.id}]
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "PERSON_CANNOT_READ"


# ---------------------------------------------------------------------------
# A definition stays in its initiative; an entity stays in its community
# ---------------------------------------------------------------------------


@surfaces
async def test_put_refuses_a_definition_from_another_initiative(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    entity = await surface.make(session, a, parent, "E")
    elsewhere = await create_initiative(session, a.guild, a.user, name="B")
    foreign = await create_property_definition(session, elsewhere, name="Foreign")

    response = await _put(
        client, a, surface, entity, [{"property_id": foreign.id, "value": "x"}]
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "PROPERTY_DEFINITION_NOT_FOUND"


@surfaces
async def test_put_on_an_entity_of_another_community_is_not_found(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    """Addressed through community A, an entity that lives in B is nobody's."""
    a, _parent = await _scene(surface, session, acting_user)
    guild_b = await create_guild(session, name="B")
    await create_guild_membership(
        session, user=a.user, guild=guild_b, role=GuildRole.admin
    )
    initiative_b = await create_initiative(session, guild_b, a.user, name="Init B")
    parent_b = await surface.parent(session, a, initiative_b)
    entity_b = await surface.make(session, a, parent_b, "B")

    response = await client.put(
        f"/api/v1/c/{a.guild.id}/{surface.path}/{entity_b}/properties",
        headers=a.headers,
        json={"values": []},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == surface.not_found_code


# ---------------------------------------------------------------------------
# The list filters by a value
# ---------------------------------------------------------------------------


@surfaces
async def test_list_filters_by_a_text_value(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    a, parent = await _scene(surface, session, acting_user)
    match = await surface.make(session, a, parent, "Match")
    other = await surface.make(session, a, parent, "Other")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _put(client, a, surface, match, [{"property_id": defn.id, "value": "findme"}])
    await _put(client, a, surface, other, [{"property_id": defn.id, "value": "skip"}])

    listed = await _listed(client, a, surface, parent, defn.id, "findme")

    assert match in listed
    assert other not in listed


@surfaces
async def test_list_filters_by_a_selected_option(
    client: AsyncClient, session: AsyncSession, acting_user, surface: Surface
):
    """A multi-select filter is containment: the option named is among those set."""
    a, parent = await _scene(surface, session, acting_user)
    with_alpha = await surface.make(session, a, parent, "A")
    without = await surface.make(session, a, parent, "N")
    defn = await create_property_definition(
        session,
        a.initiative,
        name="Labels",
        type=PropertyType.multi_select,
        options=[
            {"value": "alpha", "label": "Alpha"},
            {"value": "beta", "label": "Beta"},
            {"value": "gamma", "label": "Gamma"},
        ],
    )
    await _put(
        client,
        a,
        surface,
        with_alpha,
        [{"property_id": defn.id, "value": ["alpha", "beta"]}],
    )
    await _put(
        client, a, surface, without, [{"property_id": defn.id, "value": ["gamma"]}]
    )

    listed = await _listed(client, a, surface, parent, defn.id, ["alpha"])

    assert with_alpha in listed
    assert without not in listed


# ---------------------------------------------------------------------------
# Tasks: values follow a task only within its initiative
# ---------------------------------------------------------------------------


async def test_moving_a_task_to_another_initiative_drops_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, project_a = await _scene(TASKS, session, acting_user)
    init_b = await create_initiative(session, a.guild, a.user, name="B")
    project_b = await create_project(session, init_b, a.user, name="PB")
    task = await _make_task(session, a, project_a, "Mover")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _put(
        client, a, TASKS, task, [{"property_id": defn.id, "value": "beforeMove"}]
    )

    moved = await client.post(
        a.g(f"/tasks/{task}/move"),
        headers=a.headers,
        json={"target_project_id": project_b.id},
    )

    assert moved.status_code == 200
    assert await _stored(session, TASKS, task) == []


async def test_duplicating_a_task_in_its_project_carries_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, project = await _scene(TASKS, session, acting_user)
    task = await _make_task(session, a, project, "Orig")
    defn = await create_property_definition(
        session, a.initiative, name="Tag", type=PropertyType.text
    )
    await _put(client, a, TASKS, task, [{"property_id": defn.id, "value": "carry"}])

    duplicated = await client.post(a.g(f"/tasks/{task}/duplicate"), headers=a.headers)

    assert duplicated.status_code == 201
    assert _values(duplicated, TASKS).get(defn.id) == "carry"
    assert len(await _stored(session, TASKS, duplicated.json()["id"])) == 1


# ---------------------------------------------------------------------------
# Documents: the ``property_filters`` parameter, and copies
# ---------------------------------------------------------------------------


async def test_list_documents_filters_by_a_number(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative = await _scene(DOCUMENTS, session, acting_user)
    defn = await create_property_definition(
        session, initiative, name="Score", type=PropertyType.number
    )
    docs = [await _make_document(session, a, initiative, f"D{n}") for n in range(3)]
    for doc, score in zip(docs, [10, 20, 30]):
        await _put(
            client, a, DOCUMENTS, doc, [{"property_id": defn.id, "value": score}]
        )

    listed = await _listed(client, a, DOCUMENTS, initiative, defn.id, 20)

    assert listed & set(docs) == {docs[1]}


@pytest.mark.parametrize(
    "property_filters",
    [
        "not-json",
        json.dumps([{"property_id": i, "op": "eq", "value": "x"} for i in range(1, 7)]),
    ],
    ids=["not-json", "six-predicates"],
)
async def test_list_documents_refuses_a_filter_it_cannot_take(
    client: AsyncClient, acting_user, property_filters: str
):
    """Malformed, or past the five-predicate cap; the ids need not exist."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(
        a.g(
            f"/documents/?initiative_id={a.initiative.id}"
            f"&property_filters={property_filters}"
        ),
        headers=a.headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "QUERY_INVALID_CONDITIONS"


async def test_duplicating_a_document_in_place_carries_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative = await _scene(DOCUMENTS, session, acting_user)
    doc = await _make_document(session, a, initiative, "Src")
    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )
    await _put(
        client, a, DOCUMENTS, doc, [{"property_id": defn.id, "value": "carryover"}]
    )

    duplicated = await client.post(
        a.g(f"/documents/{doc}/duplicate"), headers=a.headers, json={"name": "Dup"}
    )

    assert duplicated.status_code == 201
    assert _values(duplicated, DOCUMENTS).get(defn.id) == "carryover"
    rows = await _stored(session, DOCUMENTS, duplicated.json()["id"])
    assert [row.property_id for row in rows] == [defn.id]


async def test_copying_a_document_to_another_initiative_drops_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, initiative = await _scene(DOCUMENTS, session, acting_user)
    init_b = await create_initiative(session, a.guild, a.user, name="B")
    doc = await _make_document(session, a, initiative, "Src")
    defn = await create_property_definition(
        session, initiative, name="Tag", type=PropertyType.text
    )
    await _put(client, a, DOCUMENTS, doc, [{"property_id": defn.id, "value": "onlyA"}])

    copied = await client.post(
        a.g(f"/documents/{doc}/copy"),
        headers=a.headers,
        json={"name": "Copied", "target_initiative_id": init_b.id},
    )

    assert copied.status_code == 201
    assert copied.json()["properties"] == []
    assert await _stored(session, DOCUMENTS, copied.json()["id"]) == []
    # The original is untouched.
    assert len(await _stored(session, DOCUMENTS, doc)) == 1


# ---------------------------------------------------------------------------
# Events: an attached-empty row, the read, ``is_null``, and the purge
# ---------------------------------------------------------------------------


async def test_attaching_a_property_to_an_event_without_a_value_keeps_a_row(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, calendar = await _scene(EVENTS, session, acting_user)
    event = await _make_event(session, a, calendar, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Empty", type=PropertyType.text
    )

    response = await _put(
        client, a, EVENTS, event, [{"property_id": defn.id, "value": None}]
    )

    assert response.status_code == 200
    assert len(await _stored(session, EVENTS, event)) == 1


async def test_reading_an_event_embeds_its_values(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, calendar = await _scene(EVENTS, session, acting_user)
    event = await _make_event(session, a, calendar, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Topic", type=PropertyType.text
    )
    await _put(
        client, a, EVENTS, event, [{"property_id": defn.id, "value": "onboarding"}]
    )

    read = await client.get(a.g(f"/calendar-events/{event}"), headers=a.headers)

    assert read.status_code == 200
    assert read.json()["property_values"][0]["value"] == "onboarding"


async def test_list_events_is_null_matches_the_unset(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a, calendar = await _scene(EVENTS, session, acting_user)
    with_value = await _make_event(session, a, calendar, "WithVal")
    without = await _make_event(session, a, calendar, "Blank")
    defn = await create_property_definition(
        session, a.initiative, name="Topic", type=PropertyType.text
    )
    await _put(
        client, a, EVENTS, with_value, [{"property_id": defn.id, "value": "yes"}]
    )

    filters = json.dumps([{"property_id": defn.id, "op": "is_null", "value": True}])
    response = await client.get(
        a.g(
            f"/calendar-events/?initiative_id={a.initiative.id}&property_filters={filters}"
        ),
        headers=a.headers,
    )

    assert response.status_code == 200
    listed = {item["id"] for item in response.json()["items"]}
    assert without in listed
    assert with_value not in listed


async def test_purging_an_initiative_takes_its_event_values_with_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A soft-deleted initiative keeps its rows, so a restore brings everything
    back; the purge is what cascades through the events."""
    a, calendar = await _scene(EVENTS, session, acting_user)
    event = await _make_event(session, a, calendar, "E")
    defn = await create_property_definition(
        session, a.initiative, name="Topic", type=PropertyType.text
    )
    await _put(client, a, EVENTS, event, [{"property_id": defn.id, "value": "hold"}])

    deleted = await client.delete(
        a.g(f"/initiatives/{a.initiative.id}"), headers=a.headers
    )
    assert deleted.status_code in (200, 204)
    assert len(await _stored(session, EVENTS, event)) == 1

    purged = await client.delete(
        a.g(f"/trash/initiative/{a.initiative.id}/purge"), headers=a.headers
    )
    assert purged.status_code == 204
    assert await _stored(session, EVENTS, event) == []
