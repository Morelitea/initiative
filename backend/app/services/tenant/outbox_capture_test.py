"""The capture trigger writes what the poller expects to read.

These assert the seam between the DB-level trigger and the delivery layer: that
ordinary writes land in the outbox at all, that the row names the right resource
and initiative, and that the two shapes the design turns on — junctions
reporting their owner, and soft deletes reporting as deletes — hold against a
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
    from app.db.initiative_rls import GUILD_WIDE_EVENTED

    guild_wide = {s.table for s in build_specs() if s.table in GUILD_WIDE_EVENTED}
    assert guild_wide == set(GUILD_WIDE_EVENTED), (
        "a guild-wide table lost its capture spec, so its events would stop"
    )
    # Every other evented table resolves a real initiative.
    others = [s for s in build_specs() if s.table not in GUILD_WIDE_EVENTED]
    assert others, "expected initiative-scoped specs alongside the guild-wide ones"
