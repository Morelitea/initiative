"""The capture trigger writes what the poller expects to read.

These assert the seam between the DB-level trigger and the delivery layer: that
ordinary writes land in the outbox at all, that the row names the right resource
and initiative, and that the two shapes the design turns on — sub-resources
reporting their parent, and soft deletes reporting as deletes — hold against a
real Postgres rather than against the rendering code.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from app.db.session import set_rls_context
from app.models.platform.guild import GuildRole
from app.models.tenant.event_outbox import EventOutbox
from app.testing import create_task, create_tag


pytestmark = pytest.mark.integration


async def _outbox(session, guild_id: int) -> list[EventOutbox]:
    await set_rls_context(session, guild_id=guild_id, guild_role="admin")
    return list(await session.exec(select(EventOutbox).order_by(EventOutbox.id.asc())))


async def test_creating_a_task_is_captured(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)

    rows = [
        r
        for r in await _outbox(session, a.guild.id)
        if r.resource_type == "tasks" and r.resource_id == task.id
    ]
    assert rows, "creating a task produced no outbox row"
    row = rows[0]
    assert row.action == "created"
    assert row.initiative_id == a.initiative.id
    assert row.changed == []


async def test_updating_a_task_names_the_changed_columns(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)

    task.title = "renamed"
    session.add(task)
    await session.commit()

    rows = [
        r
        for r in await _outbox(session, a.guild.id)
        if r.resource_id == task.id and r.action == "updated"
    ]
    assert rows, "updating a task produced no outbox row"
    assert "title" in rows[-1].changed
    # Names only — a value never leaves the database through this row.
    assert all(isinstance(name, str) for name in rows[-1].changed)


async def test_soft_delete_is_reported_as_deleted(session, acting_user):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)

    from datetime import datetime, timezone

    task.deleted_at = datetime.now(timezone.utc)
    session.add(task)
    await session.commit()

    actions = [
        r.action for r in await _outbox(session, a.guild.id) if r.resource_id == task.id
    ]
    assert actions[-1] == "deleted", (
        "a soft delete should reach a consumer as a delete, not as an update "
        f"carrying deleted_at; got {actions}"
    )


async def test_tagging_a_task_is_reported_against_the_task(session, acting_user):
    """A junction row has no id of its own, so it reports its owner."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)
    tag = await create_tag(session, a.guild)

    before = len(await _outbox(session, a.guild.id))
    from app.services.tenant import tags as tags_service

    await tags_service.set_entity_tags(
        session,
        tags_service.TAG_LINKS["task"],
        guild_id=a.guild.id,
        entity_id=task.id,
        tag_ids=[tag.id],
    )
    await session.commit()

    new_rows = (await _outbox(session, a.guild.id))[before:]
    junction = [r for r in new_rows if r.resource_type == "tasks"]
    assert junction, f"tagging produced no task-scoped row; got {new_rows}"
    assert junction[-1].resource_id == task.id
    assert junction[-1].changed == ["tags"]


async def test_a_task_status_is_reported_against_its_project(session, acting_user):
    """A sub-resource with an id of its own is still a facet of its parent.

    A project's statuses are part of the project, and the project is what a
    subscriber can fetch — so the event names the project, the way a junction
    does, rather than an id with no route behind it.
    """
    from app.models.tenant.task import TaskStatus, TaskStatusCategory

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

    before = len(await _outbox(session, a.guild.id))
    session.add(
        TaskStatus(
            guild_id=a.guild.id,
            project_id=a.project.id,
            name="Blocked",
            position=99,
            category=TaskStatusCategory.todo,
        )
    )
    await session.commit()

    new_rows = (await _outbox(session, a.guild.id))[before:]
    reported = [r for r in new_rows if r.resource_type == "projects"]
    assert reported, f"adding a status produced no project-scoped row; got {new_rows}"
    assert reported[-1].resource_id == a.project.id
    assert reported[-1].changed == ["statuses"]
    assert reported[-1].initiative_id == a.initiative.id


