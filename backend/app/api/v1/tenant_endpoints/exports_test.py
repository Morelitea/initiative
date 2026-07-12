"""Export endpoints + worker: inline/job delivery, own-row isolation, and the
job-gated download path.

The download gate matters most here: an export artifact is a per-user
snapshot that may contain initiative-isolated content, so another guild
member must get 404 on the job and its download even though they share the
guild schema.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.platform.guild import GuildRole
from app.models.tenant.export_job import ExportJob, ExportJobStatus
from app.services.export import worker as export_worker
from app.services.storage import get_guild_storage
from app.testing.factories import create_task

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _tmp_uploads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOADS_DIR", str(tmp_path))


async def _actor_with_tasks(acting_user, session, count=2):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    for i in range(count):
        await create_task(session, a.project, title=f"Task {i}")
    return a


async def test_inline_export_returns_pdf(client: AsyncClient, acting_user, session):
    a = await _actor_with_tasks(acting_user, session)
    resp = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")


async def test_inline_export_csv_and_xlsx(client: AsyncClient, acting_user, session):
    a = await _actor_with_tasks(acting_user, session)

    csv_resp = await client.get(
        a.g("/exports/tasks"), headers=a.headers, params={"format": "csv"}
    )
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    body = csv_resp.content.decode("utf-8")
    assert "Task,Project,Status,Priority,Due,Assignees" in body
    assert "Task 0" in body and "Task 1" in body

    xlsx_resp = await client.get(
        a.g("/exports/tasks"), headers=a.headers, params={"format": "xlsx"}
    )
    assert xlsx_resp.status_code == 200
    assert xlsx_resp.content.startswith(b"PK")
    assert xlsx_resp.headers["content-type"].endswith("spreadsheetml.sheet")
    assert 'filename="tasks.xlsx"' in xlsx_resp.headers["content-disposition"]

    unknown = await client.get(
        a.g("/exports/tasks"), headers=a.headers, params={"format": "docx"}
    )
    assert unknown.status_code == 422  # HTTP-layer Literal validation


async def test_inline_export_respects_task_filters(
    client: AsyncClient, acting_user, session
):
    """Malformed conditions fail exactly like the list endpoint (same parse
    pipeline), proving the export rides the list's filter engine."""
    a = await _actor_with_tasks(acting_user, session)
    resp = await client.get(
        a.g("/exports/tasks"),
        headers=a.headers,
        params={"conditions": "not json"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "QUERY_INVALID_CONDITIONS"


async def test_export_max_rows_bound(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(settings, "EXPORT_MAX_ROWS", 1)
    a = await _actor_with_tasks(acting_user, session, count=2)
    resp = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "EXPORT_TOO_LARGE"


async def test_large_export_becomes_job(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(settings, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    resp = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == ExportJobStatus.queued.value
    assert body["source"] == "tasks"
    assert body["created_by_id"] == a.user.id
    # The row persists the SELECTOR only — no artifact_ref field is exposed,
    # and params echo the caller's own filter input.
    assert "artifact_ref" not in body
    assert body["params"]["include_archived"] is False

    # Not rendered yet: download must refuse, not serve a partial artifact.
    dl = await client.get(a.g(f"/exports/{body['id']}/download"), headers=a.headers)
    assert dl.status_code == 409
    assert dl.json()["detail"] == "EXPORT_NOT_READY"


async def test_job_limit_per_user(
    client: AsyncClient, acting_user, session, monkeypatch
):
    monkeypatch.setattr(settings, "EXPORT_INLINE_MAX_ROWS", 0)
    monkeypatch.setattr(settings, "EXPORT_MAX_ACTIVE_JOBS_PER_USER", 1)
    a = await _actor_with_tasks(acting_user, session)
    first = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert first.status_code == 202
    second = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert second.status_code == 429
    assert second.json()["detail"] == "EXPORT_JOB_LIMIT_REACHED"


async def test_jobs_are_own_row_isolated(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """Another member of the SAME guild sees neither the job nor its download
    (RLS hides the row -> 404); a guild admin sees it via the admin leg."""
    monkeypatch.setattr(settings, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    resp = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    other = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

    assert (
        await client.get(a.g(f"/exports/{job_id}"), headers=a.headers)
    ).status_code == 200
    for path in (f"/exports/{job_id}", f"/exports/{job_id}/download"):
        denied = await client.get(a.g(path), headers=other.headers)
        assert denied.status_code == 404, path
    assert (
        await client.get(a.g(f"/exports/{job_id}"), headers=admin.headers)
    ).status_code == 200

    # List views scope the same way.
    assert (await client.get(a.g("/exports/"), headers=other.headers)).json() == []
    assert [
        j["id"] for j in (await client.get(a.g("/exports/"), headers=a.headers)).json()
    ] == [job_id]


async def test_worker_renders_job_and_download_succeeds(
    client: AsyncClient, acting_user, session, monkeypatch, role_session
):
    monkeypatch.setattr(settings, "EXPORT_INLINE_MAX_ROWS", 0)
    a = await _actor_with_tasks(acting_user, session)
    resp = await client.get(a.g("/exports/tasks"), headers=a.headers)
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    # The worker re-queries as the creator on an app_user session; point its
    # session factory at the test DB (the admin side is patched by the
    # standard harness).
    user_session = await role_session("app_user")
    monkeypatch.setattr(export_worker, "_open_user_session", lambda: user_session)

    await export_worker.process_export_jobs()

    status_resp = await client.get(a.g(f"/exports/{job_id}"), headers=a.headers)
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["status"] == ExportJobStatus.done.value, body.get("error")
    assert body["expires_at"] is not None

    dl = await client.get(a.g(f"/exports/{job_id}/download"), headers=a.headers)
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/pdf"
    assert dl.content.startswith(b"%PDF")

    # And the artifact never lands in the uploads table / media route.
    media = await client.get(
        f"/uploads/{a.guild.id}/exports/{job_id}.pdf", headers=a.headers
    )
    assert media.status_code == 404

    # The creator gets an inbox entry pointing at the finished job — the
    # recovery path when they navigated away while the render ran.
    from sqlmodel import select

    from app.models.platform.notification import Notification, NotificationType

    notifications = list(
        await session.exec(
            select(Notification).where(Notification.user_id == a.user.id)
        )
    )
    export_notes = [n for n in notifications if n.type == NotificationType.export_ready]
    assert len(export_notes) == 1
    assert export_notes[0].data["export_job_id"] == job_id
    assert export_notes[0].data["guild_id"] == a.guild.id


async def test_gc_expires_artifacts(acting_user, session):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    storage = get_guild_storage(a.guild.id)
    key = "exports/424242.pdf"
    storage.write(key, b"%PDF-fake", content_type="application/pdf")
    job = ExportJob(
        guild_id=a.guild.id,
        created_by_id=a.user.id,
        source="tasks",
        template_id="task-table",
        format="pdf",
        status=ExportJobStatus.done,
        artifact_ref=key,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    session.add(job)
    await session.commit()

    await export_worker.process_export_gc()

    assert storage.open_readable(key) is None
    from app.testing import route_session_to_guild

    session.expunge_all()
    await route_session_to_guild(session, a.guild.id)
    refreshed = await session.get(ExportJob, job.id)
    assert refreshed.status == ExportJobStatus.expired.value
    assert refreshed.artifact_ref is None


async def test_gc_expires_row_even_when_artifact_delete_fails(
    acting_user, session, monkeypatch
):
    """A failing storage delete must not pin the job in ``done`` (it would
    re-fail every pass and abort GC for every guild after it) — the row still
    expires and the failure is only logged."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    job = ExportJob(
        guild_id=a.guild.id,
        created_by_id=a.user.id,
        source="tasks",
        template_id="task-table",
        format="pdf",
        status=ExportJobStatus.done,
        artifact_ref="exports/31337.pdf",
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    session.add(job)
    await session.commit()

    class _BrokenStorage:
        def delete(self, key: str) -> bool:
            raise RuntimeError("storage down")

    import app.services.storage as storage_module

    monkeypatch.setattr(
        storage_module, "get_guild_storage", lambda gid: _BrokenStorage()
    )

    await export_worker.process_export_gc()

    from app.testing import route_session_to_guild

    session.expunge_all()
    await route_session_to_guild(session, a.guild.id)
    refreshed = await session.get(ExportJob, job.id)
    assert refreshed.status == ExportJobStatus.expired.value
    assert refreshed.artifact_ref is None
