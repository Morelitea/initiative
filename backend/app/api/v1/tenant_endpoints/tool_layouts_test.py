"""How an instance of a tool draws its items, and who may change it.

Reading follows reading the instance (or being in the initiative, for a shared
tool). Changing a project's layouts takes the right to configure it — its
owner, a manager of the initiative or a guild admin — with write access to it;
changing a shared tool's takes managing the initiative. Each layout changes on
its own, and keeps its own date.
"""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.advisory_locks import LockNamespace, advisory_lock
from app.models.platform.guild import CommunityRole
from app.models.tenant.resource_grant import ResourceAccessLevel
from app.models.tenant.tool_layout import ToolLayout
from app.schemas.tenant.tool_layout import MAX_DEPTH, MAX_NODES, MAX_PLUGIN_PARTS
from app.services.tenant import tool_layouts as tool_layouts_service
from app.testing import create_project, create_resource_grant, route_session_to_guild


def _project(a: Any) -> dict[str, Any]:
    return {"tool": "project", "tool_id": a.project.id}


_FIELD = {"type": "field", "props": {"field": "title"}}


def _card(*children: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "board",
        "definition": {"card": {"type": "card", "children": list(children)}},
    }


_BOARD = _card(
    {
        "type": "stack",
        "props": {"direction": "row", "gap": "sm", "wrap": True},
        "children": [
            _FIELD,
            {"type": "field", "props": {"field": "property:12"}},
            {"type": "properties"},
            {"type": "field", "props": {"field": "plugin:3:ci.state"}},
            {"type": "plugin", "props": {"plugin": 3, "part": "builds"}},
        ],
    }
)
_TABLE = {
    "kind": "table",
    "definition": {
        "columns": ["title", "dueDate", "property:12", "plugin:3:ci.state"],
    },
}
#: A task's layout: the regions left out are drawn as shipped.
_TASK: dict[str, Any] = {
    "kind": "task",
    "definition": {
        "main": [
            {
                "type": "section",
                "props": {"title": "Work", "collapsed": True},
                "children": [
                    {"type": "field", "props": {"field": "description"}},
                    {"type": "plugin", "props": {"plugin": 3, "part": "builds"}},
                ],
            },
            {"type": "comments"},
        ],
    },
}


def _dates(body: dict[str, Any]) -> dict[str, Any]:
    return {layout["kind"]: layout["updated_at"] for layout in body["layouts"]}


