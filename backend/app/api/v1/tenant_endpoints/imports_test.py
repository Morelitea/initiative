"""Tests for the import engine: envelopes, foreign files, Jira, backups."""

import io
import json
import zipfile

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.platform.guild import GuildRole
from app.models.tenant.import_job import ImportJob, ImportJobStatus
from app.services.import_engine import worker as import_worker
from app.services.storage import get_guild_storage
from app.testing.factories import (
    guild_administration,
    create_calendar_event,
    create_counter_group,
    create_document,
    create_initiative,
    create_queue,
    create_task,
)


# ---------------------------------------------------------------------------
# Import engine: envelope imports + job lifecycle
# ---------------------------------------------------------------------------


async def _export_json(client, a, endpoint, params):
    resp = await client.get(
        a.g(endpoint), headers=a.headers, params={**params, "format": "json"}
    )
    assert resp.status_code == 200, resp.text
    return json.loads(resp.content)


async def _import_envelope(client, actor, envelope, initiative_id):
    return await client.post(
        actor.g("/imports/envelope"),
        headers=actor.headers,
        json={"initiative_id": initiative_id, "envelope": envelope},
    )


async def _second_initiative(session, a, **flags):
    initiative = await create_initiative(
        session, a.guild, a.user, name="Import Target", **flags
    )
    return initiative


async def test_envelope_import_roundtrips_queue(client, acting_user, session):
    """Export a queue as its envelope, import it into another initiative:
    items, rotation state, and item tags survive; the importer gets an owner
    grant; tags match-or-create against the guild."""
    from sqlmodel import select

    from app.models.tenant.queue import Queue, QueueItem
    from app.models.tenant.resource_grant import ResourceGrant

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    queue = await create_queue(session, a.initiative, a.user, name="Turn Order")
    from app.models.tenant.queue import QueueItem as QI

    for i, label in enumerate(["Aria", "Brock"]):
        session.add(QI(queue_id=queue.id, label=label, position=float(i)))
    await session.commit()

    envelope = await _export_json(client, a, "/exports/queue", {"queue_id": queue.id})
    assert envelope["type"] == "initiative-queue"

    target = await _second_initiative(session, a, queues_enabled=True)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert result["created"]["queues"] == 1
    assert result["created"]["items"] == 2

    imported = (
        await session.exec(
            select(Queue).where(
                Queue.initiative_id == target.id, Queue.name == "Turn Order"
            )
        )
    ).one()
    items = list(
        await session.exec(select(QueueItem).where(QueueItem.queue_id == imported.id))
    )
    assert {i.label for i in items} == {"Aria", "Brock"}
    grant = (
        await session.exec(
            select(ResourceGrant).where(
                ResourceGrant.resource_type == "queue",
                ResourceGrant.resource_id == imported.id,
                ResourceGrant.user_id == a.user.id,
            )
        )
    ).one()
    assert str(grant.level) in ("owner", "ResourceAccessLevel.owner")


async def test_envelope_import_roundtrips_counter_group(client, acting_user, session):
    from sqlmodel import select

    from app.models.tenant.counter import Counter, CounterGroup

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    group = await create_counter_group(session, a.initiative, a.user, name="Party Gold")
    from app.models.tenant.counter import Counter as C
    from decimal import Decimal

    session.add(
        C(
            counter_group_id=group.id,
            name="GP",
            count=Decimal("42.5"),
            step=Decimal("1"),
            initial_count=Decimal("0"),
            position=Decimal("0"),
        )
    )
    await session.commit()

    envelope = await _export_json(
        client, a, "/exports/counter-group", {"counter_group_id": group.id}
    )
    target = await _second_initiative(session, a, counter_groups_enabled=True)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text

    imported = (
        await session.exec(
            select(CounterGroup).where(
                CounterGroup.initiative_id == target.id,
                CounterGroup.name == "Party Gold",
            )
        )
    ).one()
    counter = (
        await session.exec(
            select(Counter).where(Counter.counter_group_id == imported.id)
        )
    ).one()
    assert counter.name == "GP"
    assert float(counter.count) == 42.5


async def test_envelope_import_roundtrips_document_types(client, acting_user, session):
    """Native, spreadsheet, smart link, and whiteboard envelopes import with
    their content models restored (whiteboard unwrapped from the Excalidraw
    file shape, spreadsheet re-normalized)."""
    from sqlmodel import select

    from app.models.tenant.document import Document, DocumentType

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    target = await _second_initiative(session, a)

    native = await create_document(
        session,
        a.initiative,
        a.user,
        name="Notes",
        content={"root": {"type": "root", "children": []}},
    )
    board = await create_document(
        session,
        a.initiative,
        a.user,
        name="Map",
        document_type=DocumentType.whiteboard,
        content={"elements": [{"type": "rectangle"}], "appState": {}, "files": {}},
    )
    link = await create_document(
        session,
        a.initiative,
        a.user,
        name="Spec",
        document_type=DocumentType.smart_link,
        content={"url": "https://example.com/spec"},
    )

    for doc, doc_type in (
        (native, "native"),
        (board, "whiteboard"),
        (link, "smart_link"),
    ):
        envelope = await _export_json(
            client, a, "/exports/document", {"document_id": doc.id}
        )
        resp = await _import_envelope(client, a, envelope, target.id)
        assert resp.status_code == 201, (doc_type, resp.text)

    imported = list(
        await session.exec(select(Document).where(Document.initiative_id == target.id))
    )
    by_name = {d.name: d for d in imported}
    assert set(by_name) == {"Notes", "Map", "Spec"}
    assert by_name["Map"].content["elements"] == [{"type": "rectangle"}]
    assert "type" not in by_name["Map"].content  # unwrapped, not the file shape
    assert by_name["Spec"].content == {"url": "https://example.com/spec"}


async def test_envelope_import_roundtrips_calendar(client, acting_user, session):
    from sqlmodel import select

    from app.models.tenant.calendar import Calendar
    from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee
    from app.testing.factories import create_calendar

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    a.initiative.calendars_enabled = True
    session.add(a.initiative)
    await session.commit()
    calendar = await create_calendar(session, a.initiative, a.user, name="Raid Nights")
    await create_calendar_event(session, calendar, a.user, title="Session Zero")
    await create_calendar_event(session, calendar, a.user, title="One-shot")

    envelope = await _export_json(
        client, a, "/exports/calendar", {"initiative_id": a.initiative.id}
    )
    assert envelope["type"] == "initiative-calendar"

    target = await _second_initiative(session, a, calendars_enabled=True)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    created = resp.json()["result"]["created"]
    assert created["calendars"] == 1
    assert created["events"] == 2

    imported_calendar = (
        await session.exec(select(Calendar).where(Calendar.initiative_id == target.id))
    ).one()
    assert imported_calendar.name == "Raid Nights"
    imported = list(
        await session.exec(
            select(CalendarEvent).where(
                CalendarEvent.calendar_id == imported_calendar.id
            )
        )
    )
    assert {e.title for e in imported} == {"Session Zero", "One-shot"}
    # The exporter was the only attendee-resolvable member; attendee rows for
    # the creator resolve by email.
    attendees = list(
        await session.exec(
            select(CalendarEventAttendee).where(
                CalendarEventAttendee.calendar_event_id.in_([e.id for e in imported])
            )
        )
    )
    assert all(att.user_id == a.user.id for att in attendees)


async def test_envelope_import_project_replaces_legacy_route(
    client, acting_user, session
):
    """The engine is the project import path now: the legacy POST
    /projects/import is gone (404), and the same envelope imports through
    /imports/envelope with tasks and statuses recreated."""
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    await create_task(session, a.project, title="Fell the tower")

    envelope = await _export_json(
        client, a, "/exports/project", {"project_id": a.project.id}
    )
    assert envelope["type"] == "initiative-project"

    legacy = await client.post(
        a.g("/projects/import"),
        headers=a.headers,
        json={"initiative_id": a.initiative.id, "envelope": envelope},
    )
    assert legacy.status_code in (404, 405)

    target = await _second_initiative(session, a)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert result["created"]["tasks"] == 1

    project = (
        await session.exec(select(Project).where(Project.initiative_id == target.id))
    ).one()
    task = (await session.exec(select(Task).where(Task.project_id == project.id))).one()
    assert task.title == "Fell the tower"