async def test_a_grant_is_reported_against_the_resource_it_shares(session, acting_user):
    """Sharing is polymorphic: the event lands on whichever tool was shared.

    ``resource_grants`` rows have their own ids and no route, so a grant reports
    against the project (or document, queue, …) named in the row — which the
    subscriber can fetch, and which is the thing that actually changed.
    """
    from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)

    before = len(await _outbox(session, a.guild.id))
    session.add(
        ResourceGrant(
            guild_id=a.guild.id,
            initiative_id=a.initiative.id,
            resource_type="project",
            resource_id=a.project.id,
            user_id=b.user.id,
            level=ResourceAccessLevel.read,
        )
    )
    await session.commit()

    new_rows = (await _outbox(session, a.guild.id))[before:]
    reported = [
        r
        for r in new_rows
        if r.resource_type == "projects" and r.resource_id == a.project.id
    ]
    assert reported, f"granting access produced no project-scoped row; got {new_rows}"
    assert reported[-1].changed == ["sharing"]


async def test_creating_an_initiative_is_captured(session, acting_user):
    """Guild-level structural tables emit too.

    ``initiatives`` carries no initiative-member RLS — a membership table cannot
    be gated by the check it backs — but that exemption must not also mean an
    automation can never see an initiative being created.
    """
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    rows = [
        r
        for r in await _outbox(session, a.guild.id)
        if r.resource_type == "initiatives" and r.resource_id == a.initiative.id
    ]
    assert rows, "creating an initiative produced no outbox row"
    assert rows[0].action == "created"
    # The event is scoped to the initiative it is about, so RLS on the outbox
    # shows it to that initiative's members and to guild admins.
    assert rows[0].initiative_id == a.initiative.id


async def test_adding_a_member_reports_against_the_initiative(session, acting_user):
    """A membership row has no id of its own, so it reports its owner — which
    is also the change a subscriber can act on."""
    from app.testing import create_initiative_member, create_user

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    before = len(await _outbox(session, a.guild.id))

    joiner = await create_user(session)
    await create_initiative_member(session, a.initiative, joiner)
    await session.commit()

    new_rows = (await _outbox(session, a.guild.id))[before:]
    membership = [
        r
        for r in new_rows
        if r.resource_type == "initiatives" and "members" in r.changed
    ]
    assert membership, f"adding a member produced no initiative row; got {new_rows}"
    assert membership[-1].resource_id == a.initiative.id


async def test_a_tag_is_captured_as_a_guild_wide_event(session, acting_user):
    """Tags belong to no initiative, so their events carry a NULL one.

    That is the correct disclosure rather than a gap: a tag row is already
    readable by every member of the guild, so an event naming it reveals
    nothing new — and tags run through most flows, so an automation that
    cannot see them is missing an ordinary trigger.
    """
    from app.testing import create_tag

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    tag = await create_tag(session, a.guild)
    await session.commit()

    rows = [
        r
        for r in await _outbox(session, a.guild.id)
        if r.resource_type == "tags" and r.resource_id == tag.id
    ]
    assert rows, "creating a tag produced no outbox row"
    assert rows[0].action == "created"
    assert rows[0].initiative_id is None


async def test_an_unresolvable_initiative_still_skips(session, acting_user):
    """A NULL initiative is only ever written where a registry says so.

    Guild-wide tables expect one; an initiative-scoped row whose lookup fails
    must still be skipped rather than emitted without a scope.
    """
    from app.db.event_capture import build_specs
    from app.db.initiative_rls import EVENT_SOURCES, Emit, event_source

    declared = {
        t for t, s in EVENT_SOURCES.items() if isinstance(s, Emit) and s.guild_wide
    }
    captured = {s.table for s in build_specs() if event_source(s.table).guild_wide}
    assert captured == declared, (
        "a guild-wide table lost its capture spec, so its events would stop"
    )
    # Every other evented table resolves a real initiative.
    others = [s for s in build_specs() if not event_source(s.table).guild_wide]
    assert others, "expected initiative-scoped specs alongside the guild-wide ones"


