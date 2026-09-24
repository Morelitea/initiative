"""Migration 0344's demotion reaches every owner grant that names no user.

Run against real rows rather than the empty schema the migration chain test
builds from: the rows this revision exists for are the ones nothing in a fresh
install ever creates, and the first deployment to run it failed on a shape no
test had — a grant on a calendar that no longer existed (issue #1858).
"""

import importlib.util
import pathlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.errors import dbapi_sqlstate
from app.db.frozen import FROZEN_SQLSTATE
from app.services.tenant.soft_delete import soft_delete_entity
from app.testing import (
    create_calendar,
    create_guild,
    create_initiative,
    create_user,
    route_session_to_guild,
)

pytestmark = [pytest.mark.integration, pytest.mark.database]

MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20260921_0344_an_owner_is_a_person_or_nobody.py"
)


def _migration():
    """The revision, loaded by path: a file that starts with a digit is not an
    importable module. Safe to import — it binds ``op`` and calls nothing."""
    spec = importlib.util.spec_from_file_location("migration_0344", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _make_role_the_owner(session: AsyncSession, calendar, *, role_id: int):
    """The shape 20260804_0157 left behind: the calendar's one owner row names
    a manager role, not a person."""
    await session.exec(
        text(
            "DELETE FROM resource_grants WHERE resource_type = 'calendar' "
            "AND resource_id = :cid AND level = 'owner'"
        ).bindparams(cid=calendar.id)
    )
    await session.exec(
        text(
            "INSERT INTO resource_grants "
            "(initiative_id, resource_type, resource_id, user_id, "
            " role_id, level, created_at, all_initiative_members) "
            "VALUES (:iid, 'calendar', :cid, NULL, :rid, 'owner', now(), false)"
        ).bindparams(
            iid=calendar.initiative_id,
            cid=calendar.id,
            rid=role_id,
        )
    )


async def _level_of(session: AsyncSession, calendar_id: int, *, role_id: int):
    return (
        await session.exec(
            text(
                "SELECT level FROM resource_grants WHERE resource_type = 'calendar' "
                "AND resource_id = :cid AND role_id = :rid"
            ).bindparams(cid=calendar_id, rid=role_id)
        )
    ).scalar_one()


@pytest.fixture
async def legacy_calendars(session: AsyncSession):
    """Four calendars whose owner row names a role, in every lifecycle state a
    deployment can hold one in, plus one owned by a person as the control."""
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    initiative = await create_initiative(session, guild, user)

    live = await create_calendar(session, initiative, user)
    trashed = await create_calendar(session, initiative, user)
    archived = await create_calendar(session, initiative, user)
    purged = await create_calendar(session, initiative, user)
    owned = await create_calendar(session, initiative, user)
    await session.commit()

    await route_session_to_guild(session, guild.id)
    role_id = (
        await session.exec(
            text(
                "SELECT id FROM initiative_roles "
                "WHERE initiative_id = :iid AND name = 'project_manager'"
            ).bindparams(iid=initiative.id)
        )
    ).scalar_one()

    for calendar in (live, trashed, archived, purged):
        await _make_role_the_owner(session, calendar, role_id=role_id)
    await session.commit()

    await route_session_to_guild(session, guild.id)
    await soft_delete_entity(
        session, trashed, deleted_by_user_id=user.id, retention_days=30
    )
    await session.exec(
        text("UPDATE calendars SET archived_at = :at WHERE id = :cid").bindparams(
            at=datetime.now(timezone.utc), cid=archived.id
        )
    )
    # The calendar is gone and its grant is not: grants carry no foreign key to
    # the thing they share, and are cleared by the tool's own delete path.
    await session.exec(
        text("DELETE FROM calendars WHERE id = :cid").bindparams(cid=purged.id)
    )
    await session.commit()

    await route_session_to_guild(session, guild.id)
    return {
        "guild": guild,
        "role_id": role_id,
        "user": user,
        "live": live,
        "trashed": trashed,
        "archived": archived,
        "purged": purged,
        "owned": owned,
    }


async def test_the_bare_statement_is_refused_by_the_freeze(
    session: AsyncSession, legacy_calendars
):
    """What the first deployment hit: the lifecycle freeze reads a grant on
    frozen or missing content as read-only, and the plain UPDATE raises."""
    migration = _migration()
    with pytest.raises(DBAPIError) as excinfo:
        await session.exec(text(migration._DEMOTE))
    assert dbapi_sqlstate(excinfo.value) == FROZEN_SQLSTATE
    await session.rollback()


async def test_every_grantee_owner_grant_is_demoted(
    session: AsyncSession, legacy_calendars
):
    migration = _migration()
    role_id = legacy_calendars["role_id"]

    demoted = await session.run_sync(
        lambda sync: migration.demote_grantee_owner_grants(sync.connection())
    )
    await session.commit()

    assert demoted == 4
    await route_session_to_guild(session, legacy_calendars["guild"].id)
    for key in ("live", "trashed", "archived", "purged"):
        calendar = legacy_calendars[key]
        assert await _level_of(session, calendar.id, role_id=role_id) == "write", (
            f"the {key} calendar's role grant was not demoted"
        )

    remaining = (
        await session.exec(
            text(
                "SELECT count(*) FROM resource_grants "
                "WHERE level = 'owner' AND user_id IS NULL"
            )
        )
    ).scalar_one()
    assert remaining == 0


async def test_a_persons_owner_grant_is_left_alone(
    session: AsyncSession, legacy_calendars
):
    migration = _migration()
    await session.run_sync(
        lambda sync: migration.demote_grantee_owner_grants(sync.connection())
    )
    await session.commit()

    await route_session_to_guild(session, legacy_calendars["guild"].id)
    owner = (
        await session.exec(
            text(
                "SELECT user_id, level FROM resource_grants "
                "WHERE resource_type = 'calendar' AND resource_id = :cid "
                "AND level = 'owner'"
            ).bindparams(cid=legacy_calendars["owned"].id)
        )
    ).one()
    assert owner == (legacy_calendars["user"].id, "owner")


async def test_the_guards_are_back_when_it_is_done(
    session: AsyncSession, legacy_calendars
):
    """Switched off for one statement, not left off: every freeze trigger on
    the table is enabled again and the table is policy-bound again."""
    migration = _migration()
    await session.run_sync(
        lambda sync: migration.demote_grantee_owner_grants(sync.connection())
    )
    await session.commit()

    schema = f"guild_{legacy_calendars['guild'].id}"
    disabled = (
        await session.exec(
            text(
                "SELECT tg.tgname FROM pg_trigger tg "
                "JOIN pg_class c ON c.oid = tg.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = 'resource_grants' "
                "AND NOT tg.tgisinternal AND tg.tgenabled = 'D'"
            ).bindparams(schema=schema)
        )
    ).all()
    assert disabled == []

    forced = (
        await session.exec(
            text(
                "SELECT c.relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = 'resource_grants'"
            ).bindparams(schema=schema)
        )
    ).scalar_one()
    assert forced is True