async def test_envelope_import_authorization_gates(client, acting_user, session):
    """Unknown type 400; bad version 400; tool switch off 400; a member
    without the create permission 403; an unreachable initiative 404."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc_envelope = {
        "type": "initiative-document",
        "schema_version": 1,
        "document_type": "smart_link",
        "name": "Doc",
        "content": {"url": "https://example.com"},
        "tags": [],
        "properties": [],
    }

    unknown = await _import_envelope(
        client, a, {**doc_envelope, "type": "initiative-wands"}, a.initiative.id
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "IMPORT_UNKNOWN_TYPE"

    future = await _import_envelope(
        client, a, {**doc_envelope, "schema_version": 99}, a.initiative.id
    )
    assert future.status_code == 400
    assert future.json()["detail"] == "IMPORT_SCHEMA_VERSION_UNSUPPORTED"

    queue_envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Q",
        "items": [],
    }
    a.initiative.queues_enabled = False
    session.add(a.initiative)
    await session.commit()
    disabled = await _import_envelope(client, a, queue_envelope, a.initiative.id)
    assert disabled.status_code == 400
    assert disabled.json()["detail"] == "IMPORT_TOOL_DISABLED"

    # A plain member-role actor lacks create_documents (defaults False).
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    denied = await _import_envelope(client, b, doc_envelope, a.initiative.id)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "IMPORT_PERMISSION_REQUIRED"

    # A guild member outside the initiative: the structural initiative row is
    # guild-visible (only content is initiative-hidden), so this is a clean
    # permission refusal, not a 404.
    outsider = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    hidden = await _import_envelope(client, outsider, doc_envelope, a.initiative.id)
    assert hidden.status_code == 403


async def test_large_envelope_becomes_job_and_worker_applies_it(
    client, acting_user, session, monkeypatch, role_session
):
    """Above the inline threshold the payload is staged (the row holds no
    content) and the worker applies it as the creator, persists the result,
    deletes the payload, and notifies."""
    from sqlmodel import select

    from app.models.platform.notification import Notification, NotificationType
    from app.models.tenant.queue import Queue

    monkeypatch.setattr(settings, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Big Queue",
        "items": [{"label": f"Item {i}", "position": float(i)} for i in range(3)],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    job_id = body["id"]
    assert body["status"] == ImportJobStatus.queued.value
    assert body["params"] == {"initiative_id": a.initiative.id}
    # The row holds options only — the envelope content is staged in storage,
    # and the storage key itself is not exposed through the API.
    assert "items" not in json.dumps(body)
    assert "payload_ref" not in body

    user_session = await role_session("app_user")
    monkeypatch.setattr(import_worker, "_open_user_session", lambda: user_session)
    await import_worker.process_import_jobs()

    status_resp = await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    job = status_resp.json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["created"]["queues"] == 1
    assert job["result"]["created"]["items"] == 3

    # The staged payload was deleted on the terminal transition.
    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    row = await session.get(ImportJob, job_id)
    assert row is not None and row.payload_ref is None

    imported = (
        await session.exec(select(Queue).where(Queue.name == "Big Queue"))
    ).one()
    assert imported.created_by == a.user.id  # applied AS the creator

    notifications = list(
        await session.exec(
            select(Notification).where(Notification.user_id == a.user.id)
        )
    )
    ready = [n for n in notifications if n.type == NotificationType.import_ready]
    assert len(ready) == 1
    assert ready[0].data["import_job_id"] == job_id


async def test_worker_fails_closed_on_revoked_permission(
    client, acting_user, session, monkeypatch, role_session
):
    """Create permission revoked between enqueue and apply → the job fails
    with IMPORT_PERMISSION_REQUIRED and nothing is created."""
    from sqlalchemy import delete as sa_delete
    from sqlmodel import select

    from app.models.tenant.initiative import InitiativeMember
    from app.models.tenant.queue import Queue

    monkeypatch.setattr(settings, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Doomed Queue",
        "items": [],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202
    job_id = resp.json()["id"]

    await session.exec(
        sa_delete(InitiativeMember).where(
            InitiativeMember.initiative_id == a.initiative.id,
            InitiativeMember.user_id == a.user.id,
        )
    )
    await session.commit()

    user_session = await role_session("app_user")
    monkeypatch.setattr(import_worker, "_open_user_session", lambda: user_session)
    await import_worker.process_import_jobs()

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    # RLS hides the initiative from a non-member (404-shaped), or the
    # permission check refuses — both fail closed.
    assert job["error"] in ("IMPORT_PERMISSION_REQUIRED", "IMPORT_INVALID_PARAMS")
    assert (
        await session.exec(select(Queue).where(Queue.name == "Doomed Queue"))
    ).one_or_none() is None


async def test_stale_running_import_fails_closed_not_reapplied(
    acting_user, session, monkeypatch, role_session
):
    """A running row older than the stale threshold is FAILED, never re-run
    (an interrupted apply may have committed rows already)."""
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(settings, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=30)
    job = ImportJob(
        created_by=a.user.id,
        source="initiative-queue",
        params={"initiative_id": a.initiative.id},
        payload_ref="imports/gone.json",
        status=ImportJobStatus.running,
        created_at=stale_time,
        updated_at=stale_time,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    user_session = await role_session("app_user")
    monkeypatch.setattr(import_worker, "_open_user_session", lambda: user_session)
    await import_worker.process_import_jobs()

    await session.refresh(job)
    assert job.status == ImportJobStatus.failed
    assert job.error == "IMPORT_INTERRUPTED"


async def test_import_job_cap_and_cancel(client, acting_user, session, monkeypatch):
    monkeypatch.setattr(settings, "IMPORT_INLINE_MAX_ROWS", 0)
    monkeypatch.setattr(settings, "IMPORT_MAX_ACTIVE_JOBS_PER_USER", 1)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Q",
        "items": [],
    }
    first = await _import_envelope(client, a, envelope, a.initiative.id)
    assert first.status_code == 202
    second = await _import_envelope(client, a, envelope, a.initiative.id)
    assert second.status_code == 429
    assert second.json()["detail"] == "IMPORT_JOB_LIMIT_REACHED"

    job_id = first.json()["id"]
    cancelled = await client.delete(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == ImportJobStatus.cancelled.value

    # Cancelling freed the cap slot.
    third = await _import_envelope(client, a, envelope, a.initiative.id)
    assert third.status_code == 202

    # A terminal job is not cancellable.
    not_again = await client.delete(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)
    assert not_again.status_code == 409


async def test_import_jobs_are_own_row_isolated(
    client, acting_user, session, monkeypatch
):
    """Another member sees neither the job nor its row (RLS, 404); a guild
    admin sees it via the admin leg."""
    monkeypatch.setattr(settings, "IMPORT_INLINE_MAX_ROWS", 0)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Mine",
        "items": [],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    job_id = resp.json()["id"]

    other = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

    denied = await client.get(a.g(f"/imports/jobs/{job_id}"), headers=other.headers)
    assert denied.status_code == 404
    assert (await client.get(a.g("/imports/jobs"), headers=other.headers)).json() == []
    allowed = await client.get(a.g(f"/imports/jobs/{job_id}"), headers=admin.headers)
    assert allowed.status_code == 200


async def test_envelope_byte_bound_enforced_before_body_is_read(
    client: AsyncClient, acting_user, session, monkeypatch
):
    """The byte bound lives in ASGI middleware, not the handler: an honest
    Content-Length is refused before any body is read, and a chunked
    (length-less) stream is cut off as soon as it exceeds the limit — the
    server never buffers more than the cap."""
    monkeypatch.setattr(settings, "IMPORT_MAX_ENVELOPE_BYTES", 1024)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    big_body = json.dumps(
        {
            "initiative_id": a.initiative.id,
            "envelope": {
                "type": "initiative-queue",
                "schema_version": 1,
                "name": "Q",
                "items": [],
                "padding": "x" * 4096,
            },
        }
    ).encode("utf-8")

    # Declared length over the cap: 413 straight from the header.
    declared = await client.post(
        a.g("/imports/envelope"),
        headers={**a.headers, "Content-Type": "application/json"},
        content=big_body,
    )
    assert declared.status_code == 413
    assert declared.json()["detail"] == "IMPORT_TOO_LARGE"

    # Chunked transfer (no Content-Length): the streaming backstop cuts the
    # request off mid-body instead of buffering it all.
    async def chunks():
        for i in range(0, len(big_body), 512):
            yield big_body[i : i + 512]

    chunked = await client.post(
        a.g("/imports/envelope"),
        headers={**a.headers, "Content-Type": "application/json"},
        content=chunks(),
    )
    assert chunked.status_code == 413
    assert chunked.json()["detail"] == "IMPORT_TOO_LARGE"

    # An under-cap request still works — the bound didn't break the route.
    ok = await _import_envelope(
        client,
        a,
        {"type": "initiative-queue", "schema_version": 1, "name": "Q", "items": []},
        a.initiative.id,
    )
    assert ok.status_code == 201


# ---------------------------------------------------------------------------
# Backup-zip imports
# ---------------------------------------------------------------------------


def _make_backup_zip(manifest: dict, members: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in (members or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _minimal_manifest(initiative_id=1, name="Restored", entries=None, assets=None):
    return {
        "type": "initiative-backup",
        "schema_version": 1,
        "app_version": "0.0.0-test",
        "exported_at": "2026-07-15T00:00:00+00:00",
        "exported_by_handle": "tester#0001",
        "source_instance_url": None,
        "guild": {"id": 999, "name": "Source Guild"},
        "include_uploads": bool(assets),
        "initiatives": [
            {
                "id": initiative_id,
                "name": name,
                "description": "from backup",
                "color": "#aabbcc",
                "tools": {
                    "project": "included",
                    "document": "included",
                    "queue": "included",
                    "counter_group": "disabled",
                    "calendar_event": "included",
                },
            }
        ],
        "entries": entries or [],
        "assets": assets or [],
        "skipped": [],
    }


def _queue_entry(initiative_id=1):
    envelope = {
        "type": "initiative-queue",
        "schema_version": 1,
        "name": "Restored Queue",
        "items": [{"label": "Aria", "position": 1.0}],
    }
    entry = {
        "path": "initiatives/1-restored/queues/1-restored-queue.initiative-queue.json",
        "tool": "queue",
        "type": "initiative-queue",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Restored Queue",
        "initiative_id": initiative_id,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    return entry, envelope


async def _upload_backup(client, actor, zip_bytes):
    return await client.post(
        actor.g("/imports/backup"),
        headers=actor.headers,
        files={"file": ("backup.zip", zip_bytes, "application/zip")},
    )


async def _apply_backup(client, actor, zip_bytes, monkeypatch, role_session) -> dict:
    """Upload → confirm → worker → the finished job row."""
    resp = await _upload_backup(client, actor, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    confirmed = await client.post(
        actor.g(f"/imports/jobs/{job_id}/confirm"), headers=actor.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    return (
        await client.get(actor.g(f"/imports/jobs/{job_id}"), headers=actor.headers)
    ).json()


async def _run_import_worker(monkeypatch, role_session):
    user_session = await role_session("app_user")
    monkeypatch.setattr(import_worker, "_open_user_session", lambda: user_session)
    await import_worker.process_import_jobs()


async def test_backup_import_end_to_end_with_assets(
    client, acting_user, session, monkeypatch, role_session
):
    """Upload → plan → confirm → worker apply: a new initiative appears with
    the manifest's tool switches and the importer as manager; entries apply
    through the per-type importers; the file document's blob is restored
    (deduped here — same guild, key already exists) and quota-checked."""
    from sqlmodel import select

    from app.models.tenant.document import Document, DocumentType
    from app.models.tenant.initiative import Initiative, InitiativeMember
    from app.models.tenant.queue import Queue

    from app.testing.factories import create_upload

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    payload = b"%PDF-restored-handout"
    # The blob and its uploads row already exist in this guild (the re-import
    # case) — the restore must dedupe on the storage key, not overwrite.
    get_guild_storage(a.guild.id).write(
        "restore-me.pdf", payload, content_type="application/pdf"
    )
    await create_upload(
        session,
        a.guild,
        a.user,
        filename="restore-me.pdf",
        size_bytes=len(payload),
        content_type="application/pdf",
    )

    entry, envelope = _queue_entry()
    file_entry = {
        "path": "assets/restore-me.pdf",
        "tool": "document",
        "type": "file",
        "schema_version": None,
        "entity_id": 2,
        "title": "Handout",
        "initiative_id": 1,
        "tags": ["restored"],
        "properties": [],
        "asset": "assets/restore-me.pdf",
    }
    manifest = _minimal_manifest(
        entries=[entry, file_entry],
        assets=[
            {
                "path": "assets/restore-me.pdf",
                "storage_key": "restore-me.pdf",
                "original_filename": "Handout.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(payload),
                "referenced_by": ["initiatives/1-restored/documents/2-handout"],
            }
        ],
    )
    zip_bytes = _make_backup_zip(
        manifest,
        {
            entry["path"]: json.dumps(envelope).encode(),
            "assets/restore-me.pdf": payload,
        },
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    job_id = body["id"]
    assert body["status"] == ImportJobStatus.staged.value
    plan = body["plan"]
    assert plan["source_guild_name"] == "Source Guild"
    assert plan["initiatives"][0]["proposed_name"] == "Restored"
    assert plan["initiatives"][0]["entry_counts"] == {"queue": 1, "document": 1}
    assert plan["asset_count"] == 1
    assert plan["asset_bytes"] == len(payload)

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == ImportJobStatus.queued.value

    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    result = job["result"]
    assert result["per_tool"]["queue"]["created"] == 1
    assert result["per_tool"]["document"]["created"] == 1
    # Same guild: the storage key already existed, so the blob deduped.
    assert result["assets_deduped"] == 1
    assert result["assets_restored"] == 0

    restored = (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one()
    assert restored.description == "from backup"
    assert restored.queues_enabled is True
    assert restored.counter_groups_enabled is False  # "disabled" in manifest
    member = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == restored.id
            )
        )
    ).one()
    assert member.user_id == a.user.id

    queue = (
        await session.exec(select(Queue).where(Queue.initiative_id == restored.id))
    ).one()
    assert queue.name == "Restored Queue"
    file_doc = (
        await session.exec(
            select(Document).where(
                Document.initiative_id == restored.id,
                Document.document_type == DocumentType.file,
            )
        )
    ).one()
    assert file_doc.name == "Handout"
    assert file_doc.file_url.endswith("/restore-me.pdf")
    assert file_doc.original_filename == "Handout.pdf"


async def test_backup_belongs_to_the_seat(client, acting_user, session):
    """Restoring a community's backup sits with the seat that exports one —
    an ordinary admin is refused, as a member is."""
    seat = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    admin = await acting_user(guild_role=GuildRole.admin, guild=seat.guild)
    member = await acting_user(guild_role=GuildRole.member, guild=seat.guild)
    zip_bytes = _make_backup_zip(_minimal_manifest())
    for caller in (admin, member):
        denied = await _upload_backup(client, caller, zip_bytes)
        assert denied.status_code == 403, caller.membership.role
        assert denied.json()["detail"] == "IMPORT_SUPERADMIN_REQUIRED"


async def test_backup_rejects_invalid_and_bomb_zips(
    client, acting_user, session, monkeypatch
):
    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )

    garbage = await _upload_backup(client, a, b"not a zip at all")
    assert garbage.status_code == 400
    assert garbage.json()["detail"] == "IMPORT_ZIP_INVALID"

    traversal = _make_backup_zip(_minimal_manifest(), {"../escape.txt": b"x"})
    escaped = await _upload_backup(client, a, traversal)
    assert escaped.status_code == 400
    assert escaped.json()["detail"] == "IMPORT_ZIP_INVALID"

    monkeypatch.setattr(settings, "IMPORT_MAX_ZIP_MEMBERS", 1)
    entry, envelope = _queue_entry()
    bomb = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    too_many = await _upload_backup(client, a, bomb)
    assert too_many.status_code == 400
    assert too_many.json()["detail"] == "IMPORT_TOO_LARGE"

    monkeypatch.setattr(settings, "IMPORT_MAX_ZIP_MEMBERS", 20_000)
    future = _make_backup_zip({**_minimal_manifest(), "schema_version": 99})
    unsupported = await _upload_backup(client, a, future)
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == "IMPORT_SCHEMA_VERSION_UNSUPPORTED"


async def test_backup_rejects_asset_key_with_path_components(
    client, acting_user, session
):
    """An asset storage_key is both the uploads-row identity and the storage
    write target; the backends key by basename. A backup whose key carries path
    components is rejected whole at upload, leaving an existing blob of the same
    basename untouched and creating no second uploads row."""
    from sqlmodel import select

    from app.models.tenant.upload import Upload
    from app.testing import route_session_to_guild
    from app.testing.factories import create_upload

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    original = b"%PDF-original"
    get_guild_storage(a.guild.id).write(
        "keep.pdf", original, content_type="application/pdf"
    )
    await create_upload(
        session,
        a.guild,
        a.user,
        filename="keep.pdf",
        size_bytes=len(original),
        content_type="application/pdf",
    )

    manifest = _minimal_manifest(
        assets=[
            {
                "path": "assets/nested/keep.pdf",
                "storage_key": "nested/keep.pdf",
                "original_filename": "keep.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(original),
                "referenced_by": [],
            }
        ],
    )
    zip_bytes = _make_backup_zip(
        manifest, {"assets/nested/keep.pdf": b"REPLACED-BYTES"}
    )
    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_ZIP_INVALID"

    blob = get_guild_storage(a.guild.id).open_readable("keep.pdf")
    assert blob is not None and blob.path.read_bytes() == original
    await route_session_to_guild(session, a.guild.id)
    rows = (await session.exec(select(Upload))).all()
    assert [u.filename for u in rows] == ["keep.pdf"]


def test_reject_non_flat_asset_keys_unit():
    """The one choke point both plan and apply funnel through: flat keys pass;
    a storage_key or file-entry asset with path components raises."""
    from app.schemas.tenant.backup_export import (
        BackupManifest,
        ManifestAsset,
        ManifestEntry,
    )
    from app.services.import_engine.backup import _reject_non_flat_asset_keys
    from app.services.import_engine.contract import ImportEngineError

    def _manifest(assets=None, entries=None):
        return BackupManifest(
            type="initiative-backup",
            schema_version=1,
            app_version="0.0.0-test",
            exported_at="2026-07-15T00:00:00+00:00",
            guild={"id": 1, "name": "g"},
            include_uploads=True,
            initiatives=[],
            entries=entries or [],
            assets=assets or [],
            skipped=[],
        )

    def _asset(storage_key):
        return ManifestAsset(path=f"assets/{storage_key}", storage_key=storage_key)

    def _file_entry(asset_ref):
        return ManifestEntry(
            path=asset_ref,
            tool="document",
            type="file",
            entity_id=1,
            title="f",
            initiative_id=1,
            asset=asset_ref,
        )

    # Flat keys pass (a legit export only ever emits these).
    _reject_non_flat_asset_keys(_manifest(assets=[_asset("abc123.pdf")]))
    _reject_non_flat_asset_keys(_manifest(entries=[_file_entry("assets/abc123.pdf")]))

    # Path components in the asset key (incl. self-collision spellings) reject.
    for bad in ("nested/keep.pdf", "a/b/keep.pdf", "./keep.pdf"):
        with pytest.raises(ImportEngineError) as exc:
            _reject_non_flat_asset_keys(_manifest(assets=[_asset(bad)]))
        assert exc.value.code == "IMPORT_ZIP_INVALID"

    # And in a file entry's asset reference.
    with pytest.raises(ImportEngineError):
        _reject_non_flat_asset_keys(
            _manifest(entries=[_file_entry("assets/nested/keep.pdf")])
        )


async def test_backup_confirm_include_map_skips_tools(
    client, acting_user, session, monkeypatch, role_session
):
    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"include": {"queue": False}},
    )
    assert confirmed.status_code == 200

    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["per_tool"]["queue"]["skipped"] == 1
    assert job["result"]["per_tool"]["queue"]["created"] == 0


async def test_backup_corrupt_entry_fails_alone(
    client, acting_user, session, monkeypatch, role_session
):
    """One corrupt member fails its entry; the rest of the backup restores
    and the job completes with a per-entry report."""
    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    good_entry, good_envelope = _queue_entry()
    bad_entry = dict(good_entry)
    bad_entry["path"] = "initiatives/1-restored/queues/2-bad.initiative-queue.json"
    bad_entry["title"] = "Bad Queue"
    bad_entry["entity_id"] = 2
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[good_entry, bad_entry]),
        {
            good_entry["path"]: json.dumps(good_envelope).encode(),
            bad_entry["path"]: b"{corrupt json",
        },
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["per_tool"]["queue"] == {
        "created": 1,
        "failed": 1,
        "skipped": 0,
    }
    statuses = {e["title"]: e["status"] for e in job["result"]["entries"]}
    assert statuses == {"Restored Queue": "created", "Bad Queue": "failed"}


async def test_backup_seat_vacated_before_apply_fails_closed(
    client, acting_user, session, monkeypatch, role_session
):
    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text

    a.membership.role = GuildRole.member
    session.add(a.membership)
    await session.commit()

    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_SUPERADMIN_REQUIRED"


async def test_backup_quota_exceeded_fails_job(
    client, acting_user, session, monkeypatch, role_session
):
    from sqlmodel import select

    from app.models.platform.guild import Guild

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    guild = (await session.exec(select(Guild).where(Guild.id == a.guild.id))).one()
    await guild_administration(session, guild, max_storage_bytes=1)

    manifest = _minimal_manifest(
        assets=[
            {
                "path": "assets/huge.bin",
                "storage_key": "huge.bin",
                "original_filename": "huge.bin",
                "content_type": "application/octet-stream",
                "size_bytes": 1_000_000,
                "referenced_by": [],
            }
        ]
    )
    zip_bytes = _make_backup_zip(manifest, {"assets/huge.bin": b"x" * 1024})
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_QUOTA_EXCEEDED"


async def test_backup_staged_expiry_and_cancel(
    client, acting_user, session, monkeypatch
):
    """An unconfirmed staged backup expires via GC (payload deleted); a
    staged backup can also be cancelled; a cancelled/expired one can't be
    confirmed."""
    from datetime import datetime, timedelta, timezone

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    zip_bytes = _make_backup_zip(_minimal_manifest())

    staged = await _upload_backup(client, a, zip_bytes)
    job_id = staged.json()["id"]

    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    row = await session.get(ImportJob, job_id)
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.add(row)
    await session.commit()

    # TTL elapsed but GC hasn't swept yet: confirm must refuse and expire the
    # job NOW — a 200 here would queue a job GC silently kills with no
    # notification.
    raced = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert raced.status_code == 409
    assert raced.json()["detail"] == "IMPORT_NOT_CONFIRMABLE"
    await session.refresh(row)
    assert row.status == ImportJobStatus.expired
    assert row.payload_ref is None

    # GC stays idempotent over the already-expired row.
    await import_worker.process_import_gc()
    await session.refresh(row)
    assert row.status == ImportJobStatus.expired

    late = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert late.status_code == 409
    assert late.json()["detail"] == "IMPORT_NOT_CONFIRMABLE"

    second = await _upload_backup(client, a, zip_bytes)
    second_id = second.json()["id"]
    cancelled = await client.delete(
        a.g(f"/imports/jobs/{second_id}"), headers=a.headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == ImportJobStatus.cancelled.value


async def test_backup_restores_fresh_assets_into_storage(
    client, acting_user, session, monkeypatch, role_session
):
    """A cross-guild restore: the storage key doesn't exist here, so the blob
    is written into guild storage, an uploads row is registered, and the file
    document serves from the restored key."""
    from pathlib import Path

    from sqlmodel import select

    from app.models.tenant.upload import Upload

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    payload = b"%PDF-brand-new-blob"
    file_entry = {
        "path": "assets/from-elsewhere.pdf",
        "tool": "document",
        "type": "file",
        "schema_version": None,
        "entity_id": 1,
        "title": "Foreign Handout",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": "assets/from-elsewhere.pdf",
    }
    manifest = _minimal_manifest(
        entries=[file_entry],
        assets=[
            {
                "path": "assets/from-elsewhere.pdf",
                "storage_key": "from-elsewhere.pdf",
                "original_filename": "Foreign Handout.pdf",
                "content_type": "application/pdf",
                "size_bytes": len(payload),
                "referenced_by": [],
            }
        ],
    )
    zip_bytes = _make_backup_zip(manifest, {"assets/from-elsewhere.pdf": payload})

    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["assets_restored"] == 1
    assert job["result"]["asset_bytes"] == len(payload)

    blob = get_guild_storage(a.guild.id).open_readable("from-elsewhere.pdf")
    assert blob is not None
    assert Path(blob.path).read_bytes() == payload
    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    upload = (
        await session.exec(
            select(Upload).where(Upload.filename == "from-elsewhere.pdf")
        )
    ).one()
    assert upload.size_bytes == len(payload)
    assert upload.content_type == "application/pdf"


async def test_backup_quota_uses_zip_sizes_not_manifest_claims(
    client, acting_user, session, monkeypatch, role_session
):
    """The manifest is caller-supplied text: declaring size_bytes=1 for a
    large blob must NOT slip past the guild storage quota — the check
    accumulates the zip's own central-directory sizes."""
    from sqlmodel import select

    from app.models.platform.guild import Guild

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    guild = (await session.exec(select(Guild).where(Guild.id == a.guild.id))).one()
    await guild_administration(session, guild, max_storage_bytes=10_000)

    big_blob = b"x" * 50_000  # actual bytes far over the quota
    manifest = _minimal_manifest(
        assets=[
            {
                "path": "assets/liar.bin",
                "storage_key": "liar.bin",
                "original_filename": "liar.bin",
                "content_type": "application/octet-stream",
                "size_bytes": 1,  # understated claim
                "referenced_by": [],
            }
        ]
    )
    zip_bytes = _make_backup_zip(manifest, {"assets/liar.bin": big_blob})

    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_QUOTA_EXCEEDED"
    # Nothing was written despite the understated claim.
    assert get_guild_storage(a.guild.id).open_readable("liar.bin") is None


