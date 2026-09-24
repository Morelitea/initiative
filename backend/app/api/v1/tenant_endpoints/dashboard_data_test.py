"""A canvas answered at once: ``GET /dashboards/{id}/data``.

The one statement the canvas compiles to has to say exactly what each widget
says on its own, to exactly the same reader. The first test holds that for the
shapes a canvas holds; the rest hold the ways a canvas load differs from one
widget's: a failing widget does not take the others with it, and a guild with
no free slot refuses the canvas as a whole.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.messages import QueryMessages
from app.models.platform.guild import GuildRole
from app.models.tenant.task import TaskStatusCategory
from app.services.query import executor
from app.services.tenant.published_views_test import dashboard_body, dashboards_on
from app.testing import create_project, create_task

pytestmark = pytest.mark.integration


async def _canvas(client, actor, *statements: str) -> int:
    response = await client.post(
        actor.g("/dashboards/"),
        json={
            "name": "Canvas",
            "initiative_id": actor.initiative.id,
            "definition": dashboard_body(*statements),
        },
        headers=actor.headers,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _data(client, actor, dashboard_id: int) -> dict:
    response = await client.get(
        actor.g(f"/dashboards/{dashboard_id}/data"), headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["widgets"]


async def _one(client, actor, dashboard_id: int, widget_id: str) -> dict:
    response = await client.get(
        actor.g(f"/dashboards/{dashboard_id}/widgets/{widget_id}/query"),
        headers=actor.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _author_with_tasks(session, acting_user):
    author = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await dashboards_on(session, author.initiative)
    project = await create_project(session, author.initiative, author.user)
    for offset, category in enumerate(
        (TaskStatusCategory.todo, TaskStatusCategory.todo, TaskStatusCategory.done)
    ):
        await create_task(
            session,
            project,
            title=f"Task {offset}",
            status_category=category,
            due_date=datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=offset),
        )
    return author, project


async def test_the_canvas_answers_what_each_widget_answers(
    client, session, acting_user, monkeypatch
):
    author, _ = await _author_with_tasks(session, acting_user)
    statements = (
        "SELECT count(*) AS n FROM tasks",
        "SELECT priority, count(*) AS n FROM tasks GROUP BY priority",
        "SELECT title, due_date, created_at FROM tasks ORDER BY due_date LIMIT 2",
        "SELECT title FROM tasks WHERE status.category = 'done'",
        "SELECT status.name AS s, count(*) AS n FROM tasks GROUP BY status.name",
        "SELECT t.id, p.id FROM tasks AS t JOIN projects AS p ON p.id = t.project_id",
        "SELECT count(*) AS n FROM projects",
    )
    dashboard_id = await _canvas(client, author, *statements)

    # Answered by the compiled statement, not by the widget-at-a-time fallback,
    # which would agree with the comparison below by construction.
    async def fell_back(*_args, **_kwargs):
        raise AssertionError("the canvas fell back to one widget at a time")

    with monkeypatch.context() as patched:
        patched.setattr(executor, "execute", fell_back)
        canvas = await _data(client, author, dashboard_id)

    assert set(canvas) == {f"w{index + 1}" for index in range(len(statements))}
    for widget_id, entry in canvas.items():
        assert entry["error"] is None, (widget_id, entry)
        assert entry["result"] == await _one(client, author, dashboard_id, widget_id)
    assert canvas["w1"]["result"]["rows"] == [[3]]


async def test_a_reader_sees_their_own_rows_and_what_is_published(
    client, session, acting_user
):
    author, project = await _author_with_tasks(session, acting_user)
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=author.guild,
        initiative=author.initiative,
        initiative_role="member",
    )
    dashboard_id = await _canvas(
        client,
        author,
        "SELECT count(*) AS n FROM tasks",
        "SELECT count(*) AS n FROM tasks WHERE status.category = 'done'",
    )

    before = await _data(client, reader, dashboard_id)
    assert [before[w]["result"]["rows"] for w in ("w1", "w2")] == [[[0]], [[0]]]

    published = await client.put(
        author.g(f"/dashboards/{dashboard_id}/published"),
        json={"resources": [{"resource_type": "project", "resource_id": project.id}]},
        headers=author.headers,
    )
    assert published.status_code == 200, published.text

    after = await _data(client, reader, dashboard_id)
    assert [after[w]["result"]["rows"] for w in ("w1", "w2")] == [[[3]], [[1]]]


async def test_a_widget_that_fails_does_not_blank_the_canvas(
    client, session, acting_user
):
    author, _ = await _author_with_tasks(session, acting_user)
    dashboard_id = await _canvas(
        client,
        author,
        "SELECT count(*) AS n FROM tasks",
        "SELECT 1 / (count(*) - count(*)) AS broken FROM tasks",
    )

    canvas = await _data(client, author, dashboard_id)

    assert canvas["w1"]["result"]["rows"] == [[3]]
    assert canvas["w2"] == {"result": None, "error": QueryMessages.EXECUTION_FAILED}


async def test_a_guild_with_no_free_slot_refuses_the_canvas(
    client, session, acting_user, monkeypatch
):
    author, _ = await _author_with_tasks(session, acting_user)
    dashboard_id = await _canvas(client, author, "SELECT count(*) AS n FROM tasks")

    async def taken(_connection, _guild_id):
        return False

    monkeypatch.setattr(executor, "_claim_a_slot", taken)
    response = await client.get(
        author.g(f"/dashboards/{dashboard_id}/data"), headers=author.headers
    )
    assert response.status_code == 429
    assert response.json()["detail"] == QueryMessages.BUSY