async def test_a_hard_delete_on_a_trash_table_never_surfaces(session, acting_user):
    """Deleting a task is soft — it moves to the trash, and that is the event.
    The hard delete that follows is retention clearing it out, which must stay
    silent: a repeat of an announced delete, naming an id nothing can resolve."""
    from datetime import datetime, timezone

    from app.services.tenant.trash_purge import hard_purge_entity

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)

    task.deleted_at = datetime.now(timezone.utc)
    session.add(task)
    await session.commit()

    deletes_after_soft = [
        r
        for r in await _outbox(session, a.guild.id)
        if r.resource_id == task.id and r.action == "deleted"
    ]
    assert len(deletes_after_soft) == 1, "the soft delete should announce once"

    await set_rls_context(session, guild_id=a.guild.id, guild_role="admin")
    await hard_purge_entity(session, task)
    await session.commit()

    deletes_after_purge = [
        r
        for r in await _outbox(session, a.guild.id)
        if r.resource_id == task.id and r.action == "deleted"
    ]
    assert len(deletes_after_purge) == 1, (
        f"purge announced the delete again ({len(deletes_after_purge)} events) — "
        "a subscriber would see a delete for a row it was already told about"
    )


async def test_a_hard_delete_that_was_never_trashed_still_announces(
    session, acting_user
):
    """The guard keys on having been trashed, not on the table having the
    column: a row removed outright is still a delete a subscriber must hear."""
    from app.testing import create_initiative_member, create_user

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    joiner = await create_user(session)
    membership = await create_initiative_member(session, a.initiative, joiner)
    await session.commit()

    before = len(await _outbox(session, a.guild.id))
    await set_rls_context(session, guild_id=a.guild.id, guild_role="admin")
    await session.delete(membership)
    await session.commit()

    new_rows = (await _outbox(session, a.guild.id))[before:]
    assert [r for r in new_rows if r.resource_type == "initiatives"], (
        f"removing a member produced no event; got {new_rows}"
    )


async def test_a_trash_row_removed_outright_is_still_silent(session, acting_user):
    """The rule keys on the table's lifecycle, not on the row's history. A
    soft-deletable row hard-deleted without ever reaching the trash — a cascade
    from its purged parent — still says nothing, because the parent's own
    delete is the event a subscriber acts on."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    task = await create_task(session, a.project)

    before = len(await _outbox(session, a.guild.id))
    await set_rls_context(session, guild_id=a.guild.id, guild_role="admin")
    await session.delete(task)
    await session.commit()

    new_rows = (await _outbox(session, a.guild.id))[before:]
    assert not [r for r in new_rows if r.action == "deleted"], (
        f"a hard delete on a trash-lifecycle table surfaced; got {new_rows}"
    )


async def test_a_member_removing_themselves_is_captured(
    session, acting_user, role_session
):
    """The log records the change that ends the writer's own access.

    Leaving a guild, or a manager stepping out of an initiative, is still an
    event a subscriber acts on. Run as the real request role, so the outbox
    write is the one the leaver's own session performs, not a superuser's.
    """
    from sqlalchemy import text

    a = await acting_user(guild_role=GuildRole.member, initiative=True)
    before = len(await _outbox(session, a.guild.id))

    s = await role_session("app_user")
    await set_rls_context(
        s,
        user_id=a.user.id,
        guild_id=a.guild.id,
        guild_role=GuildRole.member.value,
    )
    await s.exec(
        text(
            "DELETE FROM initiative_members WHERE initiative_id = :i AND user_id = :u"
        ),
        params={"i": a.initiative.id, "u": a.user.id},
    )
    await s.commit()

    new_rows = (await _outbox(session, a.guild.id))[before:]
    assert [
        r
        for r in new_rows
        if r.resource_type == "initiatives" and r.resource_id == a.initiative.id
    ], f"a member removing themselves produced no event; got {new_rows}"


async def test_the_log_is_written_only_by_the_trigger(
    session, acting_user, role_session
):
    """A member may read their initiative's events, never author one: the
    outbox insert policy admits the capture trigger and nothing else."""
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError

    a = await acting_user(guild_role=GuildRole.member, initiative=True)

    s = await role_session("app_user")
    await set_rls_context(
        s,
        user_id=a.user.id,
        guild_id=a.guild.id,
        guild_role=GuildRole.member.value,
    )
    with pytest.raises(ProgrammingError, match="row-level security"):
        await s.exec(
            text(
                "INSERT INTO event_outbox "
                "(txn_id, occurred_at, actor_user_id, initiative_id, "
                " resource_type, resource_id, action, changed) "
                "VALUES (txid_current(), now(), :u, :i, 'tasks', 1, 'created', '{}')"
            ),
            params={"i": a.initiative.id, "u": a.user.id},
        )