async def test_backup_asset_restore_guards_actual_bytes_not_declarations(
    acting_user, session
):
    """Central-directory sizes are declarations too: if a zip's real
    decompressed output exceeds what the quota pass approved (interpreter
    truncation is behavior, not a contract), the restore fails before
    writing past the approved bound."""
    import zipfile as zipfile_mod

    from app.schemas.tenant.backup_export import BackupManifest, ManifestAsset
    from app.schemas.tenant.import_job import BackupImportResult
    from app.services.import_engine.backup import _restore_assets
    from app.services.import_engine.contract import ImportEngineError
    from app.testing import route_session_to_guild

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    await route_session_to_guild(session, a.guild.id)

    class LyingArchive:
        """Declares 10 bytes in the central directory, emits 100_000."""

        def getinfo(self, name):
            info = zipfile_mod.ZipInfo(name)
            info.file_size = 10
            return info

        def read(self, name):
            return b"x" * 100_000

    manifest = BackupManifest(
        type="initiative-backup",
        schema_version=1,
        app_version="0.0.0-test",
        exported_at="2026-07-15T00:00:00+00:00",
        guild={"id": 1, "name": "g"},
        include_uploads=True,
        initiatives=[],
        entries=[],
        assets=[
            ManifestAsset(
                path="assets/liar.bin",
                storage_key="unit-liar.bin",
                original_filename="liar.bin",
                content_type="application/octet-stream",
                size_bytes=10,
                referenced_by=[],
            )
        ],
        skipped=[],
    )
    result = BackupImportResult()
    with pytest.raises(ImportEngineError) as exc_info:
        await _restore_assets(
            session, LyingArchive(), manifest, a.guild.id, a.user, result
        )
    assert exc_info.value.code == "IMPORT_QUOTA_EXCEEDED"
    assert get_guild_storage(a.guild.id).open_readable("unit-liar.bin") is None