async def test_a_project_draws_its_layouts_as_shipped_until_one_changes(
    client: AsyncClient, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.get(a.g("/layouts/"), params=_project(a), headers=a.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["can_configure"] is True
    assert [
        (layout["kind"], layout.get("is_default"), layout["updated_at"])
        for layout in body["layouts"]
    ] == [
        ("table", True, None),
        ("board", False, None),
        ("calendar", False, None),
        ("task", None, None),
    ]


async def test_a_layout_changes_alone_and_goes_back_to_shipped(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    url, params = a.g("/layouts/"), _project(a)

    board = await client.put(url, params=params, json=_BOARD, headers=a.headers)
    assert board.status_code == 200, board.text
    assert (
        board.json() == (await client.get(url, params=params, headers=a.headers)).json()
    )
    board_at = _dates(board.json())["board"]
    assert {kind for kind, at in _dates(board.json()).items() if at} == {"board"}

    task = (await client.put(url, params=params, json=_TASK, headers=a.headers)).json()
    # Laying out the task leaves the board's date where it was.
    assert _dates(task)["board"] == board_at
    (task_layout,) = [layout for layout in task["layouts"] if layout["kind"] == "task"]
    assert task_layout["definition"] == {
        "header": None,
        "side": None,
        **_TASK["definition"],
    }
    # Saved again as it is, the board has not changed.
    same = (await client.put(url, params=params, json=_BOARD, headers=a.headers)).json()
    assert _dates(same)["board"] == board_at

    table = (
        await client.put(url, params=params, json=_TABLE, headers=a.headers)
    ).json()
    assert _dates(table)["table"] is not None
    await route_session_to_guild(session, a.guild.id)
    stored = {
        row.kind: row.definition
        for row in (await session.exec(select(ToolLayout))).all()
    }
    assert stored == {
        "board": _BOARD["definition"],
        "table": _TABLE["definition"],
        "task": _TASK["definition"],
    }

    reset = await client.delete(f"{url}board", params=params, headers=a.headers)
    assert reset.status_code == 200, reset.text
    assert _dates(reset.json())["board"] is None
    assert _dates(reset.json())["task"] == _dates(task)["task"]


async def test_the_list_a_project_opens_on_is_its_own_change(
    client: AsyncClient, acting_user
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.put(
        a.g("/layouts/default"),
        params=_project(a),
        json={"kind": "board"},
        headers=a.headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [
        layout["kind"] for layout in body["layouts"] if layout.get("is_default")
    ] == ["board"]
    assert set(_dates(body).values()) == {None}


async def test_changes_to_a_target_take_turns(
    client: AsyncClient, acting_user, monkeypatch
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    taken: list[tuple[LockNamespace, Any]] = []

    async def recording_lock(conn, namespace, key=None, **kwargs):
        taken.append((namespace, key))
        return await advisory_lock(conn, namespace, key, **kwargs)

    monkeypatch.setattr(tool_layouts_service, "advisory_lock", recording_lock)
    url, params = a.g("/layouts/"), _project(a)

    saved = await client.put(url, params=params, json=_BOARD, headers=a.headers)
    reset = await client.delete(f"{url}board", params=params, headers=a.headers)

    assert (saved.status_code, reset.status_code) == (200, 200)
    key = f"{a.guild.id}:project:{a.project.id}:{a.initiative.id}"
    assert taken == [(LockNamespace.TOOL_LAYOUTS, key)] * 2


@pytest.mark.parametrize("who", ["admin", "manager"])
async def test_an_admin_and_a_manager_with_write_may_configure(
    client: AsyncClient, session: AsyncSession, acting_user, who: str
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    if who == "admin":
        other = await acting_user(guild_role=CommunityRole.admin, guild=owner.guild)
    else:
        other = await acting_user(
            guild_role=CommunityRole.member,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="project_manager",
        )
        # Sharing still decides what a manager may change.
        await create_resource_grant(
            session, owner.project, user=other.user, level=ResourceAccessLevel.write
        )

    response = await client.put(
        other.g("/layouts/"),
        params=_project(owner),
        json=_BOARD,
        headers=other.headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["can_configure"] is True


@pytest.mark.parametrize("level", [ResourceAccessLevel.write, ResourceAccessLevel.read])
async def test_a_member_who_cannot_configure_reads_but_changes_nothing(
    client: AsyncClient, session: AsyncSession, acting_user, level
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    await create_resource_grant(session, owner.project, user=member.user, level=level)
    url, params = member.g("/layouts/"), _project(owner)

    listed = await client.get(url, params=params, headers=member.headers)
    saved = await client.put(url, params=params, json=_BOARD, headers=member.headers)
    opened = await client.put(
        f"{url}default", params=params, json={"kind": "board"}, headers=member.headers
    )
    reset = await client.delete(f"{url}board", params=params, headers=member.headers)

    assert listed.json()["can_configure"] is False
    assert [r.status_code for r in (saved, opened, reset)] == [403] * 3
    assert saved.json()["detail"] == "PROJECT_CONFIGURE_REQUIRED"


async def test_a_non_member_of_the_initiative_reads_nothing(
    client: AsyncClient, acting_user, reading_as
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)
    url, params = owner.g("/layouts/"), _project(owner)
    assert (
        await client.put(url, params=params, json=_BOARD, headers=owner.headers)
    ).status_code == 200

    listed = await client.get(url, params=params, headers=outsider.headers)
    saved = await client.put(url, params=params, json=_BOARD, headers=outsider.headers)
    assert (listed.status_code, saved.status_code) == (404, 404)

    for user, seen in ((outsider.user, 0), (owner.user, 1)):
        reader = await reading_as(user.id, owner.guild.id)
        assert len((await reader.exec(select(ToolLayout.id))).all()) == seen


async def test_an_initiatives_layouts_list_each_project_the_reader_can_open(
    client: AsyncClient, session: AsyncSession, acting_user
):
    manager = await acting_user(
        guild_role=CommunityRole.member,
        initiative=True,
        project=True,
        initiative_role="project_manager",
    )
    closed = await create_project(
        session, manager.initiative, manager.user, name="Zeta"
    )
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=manager.guild,
        initiative=manager.initiative,
        initiative_role="member",
    )
    await create_resource_grant(
        session, manager.project, user=member.user, level=ResourceAccessLevel.read
    )
    assert (
        await client.put(
            manager.g("/layouts/"),
            params=_project(manager),
            json=_TASK,
            headers=manager.headers,
        )
    ).status_code == 200
    url, params = (
        manager.g("/layouts/initiative"),
        {"initiative_id": manager.initiative.id},
    )

    seen = (await client.get(url, params=params, headers=manager.headers)).json()
    read = (await client.get(url, params=params, headers=member.headers)).json()

    assert [
        (each["tool_id"], [kind for kind, at in _dates(each).items() if at])
        for each in seen
    ] == [(manager.project.id, ["task"]), (closed.id, [])]
    assert all(each["can_configure"] for each in seen)
    # A member reads only what they were let into, and changes none of it.
    assert [(each["tool_id"], each["can_configure"]) for each in read] == [
        (manager.project.id, False)
    ]


async def test_an_initiatives_layouts_are_not_listed_outside_it(
    client: AsyncClient, acting_user
):
    owner = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=CommunityRole.member, guild=owner.guild)

    response = await client.get(
        outsider.g("/layouts/initiative"),
        params={"initiative_id": owner.initiative.id},
        headers=outsider.headers,
    )

    assert response.status_code == 404


def _deep(depth: int) -> dict[str, Any]:
    """A branch ``depth`` parts deep under a card."""
    node: dict[str, Any] = _FIELD
    for _ in range(depth - 1):
        node = {"type": "stack", "children": [node]}
    return node


def _field(field: str) -> dict[str, Any]:
    return {"type": "field", "props": {"field": field}}


def _plugin_part(plugin: int) -> dict[str, Any]:
    return {"type": "plugin", "props": {"plugin": plugin, "part": "builds"}}


def _table(**definition: Any) -> dict[str, Any]:
    return {"kind": "table", "definition": definition}


_SORT = {"field": "due_date", "dir": "desc"}


def _preset(slug: str = "mine", **preset: Any) -> dict[str, Any]:
    return {"name": "Mine", "slug": slug, **preset}


def _task(*side: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "task", "definition": {"side": list(side)}}


@pytest.mark.parametrize(
    ("payload", "status", "detail"),
    [
        (_card({"type": "widget"}), 422, None),
        (_card({"type": "field", "props": {"field": "colour"}}), 422, None),
        (_table(columns=["property:Size"]), 422, None),
        (_table(columns=["plugin:3:CI"]), 422, None),
        (_card({"type": "comments"}), 422, None),
        (_table(columns=["assignees"]), 422, None),
        (_table(sort=[{"field": "dueDate"}]), 422, None),
        (_table(filters={"assignees": ["me"]}), 422, None),
        (_table(presets=[_preset(), _preset()]), 422, None),
        (_table(presets=[_preset("Mine!")]), 422, None),
        (_table(presets=[_preset(filters={"assignees": ["bob"]})]), 422, None),
        (
            {"kind": "board", "definition": {"presets": [_preset(sort=[_SORT])]}},
            400,
            "TOOL_LAYOUTS_KIND_NOT_ALLOWED",
        ),
        (
            _table(presets=[_preset(filters={"priorities": ["high"]})]),
            400,
            "TOOL_LAYOUTS_KIND_NOT_ALLOWED",
        ),
        (_task({"type": "field", "props": {"field": "startDate"}}), 422, None),
        (_task({"type": "field", "props": {"field": "property:12"}}), 422, None),
        (_task({"type": "card"}), 422, None),
        ({"kind": "gallery", "definition": {}}, 422, None),
        (_table(columns=["plugin:x:ci"]), 422, None),
        (_card({"type": "plugin", "props": {"plugin": 3}}), 422, None),
        (
            _card(*[_plugin_part(3)] * (MAX_PLUGIN_PARTS + 1)),
            400,
            "TOOL_LAYOUTS_TOO_MANY_PLUGIN_PARTS",
        ),
        (_card(*[_FIELD] * MAX_NODES), 400, "TOOL_LAYOUTS_TOO_LARGE"),
        (_card(_deep(MAX_DEPTH)), 400, "TOOL_LAYOUTS_TOO_LARGE"),
    ],
    ids=[
        "unknown part",
        "unknown field",
        "a property by name",
        "a plug-in field outside the key's characters",
        "a task's part on a card",
        "a column the table cannot draw",
        "a sort, which is a person's",
        "filters, which are a person's",
        "two presets with one slug",
        "a preset's slug outside its characters",
        "a preset naming someone by name",
        "a sort on a board's preset, which a board does not sort by",
        "a project's preset in the calendar's filters",
        "a date alone on a task",
        "a property alone on a task",
        "a card on a task",
        "a kind no tool draws",
        "a plug-in field by name",
        "a plug-in part with no part",
        "too many of one plug-in's parts",
        "too many nodes",
        "too deep",
    ],
)
async def test_a_layout_is_refused_unless_every_part_is_one_we_draw(
    client: AsyncClient, acting_user, payload, status: int, detail: str | None
):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )

    response = await client.put(
        a.g("/layouts/"), params=_project(a), json=payload, headers=a.headers
    )

    assert response.status_code == status, response.text
    if detail is not None:
        assert response.json()["detail"] == detail


async def test_a_list_offers_the_presets_it_keeps(client: AsyncClient, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    url = a.g("/layouts/")
    mine = _preset(filters={"assignees": ["me"]}, sort=[_SORT])
    unassigned = _preset(
        "unassigned",
        name="Unassigned",
        filters={"assignees": ["none"], "due": "overdue"},
    )

    for definition in ({"presets": [mine, unassigned]}, {"presets": []}):
        saved = await client.put(
            url,
            params=_project(a),
            json={"kind": "table", "definition": definition},
            headers=a.headers,
        )
        assert saved.status_code == 200, saved.text
        [table] = [each for each in saved.json()["layouts"] if each["kind"] == "table"]
        presets = table["definition"]["presets"]
        # Kept as written, with what was left out filled in; none is none, not
        # the shipped ones.
        assert [(p["slug"], p["filters"]["assignees"], p["sort"]) for p in presets] == [
            (p["slug"], p["filters"]["assignees"], p.get("sort", []))
            for p in definition["presets"]
        ]


@pytest.mark.parametrize("same_initiative", [True, False])
def test_a_copy_keeps_its_presets_filters_where_they_still_mean_something(
    same_initiative: bool,
):
    filters = {
        "status_ids": [1, 2],
        "properties": [{"property_id": 9, "op": "eq", "value": "red"}],
    }
    definition = {"presets": [_preset(filters=filters)]}

    copied = tool_layouts_service.copied_definition(
        definition, {1: 11}, same_initiative=same_initiative
    )

    # Statuses are the copy's own, and one it lacks is dropped; properties
    # are the initiative's, so only a copy beside the project keeps them.
    [preset] = copied["presets"]
    assert preset["filters"]["status_ids"] == [11]
    assert preset["filters"]["properties"] == (
        filters["properties"] if same_initiative else []
    )


async def test_a_layout_at_the_limits_is_kept(client: AsyncClient, acting_user):
    a = await acting_user(
        guild_role=CommunityRole.member, initiative=True, project=True
    )
    # The card, a branch to the deepest part, and the rest beside it, among
    # them as many of each of two plug-ins' parts as one plug-in may place.
    parts = [_plugin_part(plugin) for plugin in (3, 4) for _ in range(MAX_PLUGIN_PARTS)]
    card = _card(
        _deep(MAX_DEPTH - 1),
        *parts,
        *[_FIELD] * (MAX_NODES - MAX_DEPTH - len(parts)),
    )

    response = await client.put(
        a.g("/layouts/"), params=_project(a), json=card, headers=a.headers
    )

    assert response.status_code == 200, response.text


async def test_purging_a_project_takes_its_layouts(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    await client.put(
        a.g("/layouts/"), params=_project(a), json=_BOARD, headers=a.headers
    )

    trashed = await client.delete(a.g(f"/projects/{a.project.id}"), headers=a.headers)
    assert trashed.status_code == 204, trashed.text
    purged = await client.delete(
        a.g(f"/trash/project/{a.project.id}/purge"), headers=a.headers
    )

    assert purged.status_code == 204, purged.text
    await route_session_to_guild(session, a.guild.id)
    assert (await session.exec(select(ToolLayout.id))).all() == []


async def test_a_shared_tool_is_laid_out_by_the_initiatives_managers(
    client: AsyncClient, acting_user, reading_as
):
    manager = await acting_user(guild_role=CommunityRole.member, initiative=True)
    member = await acting_user(
        guild_role=CommunityRole.member,
        guild=manager.guild,
        initiative=manager.initiative,
        initiative_role="member",
    )
    url = manager.g("/layouts/")
    params = {"tool": "calendar", "initiative_id": manager.initiative.id}
    calendar = {"kind": "calendar", "definition": {}}

    async def can_configure(actor: Any) -> bool:
        response = await client.get(url, params=params, headers=actor.headers)
        assert response.status_code == 200, response.text
        assert [layout["kind"] for layout in response.json()["layouts"]] == [
            "calendar",
            "calendar_event",
        ]
        return response.json()["can_configure"]

    assert (await can_configure(manager), await can_configure(member)) == (True, False)
    refused = await client.put(
        url, params=params, json=calendar, headers=member.headers
    )
    assert refused.json()["detail"] == "INITIATIVE_MANAGER_REQUIRED"
    saved = await client.put(url, params=params, json=calendar, headers=manager.headers)
    assert saved.status_code == 200, saved.text
    urgent = _preset("urgent", name="Urgent", filters={"priorities": ["urgent"]})
    with_preset = {"kind": "calendar", "definition": {"presets": [urgent]}}
    saved = await client.put(
        url, params=params, json=with_preset, headers=manager.headers
    )
    assert saved.status_code == 200, saved.text
    [kept] = saved.json()["layouts"][0]["definition"]["presets"]
    assert kept["filters"]["priorities"] == ["urgent"]
    # The calendar draws none of a project's other kinds.
    for wrong in (
        await client.put(url, params=params, json=_BOARD, headers=manager.headers),
        await client.put(url, params=params, json=_TASK, headers=manager.headers),
        # The calendar's presets hold its own filters, which name no one.
        await client.put(
            url,
            params=params,
            json={
                "kind": "calendar",
                "definition": {"presets": [_preset(filters={"assignees": ["me"]})]},
            },
            headers=manager.headers,
        ),
        await client.delete(f"{url}task", params=params, headers=manager.headers),
    ):
        assert wrong.json()["detail"] == "TOOL_LAYOUTS_KIND_NOT_ALLOWED"

    def row(kind: str) -> ToolLayout:
        return ToolLayout(
            initiative_id=manager.initiative.id,
            tool="calendar",
            kind=kind,
            definition={"kind": "calendar"} if kind == "default" else {},
        )

    writer = await reading_as(manager.user.id, manager.guild.id)
    writer.add(row("default"))
    await writer.commit()
    # A kind of its own, so only the row's policy can refuse it.
    await client.delete(f"{url}calendar", params=params, headers=manager.headers)
    outsider = await reading_as(member.user.id, member.guild.id)
    outsider.add(row("calendar"))
    with pytest.raises(DBAPIError):
        await outsider.commit()


def _detail(kind: str, *side: dict[str, Any]) -> dict[str, Any]:
    return {"kind": kind, "definition": {"side": list(side)}}


@pytest.mark.parametrize(
    ("target", "payload"),
    [
        ("calendar", _detail("calendar_event", {"type": "status"})),
        (
            "calendar",
            _detail(
                "calendar_event",
                {"type": "section", "children": [_field("checklist")]},
            ),
        ),
        ("calendar", _detail("calendar_event", _plugin_part(3))),
        ("calendar", _detail("calendar_event", _field("plugin:3:ci.state"))),
        ("project", _detail("task", {"type": "rsvp"})),
        ("project", _detail("task", _field("location"))),
        ("project", _detail("calendar_event")),
    ],
    ids=[
        "a task's part on an event",
        "a task's field on an event",
        "a plug-in's part on an event",
        "a plug-in's field on an event",
        "an event's part on a task",
        "an event's field on a task",
        "an event's detail on a project",
    ],
)
async def test_a_detail_draws_only_what_its_kind_has(
    client: AsyncClient, acting_user, target: str, payload: dict[str, Any]
):
    a = await acting_user(guild_role=CommunityRole.admin, initiative=True, project=True)
    params = (
        _project(a)
        if target == "project"
        else {"tool": "calendar", "initiative_id": a.initiative.id}
    )

    response = await client.put(
        a.g("/layouts/"), params=params, json=payload, headers=a.headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "TOOL_LAYOUTS_KIND_NOT_ALLOWED"


async def test_the_calendar_lays_out_its_event_detail(client: AsyncClient, acting_user):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)
    params = {"tool": "calendar", "initiative_id": a.initiative.id}
    event = _detail(
        "calendar_event",
        {"type": "rsvp"},
        {"type": "section", "children": [{"type": "dates"}, _field("location")]},
    )

    saved = await client.put(
        a.g("/layouts/"), params=params, json=event, headers=a.headers
    )

    assert saved.status_code == 200, saved.text
    layout = {each["kind"]: each for each in saved.json()["layouts"]}["calendar_event"]
    assert [part["type"] for part in layout["definition"]["side"]] == [
        "rsvp",
        "section",
    ]
    assert layout["updated_at"] is not None


@pytest.mark.parametrize(
    "params",
    [
        {"tool": "project"},
        {"tool": "calendar", "tool_id": 1},
        {"tool": "wiki", "tool_id": 1},
    ],
    ids=["no instance", "an instance of a shared tool", "a tool with no layouts"],
)
async def test_a_target_must_name_what_its_tool_takes(
    client: AsyncClient, acting_user, params: dict[str, Any]
):
    a = await acting_user(guild_role=CommunityRole.member, initiative=True)

    response = await client.get(a.g("/layouts/"), params=params, headers=a.headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "TOOL_LAYOUTS_TARGET_INVALID"
