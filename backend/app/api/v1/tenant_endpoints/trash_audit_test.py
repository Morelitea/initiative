"""Purging from the trash reaching the audit log.

A purge is the one action nothing recovers from, so the record is what is left
of the row afterwards: which kind of thing it was, which id, and who did it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.models.platform.guild import GuildRole
from app.testing import create_project, recorded

pytestmark = pytest.mark.integration


async def test_purging_an_entity_records_what_was_destroyed(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    project = await create_project(session, admin.initiative, admin.user)

    trashed = await client.delete(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )
    assert trashed.status_code in (200, 204), trashed.text

    purged = await client.delete(
        admin.g(f"/trash/project/{project.id}/purge"), headers=admin.headers
    )
    assert purged.status_code == 204, purged.text

    (row,) = await recorded(session, AuditEventType.TRASH_PURGED)
    assert row.actor_user_id == admin.user.id
    assert row.target_user_id is None
    assert row.guild_id == admin.guild.id
    assert (row.target_type, row.target_id) == ("project", project.id)
    assert row.envelope["detail"] == {"via": "admin"}


async def test_a_refused_purge_records_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    """A purge is a guild admin's, and a request that never got past that
    destroyed nothing to write down."""
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(
        guild_role=GuildRole.member,
        guild=admin.guild,
        initiative=admin.initiative,
        initiative_role="member",
    )
    project = await create_project(session, admin.initiative, admin.user)
    trashed = await client.delete(
        admin.g(f"/projects/{project.id}"), headers=admin.headers
    )
    assert trashed.status_code in (200, 204), trashed.text

    refused = await client.delete(
        member.g(f"/trash/project/{project.id}/purge"), headers=member.headers
    )
    assert refused.status_code == 403

    assert await recorded(session, AuditEventType.TRASH_PURGED) == []