# ---------------------------------------------------------------------------
# Posts: an import is a write like any other, held to the same limits
# ---------------------------------------------------------------------------


def _post_envelope(**overrides) -> dict:
    from app.testing import lexical_body

    return {
        "type": "initiative-post",
        "schema_version": 1,
        "name": "Notice",
        "body": lexical_body("Short enough."),
        "tags": [],
        **overrides,
    }


@pytest.mark.integration
async def test_importing_a_post_over_the_body_limit_is_refused(
    client, acting_user, session
):
    """Accepting it would store a post the endpoints refuse to accept or to
    save again."""
    from app.schemas.tenant.post import MAX_POST_TEXT_CHARS
    from app.testing import lexical_body

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()

    response = await _import_envelope(
        client,
        a,
        _post_envelope(body=lexical_body("x" * (MAX_POST_TEXT_CHARS + 1))),
        a.initiative.id,
    )
    assert response.status_code == 400


@pytest.mark.integration
async def test_importing_a_structurally_oversized_body_is_refused(
    client, acting_user, session
):
    """The character count is not the only ceiling. A body can hold almost no
    words and still be enormous — deeply nested empty nodes — and a normal
    write refuses that, so an import has to as well."""
    from app.schemas.tenant.post import MAX_POST_BODY_BYTES

    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()

    # Wide rather than wordy: thousands of empty paragraphs carry no text at
    # all, so the character limit lets them straight through.
    empty = {"type": "paragraph", "children": [], "version": 1, "format": ""}
    bloated = {"root": {"type": "root", "children": [empty] * 4000}}
    assert len(json.dumps(bloated).encode("utf-8")) > MAX_POST_BODY_BYTES

    response = await _import_envelope(
        client, a, _post_envelope(body=bloated), a.initiative.id
    )
    assert response.status_code == 400


@pytest.mark.integration
async def test_importing_a_long_headline_trims_rather_than_fails(
    client, acting_user, session
):
    """A headline is display text. The column holds 255, and failing a whole
    restore over a long title helps nobody — so it is trimmed and said."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True)
    a.initiative.posts_enabled = True
    session.add(a.initiative)
    await session.commit()

    response = await _import_envelope(
        client, a, _post_envelope(name="H" * 400), a.initiative.id
    )
    assert response.status_code in (200, 201, 202), response.text
    body = response.json()
    assert len(body["result"]["entity_title"]) <= 255
    assert any("shortened" in w.lower() for w in body["result"]["warnings"])


# ---------------------------------------------------------------------------
# What a project envelope now carries: when things happened, what was said on
# them, and what they point at
# ---------------------------------------------------------------------------


async def test_project_envelope_carries_comments_dates_and_links(
    client, acting_user, session
):
    """Export a project whose tasks have comments, real creation dates and an
    edge between them; import it somewhere else and find all three.

    This is the round trip the whole deferred pass exists for: the edge is
    between two tasks written by the same entry, so it resolves; the dates are
    the ones the source had, not the moment of the restore; and the comment
    arrives attributed to the person who ran the import, with its original
    author named in the text rather than impersonated.
    """
    from datetime import datetime, timezone

    from sqlmodel import select

    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.comment import Comment
    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.relationships import Endpoint
    from app.testing.factories import create_comment

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    written_at = datetime(2024, 3, 4, 9, 30, tzinfo=timezone.utc)
    blocker = await create_task(
        session, a.project, title="Pour the footings", created_at=written_at
    )
    blocked = await create_task(session, a.project, title="Raise the frame")
    await create_comment(session, a.user, task=blocker, content="Frost delayed us")
    await relationships_service.create(
        session,
        source=Endpoint(kind=SearchEntityType.task, id=blocked.id),
        relationship_type=RelationshipType.depends_on,
        target=Endpoint(kind=SearchEntityType.task, id=blocker.id),
        created_by=a.user.id,
    )
    await session.commit()

    envelope = await _export_json(
        client, a, "/exports/project", {"project_id": a.project.id}
    )
    by_title = {task["title"]: task for task in envelope["tasks"]}
    assert by_title["Pour the footings"]["created_at"].startswith("2024-03-04")
    assert by_title["Pour the footings"]["comments"][0]["body"] == "Frost delayed us"
    assert by_title["Raise the frame"]["links"] == [
        {
            "type": "depends_on",
            "target_external_ref": f"task:{blocker.id}",
        }
    ]

    target = await _second_initiative(session, a)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert result["created"]["comments"] == 1
    assert (result["links_created"], result["links_unresolved"]) == (1, 0)

    project = (
        await session.exec(select(Project).where(Project.initiative_id == target.id))
    ).one()
    tasks = {
        task.title: task
        for task in (
            await session.exec(select(Task).where(Task.project_id == project.id))
        ).all()
    }
    assert tasks["Pour the footings"].created_at == written_at

    comment = (
        await session.exec(
            select(Comment).where(Comment.task_id == tasks["Pour the footings"].id)
        )
    ).one()
    # The author's handle is a member of the target initiative, so the comment
    # is theirs — nothing is added to what they said.
    assert comment.created_by == a.user.id
    assert comment.content == "Frost delayed us"
    assert comment.imported_author_name is None

    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.task, id=tasks["Raise the frame"].id),
        relationship_type=RelationshipType.depends_on,
        other_kind=SearchEntityType.task,
    ) == [tasks["Pour the footings"].id]


async def test_envelope_link_out_of_the_file_is_counted(client, acting_user, session):
    """A link whose far end is not in this envelope is ordinary — a number in
    the report, not a refusal."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = {
        "type": "initiative-project",
        "schema_version": 1,
        "app_version": "0.0.0-test",
        "exported_at": "2026-07-15T00:00:00+00:00",
        "project": {"name": "Imported Board"},
        "tags": [],
        "task_statuses": [
            {"name": "To Do", "category": "todo", "position": 0, "is_default": True}
        ],
        "property_definitions": [],
        "tasks": [
            {
                "title": "Fit the door",
                "status_name": "To Do",
                "external_ref": "jira:ACME-1",
                "tags": [],
                "assignee_handles": [],
                "checklist": [],
                "property_values": [],
                "links": [
                    {"type": "related_to", "target_external_ref": "jira:OTHER-9"}
                ],
            }
        ],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text
    result = resp.json()["result"]
    assert (result["links_created"], result["links_unresolved"]) == (0, 1)


