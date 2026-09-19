"""Bulk exports reaching the audit log.

An export is data leaving the deployment in one piece, so both aggregate
routes are recorded: who asked, for what, and which job carries it. Nothing
changed, which is exactly what makes the record worth having — a read of
everything looks like nothing at all in the content tables.

Per-entity exports (one project, the task list) are formatted reads and are
not recorded.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.models.platform.guild import GuildRole
from app.testing import recorded

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def test_exporting_an_initiative_records_the_job_that_carries_it(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    response = await client.get(
        a.g("/exports/initiative"),
        headers=a.headers,
        params={"initiative_id": a.initiative.id},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    (row,) = await recorded(session, AuditEventType.INITIATIVE_EXPORTED)
    assert row.actor_user_id == a.user.id
    assert row.guild_id == a.guild.id
    assert (row.target_type, row.target_id) == ("export_job", job_id)
    assert row.envelope["detail"] == {
        "mode": "backup",
        "include_uploads": True,
        "initiative_id": a.initiative.id,
        "job_id": job_id,
    }
    # A read changed nothing; the record says so.
    assert row.envelope["is_write"] is False


async def test_exporting_a_guild_records_its_own_event(
    client: AsyncClient, session: AsyncSession, acting_user
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)

    response = await client.get(
        a.g("/exports/guild"),
        headers=a.headers,
        params={"mode": "backup", "include_uploads": False},
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]

    (row,) = await recorded(session, AuditEventType.GUILD_EXPORTED)
    assert row.actor_user_id == a.user.id
    assert row.guild_id == a.guild.id
    assert (row.target_type, row.target_id) == ("export_job", job_id)
    assert row.envelope["detail"] == {
        "mode": "backup",
        "include_uploads": False,
        "job_id": job_id,
    }
    assert await recorded(session, AuditEventType.INITIATIVE_EXPORTED) == []


async def test_a_refused_guild_export_records_nothing(
    client: AsyncClient, session: AsyncSession, acting_user
):
    admin = await acting_user(guild_role=GuildRole.admin, initiative=True)
    member = await acting_user(guild_role=GuildRole.member, guild=admin.guild)

    response = await client.get(member.g("/exports/guild"), headers=member.headers)
    assert response.status_code == 403

    assert await recorded(session, AuditEventType.GUILD_EXPORTED) == []
