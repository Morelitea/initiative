"""The rung a request holds on a row is the database's answer.

``resource_level`` is the sharing gate's sibling: the same legs, answering
which rung of the ladder they reach rather than whether they reach one. The
policies keep asking ``resource_access``; a serializer reads ``access_level``,
mapped on every shareable model and answered in the same SELECT as the row.
These tests ask all three on the request login, standing by standing, and
hold them to one another.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, func
from sqlalchemy.orm import undefer
from sqlmodel import select

from app.db.authorization import (
    FULL_ACCESS,
    GRANT_REACHES_READER,
    RESOURCE_ACCESS,
    RESOURCE_LEVEL,
    _highest_rung_case,
    standing_arg,
)
from app.models.platform.guild import GuildRole
from app.models.platform.user import UserRole
from app.models.tenant.initiative import InitiativeRoleModel
from app.models.tenant.project import Project
from app.models.tenant.resource_grant import (
    WRITE_LEVELS,
    ResourceAccessLevel,
    ResourceGrant,
)
from app.testing import create_access_grant, create_user, route_as, route_system
from app.testing.schema_harness import route_session_to_guild

OWNER = ResourceAccessLevel.owner.value
WRITE = ResourceAccessLevel.write.value
READ = ResourceAccessLevel.read.value


@pytest.mark.unit
def test_the_two_bodies_share_every_leg():
    assert FULL_ACCESS in RESOURCE_LEVEL
    assert FULL_ACCESS in RESOURCE_ACCESS
    assert GRANT_REACHES_READER in RESOURCE_LEVEL
    assert GRANT_REACHES_READER in RESOURCE_ACCESS


@pytest.mark.unit
def test_the_highest_rung_is_spelled_from_the_ladder():
    assert _highest_rung_case() == (
        "WHEN bool_or(g.level = 'owner') THEN 'owner'\n"
        "             WHEN bool_or(g.level = 'write') THEN 'write'\n"
        "             WHEN count(*) > 0 THEN 'read'"
    )


# --- the standings, and what each grant shape gives them ----------------------

STANDINGS = ("member", "admin", "full_access", "pam_read", "pam_write", "system")
GRANTS = ("none", "user_read", "user_write", "user_owner", "role_write", "everyone")

#: The rung each standing holds under each grant shape. A grant naming the
#: reader applies to anybody it names; a role grant or an everyone grant
#: applies through a membership, which a grantee does not hold.
EXPECTED: dict[str, dict[str, str | None]] = {
    "member": {
        "none": None,
        "user_read": READ,
        "user_write": WRITE,
        "user_owner": OWNER,
        "role_write": WRITE,
        "everyone": READ,
    },
    "admin": dict.fromkeys(GRANTS, OWNER),
    "full_access": dict.fromkeys(GRANTS, OWNER),
    "pam_read": {
        "none": READ,
        "user_read": READ,
        "user_write": WRITE,
        "user_owner": OWNER,
        "role_write": READ,
        "everyone": READ,
    },
    "pam_write": {
        "none": WRITE,
        "user_read": WRITE,
        "user_write": WRITE,
        "user_owner": OWNER,
        "role_write": WRITE,
        "everyone": WRITE,
    },
    "system": dict.fromkeys(GRANTS, OWNER),
}


async def _subject(session, acting_user, a, standing):
    """The account the standing belongs to, with what gives it that standing."""
    if standing == "member":
        b = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="member",
        )
        return b.user
    if standing == "full_access":
        b = await acting_user(
            guild_role=GuildRole.member,
            guild=a.guild,
            initiative=a.initiative,
            initiative_role="moderator",
        )
        return b.user
    if standing == "admin":
        b = await acting_user(guild_role=GuildRole.admin, guild=a.guild)
        return b.user
    support = await create_user(session, role=UserRole.support)
    await create_access_grant(
        session,
        user=support,
        guild=a.guild,
        access_level="read_write" if standing == "pam_write" else "read",
    )
    return support


async def _apply_grant(session, a, shape, subject):
    """Replace the project's grants with exactly the shape named."""
    await route_session_to_guild(session, a.guild.id)
    await session.exec(
        delete(ResourceGrant).where(
            ResourceGrant.resource_type == "project",
            ResourceGrant.resource_id == a.project.id,
        )
    )
    if shape != "none":
        member_role_id = (
            await session.exec(
                select(InitiativeRoleModel.id).where(
                    InitiativeRoleModel.initiative_id == a.initiative.id,
                    InitiativeRoleModel.name == "member",
                )
            )
        ).one()
        level = {
            "user_read": READ,
            "user_write": WRITE,
            "user_owner": OWNER,
            "role_write": WRITE,
            "everyone": READ,
        }[shape]
        session.add(
            ResourceGrant(
                resource_type="project",
                resource_id=a.project.id,
                initiative_id=a.initiative.id,
                user_id=subject.id if shape.startswith("user_") else None,
                role_id=member_role_id if shape == "role_write" else None,
                all_initiative_members=shape == "everyone",
                level=level,
            )
        )
    await session.commit()


@pytest.mark.integration
@pytest.mark.parametrize("shape", GRANTS)
@pytest.mark.parametrize("standing", STANDINGS)
async def test_the_level_the_gate_and_the_column_agree(
    session, acting_user, role_session, standing, shape
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    if standing == "system":
        s = await role_session("app_admin")
        await route_system(s, guild_id=a.guild.id)
        reader_id = None
        await _apply_grant(session, a, shape, a.user)
    else:
        subject = await _subject(session, acting_user, a, standing)
        await _apply_grant(session, a, shape, subject)
        s = await role_session("app_user")
        await route_as(s, user_id=subject.id, guild_id=a.guild.id)
        reader_id = subject.id

    expected = EXPECTED[standing][shape]
    args = ("project", a.project.id, reader_id, a.initiative.id)
    st = standing_arg()
    level = (await s.exec(select(func.resource_level(*args, st)))).one()
    reads = (await s.exec(select(func.resource_access(*args, False, st)))).one()
    writes = (await s.exec(select(func.resource_access(*args, True, st)))).one()
    assert level == expected, f"{standing} under {shape}"
    assert reads is (level is not None)
    assert writes is (level in {lvl.value for lvl in WRITE_LEVELS})

    row = (
        await s.exec(
            select(Project)
            .where(Project.id == a.project.id)
            .options(undefer(Project.access_level))
        )
    ).one_or_none()
    assert (row is not None) is reads
    if row is not None:
        assert row.access_level == level


@pytest.mark.integration
async def test_a_reader_outside_the_initiative_is_answered_by_the_policy(
    session, acting_user, role_session
):
    """The level is asked of a row the policy already admitted; a row the
    reader cannot reach never arrives to be asked about."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    await _apply_grant(session, a, "user_owner", outsider.user)

    s = await role_session("app_user")
    await route_as(s, user_id=outsider.user.id, guild_id=a.guild.id)
    rows = (await s.exec(select(Project.id).where(Project.id == a.project.id))).all()
    assert rows == []