# ---------------------------------------------------------------------------
# What a backup manifest now says: where an entry is filed, and where the
# bundle should land
# ---------------------------------------------------------------------------


async def test_backup_attach_to_files_a_document_in_its_wiki(
    client, acting_user, session, monkeypatch, role_session
):
    """A file document that sat in a wiki still sits in it after a restore.

    The edge names two rows whose ids the archive cannot carry, so it crosses
    as ``attach_to`` on the document's entry, pointing at the wiki's entry
    path. Both are applied as ordinary entries and the edge is written once
    the pass runs — which is why the document entry can come first.
    """
    from sqlmodel import select

    from app.core.relationships import RelationshipType
    from app.core.search import SearchEntityType
    from app.models.tenant.document import Document, DocumentType
    from app.models.tenant.initiative import Initiative
    from app.models.tenant.wiki import Wiki
    from app.services.tenant import relationships as relationships_service
    from app.services.tenant.relationships import Endpoint
    from app.testing.factories import create_upload

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    payload = b"%PDF-field-notes"
    get_guild_storage(a.guild.id).write(
        "field-notes.pdf", payload, content_type="application/pdf"
    )
    await create_upload(
        session,
        a.guild,
        a.user,
        filename="field-notes.pdf",
        size_bytes=len(payload),
        content_type="application/pdf",
    )

    wiki_path = "initiatives/1-restored/wikis/7-handbook.initiative-wiki.json"
    wiki_envelope = {
        "type": "initiative-wiki",
        "schema_version": 1,
        "name": "Handbook",
        "pages": [],
    }
    wiki_entry = {
        "path": wiki_path,
        "tool": "wiki",
        "type": "initiative-wiki",
        "schema_version": 1,
        "entity_id": 7,
        "title": "Handbook",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    file_entry = {
        "path": "assets/field-notes.pdf",
        "tool": "document",
        "type": "file",
        "schema_version": None,
        "entity_id": 3,
        "title": "Field notes",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": "assets/field-notes.pdf",
        "attach_to": {"kind": "wiki", "ref": wiki_path},
    }
    manifest = _minimal_manifest(entries=[file_entry, wiki_entry])
    manifest["initiatives"][0]["tools"]["wiki"] = "included"
    zip_bytes = _make_backup_zip(
        manifest,
        {
            wiki_path: json.dumps(wiki_envelope).encode(),
            "assets/field-notes.pdf": payload,
        },
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["links_created"] == 1

    restored = (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one()
    wiki = (
        await session.exec(select(Wiki).where(Wiki.initiative_id == restored.id))
    ).one()
    document = (
        await session.exec(
            select(Document).where(
                Document.initiative_id == restored.id,
                Document.document_type == DocumentType.file,
            )
        )
    ).one()
    assert await relationships_service.related_ids(
        session,
        Endpoint(kind=SearchEntityType.document, id=document.id),
        relationship_type=RelationshipType.part_of,
        other_kind=SearchEntityType.wiki,
    ) == [wiki.id]


async def test_backup_applies_into_an_existing_initiative(
    client, acting_user, session, monkeypatch, role_session
):
    """A bundle naming ``target_initiative_id`` lands in an initiative
    somebody already runs, instead of creating one.

    This is what a foreign source needs: a Jira project belongs on a board in
    an initiative that exists, and choosing that is the importer's call, not
    ours. No new initiative appears, and nothing about the target's name or
    tool switches is touched.
    """
    from sqlmodel import select

    from app.models.tenant.initiative import Initiative
    from app.models.tenant.queue import Queue

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    target = await _second_initiative(session, a)
    before = len((await session.exec(select(Initiative.id))).all())

    entry, envelope = _queue_entry()
    manifest = _minimal_manifest(entries=[entry])
    manifest["initiatives"][0]["target_initiative_id"] = target.id
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")
    assert job["result"]["initiatives"][0]["initiative_id"] == target.id

    assert len((await session.exec(select(Initiative.id))).all()) == before
    assert (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one_or_none() is None

    queue = (
        await session.exec(select(Queue).where(Queue.initiative_id == target.id))
    ).one()
    assert queue.name == "Restored Queue"


async def test_backup_into_an_unreachable_initiative_fails_the_job(
    client, acting_user, session, monkeypatch, role_session
):
    """An initiative the importer cannot reach is indistinguishable from one
    that is not there, and neither is a place to write to."""
    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )

    entry, envelope = _queue_entry()
    manifest = _minimal_manifest(entries=[entry])
    manifest["initiatives"][0]["target_initiative_id"] = 10_000_000
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_INVALID_PARAMS"


# ---------------------------------------------------------------------------
# The fetching status
# ---------------------------------------------------------------------------


async def test_a_stale_fetch_is_re_claimed_not_failed(
    client, acting_user, session, monkeypatch, role_session
):
    """A crashed fetch goes back in the queue; a crashed apply does not.

    The difference is what is already in the database. An apply has committed
    rows under the always-create policy, so re-running it would duplicate
    them. A fetch has written nothing but a payload in storage, so there is
    nothing to duplicate — the partial payload is thrown away and the job
    starts over.
    """
    from datetime import datetime, timedelta, timezone

    from sqlmodel import select

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=3)
    job = ImportJob(
        created_by=a.user.id,
        source="atlassian",
        params={"initiative_id": a.initiative.id},
        payload_ref="imports/half-written.json",
        status=ImportJobStatus.fetching,
    )
    session.add(job)
    await session.commit()
    # updated_at is stamped on write, so age it afterwards.
    await session.exec(
        ImportJob.__table__.update()
        .where(ImportJob.__table__.c.id == job.id)
        .values(updated_at=long_ago)
    )
    await session.commit()

    await _run_import_worker(monkeypatch, role_session)

    session.expunge_all()
    reclaimed = (
        await session.exec(select(ImportJob).where(ImportJob.id == job.id))
    ).one()
    # It left ``fetching`` and its half-written payload is gone, so the fetch
    # can start clean. It is NOT the apply path's fail-closed outcome, which
    # is the distinction this rule exists to make. (The same pass then picks
    # the queued row up and starts the fetch over, which fails on the spot:
    # this row was never given a credential to read the site with.)
    assert reclaimed.status is not ImportJobStatus.fetching
    assert reclaimed.error != "IMPORT_INTERRUPTED"
    assert reclaimed.payload_ref != "imports/half-written.json"
    assert (
        get_guild_storage(a.guild.id).open_readable("imports/half-written.json") is None
    )


# ---------------------------------------------------------------------------
# Who said what: matching a comment's author to an account here
# ---------------------------------------------------------------------------


def _project_envelope_with_comment(author_handle: str, author_name: str) -> dict:
    """A one-task project whose task carries one comment by somebody else."""
    return {
        "type": "initiative-project",
        "schema_version": 1,
        "app_version": "0.0.0-test",
        "exported_at": "2026-07-15T00:00:00+00:00",
        "project": {"name": "Imported Board"},
        "tags": [],
        "task_statuses": [
            {"name": "To Do", "category": "todo", "position": 0, "is_default": True}
        ],
        "property_definitions": [],
        "tasks": [
            {
                "title": "Fit the door",
                "status_name": "To Do",
                "tags": [],
                "assignee_handles": [],
                "checklist": [],
                "property_values": [],
                "comments": [
                    {
                        "author_handle": author_handle,
                        "author_name": author_name,
                        "body": "The frame is out of true",
                        "created_at": "2024-03-04T09:30:00+00:00",
                    }
                ],
            }
        ],
    }


async def test_an_unmatched_author_keeps_their_name_and_no_account(
    client, acting_user, session, monkeypatch, role_session
):
    """Nobody here is somebody. The comment carries the name it arrived with
    and is credited to no account — not to whoever ran the import.

    The envelope quotes a stranger, so it is staged rather than applied and
    the importer is asked who that is; leaving the row blank is the answer
    this test gives, and it is a real one.
    """
    from sqlmodel import select

    from app.models.tenant.comment import Comment

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"

    confirm = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"), headers=a.headers, json={}
    )
    assert confirm.status_code == 200, confirm.text
    user_session = await role_session("app_user")
    monkeypatch.setattr(import_worker, "_open_user_session", lambda: user_session)
    await import_worker.process_import_jobs()

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    # The row names what wrote it, because every guild-content row does...
    assert comment.created_by == a.user.id
    # ...and the name rides beside it, which is what the reader sees.
    assert comment.imported_author_name == "Alice Chen"


async def test_an_envelope_quoting_a_stranger_asks_before_it_applies(
    client, acting_user, session
):
    """The people step for a lone envelope: nothing is written until somebody
    has answered, and the plan is the question."""
    from sqlmodel import select

    from app.models.tenant.project import Project

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"
    assert job["plan"]["people"] == [
        {
            "handle": "stranger#4321",
            "name": "Alice Chen",
            "comment_count": 1,
            "suggested_user_id": None,
        }
    ]
    # Staged means staged: the board does not exist yet.
    assert not (
        await session.exec(select(Project).where(Project.name == "Imported Board"))
    ).all()


async def test_an_envelope_naming_strangers_only_as_assignees_still_asks(
    client, acting_user, session
):
    """Assignees go through the people step's answer too, so an envelope
    whose only people are assignees is a question like any other. It used to
    apply on the spot and report them afterwards as unmatched — which is what
    every Todoist, TickTick and Vikunja export did, since those name people
    only as the person responsible for a task."""
    from sqlmodel import select

    from app.models.tenant.project import Project

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["comments"] = []
    envelope["tasks"][0]["assignee_handles"] = ["Jordan", "Mel"]
    envelope["tasks"].append(
        {**envelope["tasks"][0], "title": "Hang it", "assignee_handles": ["Mel"]}
    )

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"
    assert job["plan"]["people"] == [
        {
            "handle": handle,
            "name": None,
            "comment_count": 0,
            "suggested_user_id": None,
        }
        for handle in ("Jordan", "Mel")
    ]
    assert not (
        await session.exec(select(Project).where(Project.name == "Imported Board"))
    ).all()


async def test_the_people_step_decides_who_an_imported_task_is_assigned_to(
    client, acting_user, session, monkeypatch, role_session
):
    """The answer to the step is what lands: a handle nobody here goes by,
    mapped to a member of the initiative, is that member's task."""
    from sqlmodel import select

    from app.models.tenant.task import Task, TaskAssignee

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["comments"] = []
    envelope["tasks"][0]["assignee_handles"] = ["Jordan"]

    job = (await _import_envelope(client, a, envelope, a.initiative.id)).json()
    assert job["status"] == "staged"
    confirmed = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"),
        headers=a.headers,
        json={"people_map": {"Jordan": a.user.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    done = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert done["status"] == "done", done.get("error")
    assert done["result"]["unmatched_handles"] == []

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the door"))).one()
    assignees = (
        await session.exec(select(TaskAssignee).where(TaskAssignee.task_id == task.id))
    ).all()
    assert [row.user_id for row in assignees] == [a.user.id]


async def test_a_user_property_is_placed_by_the_people_step(
    client, acting_user, session, monkeypatch, role_session
):
    """A user-type property — a Reporter — names a person the way an assignee
    does, so it is asked about the same way, and the answer is what lands."""
    from sqlmodel import select

    from app.models.tenant.property import TaskPropertyValue
    from app.models.tenant.task import Task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["comments"] = []
    envelope["property_definitions"] = [
        {"name": "Reporter", "type": "user_reference", "position": 0}
    ]
    envelope["tasks"][0]["property_values"] = [
        {
            "property_name": "Reporter",
            "property_type": "user_reference",
            "value_handle": "Robin",
        }
    ]

    job = (await _import_envelope(client, a, envelope, a.initiative.id)).json()
    assert job["status"] == "staged", job
    assert [p["handle"] for p in job["plan"]["people"]] == ["Robin"]

    await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"),
        headers=a.headers,
        json={"people_map": {"Robin": a.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)
    done = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert done["status"] == "done", done.get("error")

    session.expunge_all()
    task = (await session.exec(select(Task).where(Task.title == "Fit the door"))).one()
    values = (
        await session.exec(
            select(TaskPropertyValue).where(TaskPropertyValue.task_id == task.id)
        )
    ).all()
    assert [v.value_user_id for v in values] == [a.user.id]


async def test_a_document_naming_somebody_in_a_property_asks_first(
    client, acting_user, session
):
    """Documents used to be an envelope that names nobody. A user-type
    property on one names somebody, so it stops to ask."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = {
        "type": "initiative-document",
        "schema_version": 1,
        "document_type": "smart_link",
        "name": "Spec",
        "content": {"url": "https://example.com"},
        "tags": [],
        "properties": [
            {
                "property_name": "Owner",
                "property_type": "user_reference",
                "value_handle": "Robin",
            }
        ],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == "staged"
    assert job["plan"]["people"] == [
        {
            "handle": "Robin",
            "name": None,
            "comment_count": 0,
            "suggested_user_id": None,
        }
    ]


async def test_an_envelope_whose_people_all_match_is_not_a_second_step(
    client, acting_user, session
):
    """Asking somebody to agree with a screen full of correct answers is not
    a step. Every handle matching a member exactly means there is nothing to
    decide, so the file imports on one click, as it always did."""
    from app.core.user_display import handle_of

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    envelope = _project_envelope_with_comment(handle_of(b.user), "Someone Else")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text


async def test_only_the_creator_answers_an_envelopes_people_step(
    client, acting_user, session
):
    """A guild admin can SEE somebody else's staged job — RLS says so. Saying
    who its people are on their behalf is a different thing."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    admin = await acting_user(guild_role=GuildRole.admin, guild=a.guild)

    resp = await _import_envelope(
        client,
        a,
        _project_envelope_with_comment("stranger#4321", "Alice Chen"),
        a.initiative.id,
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]

    stolen = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=admin.headers, json={}
    )
    assert stolen.status_code == 403, stolen.text
    assert stolen.json()["detail"] == "IMPORT_NOT_CONFIRMABLE"


async def test_the_people_map_decides_who_an_envelopes_assignee_is(
    client, acting_user, session, monkeypatch, role_session
):
    """An assignee goes through the map like an author does — but the
    initiative's roster still has the last word, because being assigned
    something is a statement about who is working here now."""
    from sqlmodel import select

    from app.models.tenant.task import Task, TaskAssignee

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    inside = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    # In the community, not in this initiative — so the map may name them and
    # the assignment still must not land.
    outside = await acting_user(guild_role=GuildRole.member, guild=a.guild)

    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    envelope["tasks"][0]["assignee_handles"] = ["ghost#1111", "phantom#2222"]

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["id"]

    confirm = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={
            "people_map": {
                "ghost#1111": inside.user.id,
                "phantom#2222": outside.user.id,
            }
        },
    )
    assert confirm.status_code == 200, confirm.text
    user_session = await role_session("app_user")
    monkeypatch.setattr(import_worker, "_open_user_session", lambda: user_session)
    await import_worker.process_import_jobs()

    task = (await session.exec(select(Task).where(Task.title == "Fit the door"))).one()
    assignees = (
        await session.exec(select(TaskAssignee).where(TaskAssignee.task_id == task.id))
    ).all()
    assert [row.user_id for row in assignees] == [inside.user.id]


async def test_an_exact_handle_match_makes_the_comment_theirs(
    client, acting_user, session
):
    """A handle that is already a member of the initiative it is landing in
    needs nobody to confirm it: it is the same identifier."""
    from sqlmodel import select

    from app.core.user_display import handle_of
    from app.models.tenant.comment import Comment

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=a.initiative,
        initiative_role="member",
    )
    envelope = _project_envelope_with_comment(handle_of(b.user), "Someone Else")

    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    assert comment.created_by == b.user.id
    assert comment.imported_author_name is None


async def test_the_plan_lists_the_people_and_suggests_the_exact_matches(
    client, acting_user, session
):
    """The wizard's people step is rendered from the plan, so the plan has to
    carry everyone the archive quotes — read from the manifest, because the
    plan never opens an envelope."""
    from app.core.user_display import handle_of

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    manifest = _minimal_manifest(entries=[entry])
    manifest["people"] = [
        {"handle": handle_of(a.user), "name": "The Importer", "comment_count": 4},
        {"handle": "stranger#4321", "name": "Alice Chen", "comment_count": 1},
    ]
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    people = resp.json()["plan"]["people"]
    by_handle = {person["handle"]: person for person in people}

    # A member of this guild, by exact handle — offered as the answer.
    assert by_handle[handle_of(a.user)]["suggested_user_id"] == a.user.id
    assert by_handle[handle_of(a.user)]["comment_count"] == 4
    # A name nobody here answers to is left for a person to decide.
    assert by_handle["stranger#4321"]["suggested_user_id"] is None


async def test_the_confirmed_mapping_decides_who_a_comment_belongs_to(
    client, acting_user, session, monkeypatch, role_session
):
    """The people step's whole purpose: a name that matches nobody becomes
    somebody, because a person said so."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    b = await acting_user(guild_role=GuildRole.member, guild=a.guild)

    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    entry = {
        "path": "initiatives/1-restored/projects/1-board.initiative-project.json",
        "tool": "project",
        "type": "initiative-project",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Imported Board",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    manifest = _minimal_manifest(entries=[entry])
    manifest["people"] = [
        {"handle": "stranger#4321", "name": "Alice Chen", "comment_count": 1}
    ]
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"stranger#4321": b.user.id}},
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    assert comment.created_by == b.user.id
    assert comment.imported_author_name is None


async def test_a_mapping_naming_a_non_member_is_dropped(
    client, acting_user, session, monkeypatch, role_session
):
    """The confirm may be hours old. Somebody named in it who has since left
    the community does not get authorship of anything."""
    from sqlmodel import select

    from app.models.tenant.comment import Comment

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    outsider = await acting_user(guild_role=GuildRole.member)

    envelope = _project_envelope_with_comment("stranger#4321", "Alice Chen")
    entry = {
        "path": "initiatives/1-restored/projects/1-board.initiative-project.json",
        "tool": "project",
        "type": "initiative-project",
        "schema_version": 1,
        "entity_id": 1,
        "title": "Imported Board",
        "initiative_id": 1,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    manifest = _minimal_manifest(entries=[entry])
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(envelope).encode()}
    )

    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    # An account in a different guild entirely — the map names them anyway.
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"stranger#4321": outsider.user.id}},
    )
    await _run_import_worker(monkeypatch, role_session)

    comment = (
        await session.exec(
            select(Comment).where(Comment.content == "The frame is out of true")
        )
    ).one()
    assert comment.created_by != outsider.user.id
    assert comment.imported_author_name == "Alice Chen"


async def test_confirm_refuses_a_malformed_people_map(client, acting_user, session):
    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]

    bad = await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"),
        headers=a.headers,
        json={"people_map": {"stranger#4321": "not-an-id"}},
    )
    assert bad.status_code == 400
    assert bad.json()["detail"] == "IMPORT_INVALID_PARAMS"


# ---------------------------------------------------------------------------
# An initiative's own shape: property definitions, roles and members
# ---------------------------------------------------------------------------


def _structural_entry(type_: str, payload: dict, initiative_id=1):  # noqa: D401
    """One of the two files describing the initiative rather than its content."""
    name = type_.removeprefix("initiative-")
    entry = {
        "path": f"initiatives/1-restored/{name}.json",
        "tool": "initiative",
        "type": type_,
        "schema_version": 1,
        "entity_id": initiative_id,
        "title": "Restored",
        "initiative_id": initiative_id,
        "tags": [],
        "properties": [],
        "asset": None,
    }
    return entry, payload


async def test_backup_restores_property_definitions_in_full(
    client, acting_user, session, monkeypatch, role_session
):
    """The definitions arrive as they were, rather than being rebuilt from
    whichever values happened to reference them."""
    from sqlmodel import select

    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    entry, payload = _structural_entry(
        "initiative-properties",
        {
            "type": "initiative-properties",
            "schema_version": 1,
            "properties": [
                {
                    "name": "Region",
                    "type": "select",
                    "position": 0,
                    "color": "#abcdef",
                    "options": [
                        {"id": "n", "label": "North"},
                        {"id": "s", "label": "South"},
                    ],
                }
            ],
        },
    )
    manifest = _minimal_manifest(entries=[entry])
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(payload).encode()}
    )

    job = await _apply_backup(client, a, zip_bytes, monkeypatch, role_session)
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    from app.models.tenant.property import PropertyDefinition

    await route_session_to_guild(session, a.guild.id)
    definitions = {
        d.name: d
        for d in await session.exec(select(PropertyDefinition))
        if d.name == "Region"
    }
    region = definitions["Region"]
    assert [o["label"] for o in region.options] == ["North", "South"]
    assert region.color == "#abcdef"


async def test_backup_restores_roles_and_places_members(
    client, acting_user, session, monkeypatch, role_session
):
    """Roles the target lacks are created; people already in the community are
    placed into the initiative at the role the archive names."""
    from sqlmodel import select

    from app.core.user_display import handle_of
    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    other = await acting_user(guild_role=GuildRole.member, guild=a.guild)
    handle = handle_of(other.user)

    entry, payload = _structural_entry(
        "initiative-structure",
        {
            "type": "initiative-structure",
            "schema_version": 1,
            "roles": [
                {
                    "name": "lorekeeper",
                    "display_name": "Lorekeeper",
                    "is_manager": False,
                    "override_share_restrictions": False,
                    "position": 5,
                    "permissions": ["create_documents"],
                }
            ],
            "members": [{"handle": handle, "role": "lorekeeper"}],
        },
    )
    manifest = _minimal_manifest(entries=[entry])
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(payload).encode()}
    )

    job = await _apply_backup(client, a, zip_bytes, monkeypatch, role_session)
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    from app.models.tenant.initiative import (
        Initiative,
        InitiativeMember,
        InitiativeRoleModel,
    )

    await route_session_to_guild(session, a.guild.id)
    created = (
        await session.exec(select(Initiative).where(Initiative.name == "Restored"))
    ).one()
    role = (
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == created.id,
                InitiativeRoleModel.name == "lorekeeper",
            )
        )
    ).one()
    assert role.display_name == "Lorekeeper"
    member = (
        await session.exec(
            select(InitiativeMember).where(
                InitiativeMember.initiative_id == created.id,
                InitiativeMember.user_id == other.user.id,
            )
        )
    ).one()
    assert member.role_id == role.id


async def test_backup_structure_never_overwrites_what_is_already_there(
    client, acting_user, session, monkeypatch, role_session
):
    """Applying is additive: a role of the same name is the target's answer,
    and nobody is removed or moved by an import."""
    from sqlmodel import select

    from app.testing import route_session_to_guild

    a = await acting_user(
        guild_role=GuildRole.superadmin, initiative=True, project=True
    )
    entry, payload = _structural_entry(
        "initiative-structure",
        {
            "type": "initiative-structure",
            "schema_version": 1,
            # A name every initiative already has.
            "roles": [
                {
                    "name": "member",
                    "display_name": "Renamed By The Archive",
                    "is_manager": True,
                    "permissions": [],
                }
            ],
            "members": [],
        },
    )
    manifest = _minimal_manifest(entries=[entry], initiative_id=a.initiative.id)
    manifest["initiatives"][0]["target_initiative_id"] = a.initiative.id
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(payload).encode()}
    )

    job = await _apply_backup(client, a, zip_bytes, monkeypatch, role_session)
    assert job["status"] == ImportJobStatus.done.value, job.get("error")

    from app.models.tenant.initiative import InitiativeRoleModel

    await route_session_to_guild(session, a.guild.id)
    roles = list(
        await session.exec(
            select(InitiativeRoleModel).where(
                InitiativeRoleModel.initiative_id == a.initiative.id,
                InitiativeRoleModel.name == "member",
            )
        )
    )
    assert len(roles) == 1
    assert roles[0].display_name != "Renamed By The Archive"


# ---------------------------------------------------------------------------
# Atlassian connect
# ---------------------------------------------------------------------------


def _atlassian_site(*, jira_status=200, confluence_status=200):
    """Stub one Atlassian site for the endpoint's egress."""
    import httpx

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/rest/api/3/project/search" in url:
            if jira_status != 200:
                return httpx.Response(jira_status, json={})
            return httpx.Response(
                200, json={"values": [{"id": "1", "key": "ACME", "name": "Acme"}]}
            )
        if "/rest/api/3/search/approximate-count" in url:
            return httpx.Response(200, json={"count": 12})
        if "/wiki/api/v2/spaces" in url:
            if confluence_status != 200:
                return httpx.Response(confluence_status, json={})
            return httpx.Response(
                200, json={"results": [{"id": "9", "key": "DOCS", "name": "Docs"}]}
            )
        if "/wiki/rest/api/search" in url:
            return httpx.Response(200, json={"totalSize": 4})
        return httpx.Response(404, json={})

    return fake_request


async def _connect(client, actor, **overrides):
    body = {
        "site_url": "https://acme.atlassian.net",
        "email": "someone@example.com",
        "api_token": "shhh",
        **overrides,
    }
    return await client.post(
        actor.g("/imports/atlassian/connect"), headers=actor.headers, json=body
    )


async def test_connect_proves_the_token_and_says_what_is_there(
    client, acting_user, session, monkeypatch
):
    """One request answers both of the connect step's questions."""
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(atlassian_service, "request_public_target", _atlassian_site())
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    resp = await _connect(client, a)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["site_url"] == "https://acme.atlassian.net"
    assert body["jira"]["available"] is True
    assert [(p["key"], p["issue_count"]) for p in body["jira"]["projects"]] == [
        ("ACME", 12)
    ]
    assert [(s["key"], s["page_count"]) for s in body["confluence"]["spaces"]] == [
        ("DOCS", 4)
    ]

    # The connect keeps nothing and hands nothing back to quote: the token
    # comes again with the request that starts an import.
    assert "shhh" not in resp.text
    assert "credential_id" not in body


async def test_a_rejected_token_is_an_error_not_a_connection(
    client, acting_user, session, monkeypatch
):
    """A token the site will not take fails the connect."""
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(
        atlassian_service,
        "request_public_target",
        _atlassian_site(jira_status=401),
    )
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    resp = await _connect(client, a)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_SOURCE_AUTH"


async def test_connect_refuses_an_address_it_would_have_to_downgrade_for(
    client, acting_user, monkeypatch
):
    """http would put the token on the wire in the clear, so the address is
    refused before anything is sent anywhere."""
    from app.services.import_engine import atlassian as atlassian_service

    async def never_called(*a, **kw):  # pragma: no cover - must not run
        raise AssertionError("no request should be made for a refused address")

    monkeypatch.setattr(atlassian_service, "request_public_target", never_called)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    resp = await _connect(client, a, site_url="http://acme.atlassian.net")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_SOURCE_UNREACHABLE"


# ---------------------------------------------------------------------------
# A Jira import as a job: start → fetch → review → apply
# ---------------------------------------------------------------------------


_JIRA_STATUSES = [
    {
        "name": "Story",
        "statuses": [
            {"id": "1", "name": "To Do", "statusCategory": {"key": "new"}},
            {"id": "2", "name": "Done", "statusCategory": {"key": "done"}},
        ],
    }
]


def _jira_site(*, issues=None, locked=(), on_request=None):
    """Stub a site that answers both a connect and a fetch.

    ``locked`` names projects the token cannot read; ``on_request`` sees every
    URL before it is answered, which is how a test reaches into the middle of
    a fetch.
    """
    import httpx

    probe = _atlassian_site()
    requested: list[str] = []

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        requested.append(url)
        if on_request is not None:
            await on_request(url)
        if any(f"/rest/api/3/project/{key}" in url for key in locked):
            return httpx.Response(403, json={})
        if "/rest/api/3/project/search" in url:
            return await probe(method, url, headers=headers, json=json)
        if url.endswith("/statuses"):
            return httpx.Response(200, json=_JIRA_STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"key": key, "name": f"{key} Board"})
        if "/rest/api/3/search/jql" in url:
            return httpx.Response(200, json={"issues": issues or []})
        if "/rest/agile/1.0/board?" in url:
            return httpx.Response(404, json={})
        return await probe(method, url, headers=headers, json=json)

    fake_request.requested = requested  # type: ignore[attr-defined]
    return fake_request


