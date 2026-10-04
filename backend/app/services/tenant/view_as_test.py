"""A dashboard that shows everybody its owner's view.

Two people, one dashboard, and a project only one of them can open: the shape
of every test here.
"""

from __future__ import annotations

from app.core.messages import DashboardMessages
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserStatus
from app.services.tenant.published_views_test import (
    COUNT_TASKS,
    dashboard_body,
    dashboards_on,
    make_dashboard,
    widget_rows,
)
from app.testing import create_project, create_task


async def two_people(session, acting_user):
    """An admin who owns a private project with two tasks, and a member of the
    same initiative who cannot open it."""
    owner = await acting_user(guild_role=GuildRole.admin, initiative=True)
    await dashboards_on(session, owner.initiative)
    reader = await acting_user(
        guild_role=GuildRole.member,
        guild=owner.guild,
        initiative=owner.initiative,
        initiative_role="member",
    )
    project = await create_project(session, owner.initiative, owner.user)
    await create_task(session, project)
    await create_task(session, project)
    return owner, reader


async def set_mode(client, actor, dashboard_id: int, mode: str):
    return await client.put(
        actor.g(f"/dashboards/{dashboard_id}/view-as"),
        json={"mode": mode},
        headers=actor.headers,
    )


async def canvas_rows(client, actor, dashboard_id: int):
    response = await client.get(
        actor.g(f"/dashboards/{dashboard_id}/data"), headers=actor.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["widgets"]["w1"]["result"]["rows"]


class TestWhatAReaderSees:
    async def test_the_owner_view_is_shown_to_every_reader(
        self, client, session, acting_user
    ):
        owner, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, owner)
        assert await widget_rows(client, reader, dashboard_id) == [[0]]

        response = await set_mode(client, owner, dashboard_id, "owner")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["view_as_user_id"] == owner.user.id
        assert body["view_as_active"] is True

        assert await widget_rows(client, reader, dashboard_id) == [[2]]
        assert await canvas_rows(client, reader, dashboard_id) == [[2]]

        back = await set_mode(client, owner, dashboard_id, "viewer")
        assert back.status_code == 200
        assert back.json()["view_as_user_id"] is None
        assert await widget_rows(client, reader, dashboard_id) == [[0]]

    async def test_it_answers_nowhere_but_that_dashboard(
        self, client, session, acting_user
    ):
        owner, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, owner)
        await set_mode(client, owner, dashboard_id, "owner")

        direct = await client.post(
            reader.g("/query"),
            json={"sql": COUNT_TASKS, "initiative_id": owner.initiative.id},
            headers=reader.headers,
        )
        assert direct.status_code == 200
        assert direct.json()["rows"] == [[0]]
        other = await make_dashboard(client, owner)
        assert await widget_rows(client, reader, other) == [[0]]

    async def test_me_is_the_owner(self, client, session, acting_user):
        """The view shown is the owner's, so the reader the statement names is
        them too."""
        owner, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(
            client, owner, "SELECT count(*) AS n FROM tasks WHERE created_by = me"
        )
        await set_mode(client, owner, dashboard_id, "owner")
        own = await widget_rows(client, owner, dashboard_id)
        assert await widget_rows(client, reader, dashboard_id) == own


class TestWhoMayChooseIt:
    async def test_a_reader_cannot_turn_it_on(self, client, session, acting_user):
        owner, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, owner)
        response = await set_mode(client, reader, dashboard_id, "owner")
        assert response.status_code in (403, 404)

    async def test_an_editor_shows_only_their_own_view(
        self, client, session, acting_user
    ):
        """Turning it on names the person doing it; there is no way to name
        anybody else."""
        owner, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, owner)
        await client.put(
            owner.g(f"/dashboards/{dashboard_id}/grants"),
            json=[{"user_id": reader.user.id, "level": "write"}],
            headers=owner.headers,
        )
        response = await set_mode(client, reader, dashboard_id, "owner")
        assert response.status_code == 200, response.text
        assert response.json()["view_as_user_id"] == reader.user.id
        assert await widget_rows(client, owner, dashboard_id) == [[0]]

    async def test_only_the_owner_changes_the_widgets(
        self, client, session, acting_user
    ):
        owner, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, owner)
        await client.put(
            owner.g(f"/dashboards/{dashboard_id}/grants"),
            json=[{"user_id": reader.user.id, "level": "write"}],
            headers=owner.headers,
        )
        await set_mode(client, owner, dashboard_id, "owner")

        edit = await client.patch(
            reader.g(f"/dashboards/{dashboard_id}"),
            json={"definition": dashboard_body("SELECT title FROM tasks")},
            headers=reader.headers,
        )
        assert edit.status_code == 403
        assert edit.json()["detail"] == DashboardMessages.VIEW_AS_EDIT_OWNER_ONLY

        # A rename is not what the widgets ask, and is allowed.
        rename = await client.patch(
            reader.g(f"/dashboards/{dashboard_id}"),
            json={"name": "Renamed"},
            headers=reader.headers,
        )
        assert rename.status_code == 200, rename.text

        # The owner may change them.
        own_edit = await client.patch(
            owner.g(f"/dashboards/{dashboard_id}"),
            json={"definition": dashboard_body("SELECT count(*) AS n FROM projects")},
            headers=owner.headers,
        )
        assert own_edit.status_code == 200, own_edit.text

        # And the other editor can switch it back, then edit.
        assert (
            await set_mode(client, reader, dashboard_id, "viewer")
        ).status_code == 200
        edit = await client.patch(
            reader.g(f"/dashboards/{dashboard_id}"),
            json={"definition": dashboard_body("SELECT title FROM tasks")},
            headers=reader.headers,
        )
        assert edit.status_code == 200, edit.text


class TestItFailsClosedOnTheOwner:
    async def test_a_suspended_owner_shows_nothing_of_theirs(
        self, client, session, acting_user
    ):
        owner, reader = await two_people(session, acting_user)
        dashboard_id = await make_dashboard(client, owner)
        await set_mode(client, owner, dashboard_id, "owner")
        assert await widget_rows(client, reader, dashboard_id) == [[2]]

        owner.user.status = UserStatus.suspended
        session.add(owner.user)
        await session.commit()

        assert await widget_rows(client, reader, dashboard_id) == [[0]]
        detail = await client.get(
            reader.g(f"/dashboards/{dashboard_id}"), headers=reader.headers
        )
        assert detail.json()["view_as_active"] is False
        assert detail.json()["view_as_user_id"] == owner.user.id

    async def test_an_owner_who_left_shows_nothing_of_theirs(
        self, client, session, acting_user
    ):
        owner, reader = await two_people(session, acting_user)
        admin = await acting_user(
            guild_role=GuildRole.admin,
            guild=owner.guild,
            initiative=owner.initiative,
            initiative_role="member",
        )
        dashboard_id = await make_dashboard(client, admin)
        await set_mode(client, admin, dashboard_id, "owner")
        assert await widget_rows(client, reader, dashboard_id) == [[2]]

        await session.delete(admin.membership)
        await session.commit()

        assert await widget_rows(client, reader, dashboard_id) == [[0]]