def _jira_issue(key, summary, status="To Do", assignee=None):
    fields = {"summary": summary, "status": {"name": status}}
    if assignee:
        fields["assignee"] = {"displayName": assignee}
    return {"key": key, "fields": fields}


async def _start_jira(client, actor, *, initiative_id, keys=("ACME",), **overrides):
    body = {
        "site_url": "https://acme.atlassian.net",
        "email": "someone@example.com",
        "api_token": "shhh",
        "initiative_id": initiative_id,
        "project_keys": list(keys),
        **overrides,
    }
    return await client.post(
        actor.g("/imports/atlassian/jira"), headers=actor.headers, json=body
    )


async def _job_secret(session, guild_id, job_id):
    """The secret still on a job row, read as the system engine."""
    from app.db.session import set_rls_context

    session.expunge_all()
    await set_rls_context(session, guild_id=guild_id)
    job = await session.get(ImportJob, job_id)
    return None if job is None else job.secret_encrypted


async def test_a_jira_import_fetches_then_waits_for_review_then_applies(
    client, acting_user, session, monkeypatch, role_session
):
    """The whole path, once: the fetch reads the site into a bundle and parks
    it for review with nothing written, the review names the people and the
    counts, and the confirm files the project into the chosen initiative.

    The credential is gone the moment the bundle is staged — the review can
    wait for hours, and it has no need of a live secret to do it.
    """
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.services.import_engine import atlassian as atlassian_service

    site = _jira_site(
        issues=[
            _jira_issue("ACME-1", "Wire the thing", assignee="Pat Smith"),
            _jira_issue("ACME-2", "Ship the thing", status="Done"),
        ]
    )
    monkeypatch.setattr(atlassian_service, "request_public_target", site)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    resp = await _start_jira(client, a, initiative_id=a.initiative.id)
    assert resp.status_code == 202, resp.text
    job = resp.json()
    assert job["status"] == ImportJobStatus.queued.value
    assert job["source"] == "atlassian"
    assert job["params"]["jira_projects"] == ["ACME"]
    assert job["params"]["site_url"] == "https://acme.atlassian.net"
    assert "shhh" not in resp.text

    await _run_import_worker(monkeypatch, role_session)
    staged = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert staged["status"] == ImportJobStatus.staged.value, staged.get("error")
    plan = staged["plan"]
    assert plan["atlassian"]["projects"] == 1
    assert plan["atlassian"]["tasks"] == 2
    assert plan["atlassian"]["unreadable_projects"] == []
    assert plan["initiatives"][0]["target_initiative_id"] == a.initiative.id
    assert [p["handle"] for p in plan["people"]] == ["Pat Smith"]

    # Fetched, not applied: no project yet, and the token is already gone.
    assert (
        await session.exec(select(Project).where(Project.name == "ACME Board"))
    ).one_or_none() is None
    assert await _job_secret(session, a.guild.id, job["id"]) is None

    confirmed = await client.post(
        a.g(f"/imports/jobs/{job['id']}/confirm"), headers=a.headers, json={}
    )
    assert confirmed.status_code == 200, confirmed.text
    await _run_import_worker(monkeypatch, role_session)

    done = (
        await client.get(a.g(f"/imports/jobs/{job['id']}"), headers=a.headers)
    ).json()
    assert done["status"] == ImportJobStatus.done.value, done.get("error")
    assert done["result"]["initiatives"][0]["initiative_id"] == a.initiative.id

    session.expunge_all()
    project = (
        await session.exec(select(Project).where(Project.name == "ACME Board"))
    ).one()
    assert project.initiative_id == a.initiative.id
    titles = {
        t.title
        for t in (
            await session.exec(select(Task).where(Task.project_id == project.id))
        ).all()
    }
    assert titles == {"Wire the thing", "Ship the thing"}


async def test_starting_a_jira_import_refuses_what_it_can_up_front(
    client, acting_user, session, monkeypatch
):
    """Everything that can be refused before the site is read is refused
    before the site is read, so the answer arrives in the wizard rather than
    as a failed job minutes later."""
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(atlassian_service, "request_public_target", _jira_site())
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)

    nothing = await _start_jira(client, a, initiative_id=a.initiative.id, keys=())
    assert nothing.status_code == 400
    assert nothing.json()["detail"] == "IMPORT_SOURCE_NOTHING_SELECTED"

    # A key travels into a URL path and a JQL clause at the other end, so one
    # that is not shaped like a Jira key never gets that far.
    malformed = await _start_jira(
        client,
        a,
        initiative_id=a.initiative.id,
        keys=('ACME" OR project = "X',),
    )
    assert malformed.status_code == 422

    target = await _second_initiative(session, a, projects_enabled=False)
    disabled = await _start_jira(client, a, initiative_id=target.id)
    assert disabled.status_code == 400
    assert disabled.json()["detail"] == "IMPORT_TOOL_DISABLED"

    first = await _start_jira(client, a, initiative_id=a.initiative.id)
    assert first.status_code == 202, first.text
    # Each job carries its own secret, so a second import of the same site is
    # an ordinary second job rather than a contested connection.
    second = await _start_jira(client, a, initiative_id=a.initiative.id)
    assert second.status_code == 202, second.text
    assert second.json()["id"] != first.json()["id"]


async def test_a_site_that_refuses_every_project_fails_the_job_and_drops_the_token(
    client, acting_user, session, monkeypatch, role_session
):
    """A failed fetch is a failed job with a code, a notification, and no
    credential left behind."""
    from sqlmodel import select

    from app.models.platform.notification import Notification, NotificationType
    from app.services.import_engine import atlassian as atlassian_service

    monkeypatch.setattr(
        atlassian_service, "request_public_target", _jira_site(locked=("ACME",))
    )
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    job_id = (await _start_jira(client, a, initiative_id=a.initiative.id)).json()["id"]

    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_SOURCE_UNREACHABLE"
    failed = [
        n
        for n in (
            await session.exec(
                select(Notification).where(Notification.user_id == a.user.id)
            )
        ).all()
        if n.type == NotificationType.import_failed
    ]
    assert [n.data["import_job_id"] for n in failed] == [job_id]

    # Last, because it reads the row as the system rather than as anybody.
    assert await _job_secret(session, a.guild.id, job["id"]) is None


async def test_cancelling_a_fetch_stops_it_at_the_next_project(
    client, acting_user, session, monkeypatch, role_session
):
    """A fetch has written nothing but its own payload, so stopping one is
    safe — and it should actually stop, not read the rest of the site first
    and throw it away."""
    from app.services.import_engine import atlassian as atlassian_service

    state: dict = {}

    async def cancel_mid_read(url):
        # The first project's issues are being read: cancel the job, as the
        # wizard's Cancel button would, before the second is reached.
        if "search/jql" in url and not state.get("cancelled"):
            state["cancelled"] = True
            resp = await client.delete(
                state["actor"].g(f"/imports/jobs/{state['job_id']}"),
                headers=state["actor"].headers,
            )
            assert resp.status_code == 200, resp.text

    site = _jira_site(issues=[_jira_issue("ACME-1", "One")], on_request=cancel_mid_read)
    monkeypatch.setattr(atlassian_service, "request_public_target", site)
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    job_id = (
        await _start_jira(
            client,
            a,
            initiative_id=a.initiative.id,
            keys=("ACME", "BETA"),
        )
    ).json()["id"]
    state.update(actor=a, job_id=job_id)

    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.cancelled.value
    assert not any("/project/BETA" in url for url in site.requested)
    assert await _job_secret(session, a.guild.id, job["id"]) is None


# ---------------------------------------------------------------------------
# Imports from another product's export file
# ---------------------------------------------------------------------------

TODOIST_CSV = (
    "TYPE,CONTENT,DESCRIPTION,PRIORITY,INDENT,AUTHOR,RESPONSIBLE,DATE,"
    "DATE_LANG,TIMEZONE,DURATION,DURATION_UNIT,meta,DEADLINE,DEADLINE_LANG\n"
    "section,Doing,,,,,,,,,,,,,\n"
    "task,Ship it,With detail,1,1,,,,,,,,,2026-03-09,\n"
    "task,A step,,4,2,,,,,,,,,,\n"
    "note,Said something,,,,Dana (42),,,,,,,,,\n"
)


async def _preview_foreign(client, actor, source, content):
    return await client.post(
        actor.g(f"/imports/foreign/{source}/preview"),
        headers={**actor.headers, "Content-Type": "text/plain"},
        content=content.encode(),
    )


async def test_preview_says_what_a_todoist_export_holds(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    resp = await _preview_foreign(client, a, "todoist", TODOIST_CSV)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "todoist"
    # A Todoist CSV names one project and does not say which, so the step that
    # follows collects a name rather than offering a choice.
    assert body["picks_one"] is False
    assert body["options"][0]["task_count"] == 1


async def test_preview_of_an_unknown_product_is_refused(client, acting_user):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    resp = await _preview_foreign(client, a, "trello", "anything")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_UNKNOWN_SOURCE"


async def test_preview_of_a_file_that_is_not_that_export_is_refused(
    client, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    resp = await _preview_foreign(client, a, "vikunja", "this is not json }{{{")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "IMPORT_FILE_UNREADABLE"


async def test_a_todoist_export_becomes_a_project(client, acting_user, session):
    """The whole point: a foreign file lands as a project carrying what it
    said — statuses from its sections, a checklist, a comment, a deadline —
    through the same apply path an exported project takes."""
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    resp = await client.post(
        a.g("/imports/foreign/todoist"),
        headers=a.headers,
        json={
            "initiative_id": a.initiative.id,
            "selection": "From Todoist",
            "content": TODOIST_CSV,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["result"]["created"]["tasks"] == 1

    project = (
        await session.exec(select(Project).where(Project.name == "From Todoist"))
    ).first()
    assert project is not None
    task = (await session.exec(select(Task).where(Task.project_id == project.id))).one()
    assert task.title == "Ship it"
    assert [item["text"] for item in task.checklist] == ["A step"]
    assert task.due_date is not None


async def test_a_real_sized_export_arrives_whole(
    client, acting_user, session, monkeypatch
):
    """An export is not a short string. A file past the plain-text field
    ceiling — which every real export is — used to be refused with a 422
    before the handler ran, and markup in a task's text was stripped on the
    way in. The file is the file: every row lands, and so does what it said.
    """
    from sqlmodel import select

    from app.models.tenant.project import Project
    from app.models.tenant.task import Task
    from app.schemas.base import MAX_PLAIN_TEXT_LENGTH

    header, *rows = TODOIST_CSV.splitlines()
    padding = [
        f"task,Filler task number {i} with a longish title,,4,1,,,,,,,,,,"
        for i in range(400)
    ]
    content = "\n".join(
        [header, rows[0], "task,Compare a < b & <b>c</b>,,1,1,,,,,,,,,,", *padding]
    )
    assert len(content) > MAX_PLAIN_TEXT_LENGTH
    # Applied in the request, so what landed can be read straight back.
    monkeypatch.setattr(settings, "IMPORT_INLINE_MAX_ROWS", 10_000)

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    resp = await client.post(
        a.g("/imports/foreign/todoist"),
        headers=a.headers,
        json={
            "initiative_id": a.initiative.id,
            "selection": "Big Todoist",
            "content": content,
        },
    )
    assert resp.status_code == 201, resp.text

    project = (
        await session.exec(select(Project).where(Project.name == "Big Todoist"))
    ).one()
    titles = {
        t.title
        for t in (
            await session.exec(select(Task).where(Task.project_id == project.id))
        ).all()
    }
    assert len(titles) == 401
    # The characters survive; the markup is stripped by the task title's own
    # rule, the same one a title typed in the app goes through.
    assert "Compare a < b & c" in titles


async def test_importing_from_a_product_needs_the_create_permission(
    client, acting_user, session
):
    """Nothing about arriving from another product widens who may create a
    project here — it is the same gate the envelope route applies."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    other = await _second_initiative(session, a, create_projects_role="admin")
    b = await acting_user(
        guild_role=GuildRole.member,
        guild=a.guild,
        initiative=other,
        initiative_role="member",
    )
    resp = await client.post(
        b.g("/imports/foreign/todoist"),
        headers=b.headers,
        json={
            "initiative_id": other.id,
            "selection": "Nope",
            "content": TODOIST_CSV,
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "IMPORT_PERMISSION_REQUIRED"


async def test_importing_into_an_initiative_you_cannot_reach_is_a_404(
    client, acting_user
):
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    resp = await client.post(
        a.g("/imports/foreign/todoist"),
        headers=a.headers,
        json={
            "initiative_id": 9_999_999,
            "selection": "Nope",
            "content": TODOIST_CSV,
        },
    )
    assert resp.status_code == 404
