"""Tests for import parse endpoints — error response shape."""

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
    create_calendar_event,
    create_counter_group,
    create_document,
    create_initiative,
    create_queue,
    create_task,
)


@pytest.mark.integration
async def test_todoist_parse_bad_csv_opaque_error(client: AsyncClient, acting_user):
    """Todoist CSV with a non-numeric INDENT triggers ValueError, returns the opaque constant."""
    a = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        a.g("/imports/todoist/parse"),
        headers={**a.headers, "Content-Type": "text/plain"},
        content=b"TYPE,CONTENT,INDENT\ntask,My Task,not-a-number",
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail == "IMPORT_PARSE_FAILED"
    assert "Traceback" not in detail
    assert "Error" not in detail


@pytest.mark.integration
async def test_vikunja_parse_bad_json_opaque_error(client: AsyncClient, acting_user):
    """Malformed Vikunja JSON returns the constant, not a raw exception."""
    a = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        a.g("/imports/vikunja/parse"),
        headers={**a.headers, "Content-Type": "text/plain"},
        content=b"this is not json }{{{",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "IMPORT_PARSE_FAILED"


@pytest.mark.integration
async def test_ticktick_parse_bad_csv_opaque_error(client: AsyncClient, acting_user):
    """Malformed TickTick CSV returns the constant, not a raw exception."""
    a = await acting_user(guild_role=GuildRole.member)
    response = await client.post(
        a.g("/imports/ticktick/parse"),
        headers={**a.headers, "Content-Type": "text/plain"},
        content=b"\x00\x01\x02\x03binary garbage",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "IMPORT_PARSE_FAILED"


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
        session.add(
            QI(queue_id=queue.id, guild_id=a.guild.id, label=label, position=float(i))
        )
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
            guild_id=a.guild.id,
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
        title="Notes",
        content={"root": {"type": "root", "children": []}},
    )
    board = await create_document(
        session,
        a.initiative,
        a.user,
        title="Map",
        document_type=DocumentType.whiteboard,
        content={"elements": [{"type": "rectangle"}], "appState": {}, "files": {}},
    )
    link = await create_document(
        session,
        a.initiative,
        a.user,
        title="Spec",
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
    by_title = {d.title: d for d in imported}
    assert set(by_title) == {"Notes", "Map", "Spec"}
    assert by_title["Map"].content["elements"] == [{"type": "rectangle"}]
    assert "type" not in by_title["Map"].content  # unwrapped, not the file shape
    assert by_title["Spec"].content == {"url": "https://example.com/spec"}


async def test_envelope_import_roundtrips_calendar_events(client, acting_user, session):
    from sqlmodel import select

    from app.models.tenant.calendar_event import CalendarEvent, CalendarEventAttendee

    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    a.initiative.calendar_events_enabled = True
    session.add(a.initiative)
    await session.commit()
    await create_calendar_event(session, a.initiative, a.user, title="Session Zero")
    await create_calendar_event(session, a.initiative, a.user, title="One-shot")

    envelope = await _export_json(
        client, a, "/exports/calendar-event", {"initiative_id": a.initiative.id}
    )
    assert envelope["type"] == "initiative-calendar-events"

    target = await _second_initiative(session, a, calendar_events_enabled=True)
    resp = await _import_envelope(client, a, envelope, target.id)
    assert resp.status_code == 201, resp.text
    assert resp.json()["result"]["created"]["events"] == 2

    imported = list(
        await session.exec(
            select(CalendarEvent).where(CalendarEvent.initiative_id == target.id)
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


async def test_envelope_import_accepts_legacy_kind_spelling(
    client, acting_user, session
):
    """0.56.0-era envelopes spell the discriminator `kind` — they import."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    envelope = {
        "kind": "initiative-document",
        "schema_version": 1,
        "document_type": "smart_link",
        "title": "Old export",
        "content": {"url": "https://example.com"},
        "tags": [],
        "properties": [],
    }
    resp = await _import_envelope(client, a, envelope, a.initiative.id)
    assert resp.status_code == 201, resp.text


async def test_envelope_import_authorization_gates(client, acting_user, session):
    """Unknown type 400; bad version 400; tool switch off 400; a member
    without the create permission 403; an unreachable initiative 404."""
    a = await acting_user(guild_role=GuildRole.member, initiative=True, project=True)
    doc_envelope = {
        "type": "initiative-document",
        "schema_version": 1,
        "document_type": "smart_link",
        "title": "Doc",
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
    assert imported.created_by_id == a.user.id  # applied AS the creator

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
        guild_id=a.guild.id,
        created_by_id=a.user.id,
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
        "exported_by_email": "test@example.com",
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

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
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
    assert file_doc.title == "Handout"
    assert file_doc.file_url.endswith("/restore-me.pdf")
    assert file_doc.original_filename == "Handout.pdf"


async def test_backup_requires_real_admin(client, acting_user, session):
    member = await acting_user(
        guild_role=GuildRole.member, initiative=True, project=True
    )
    zip_bytes = _make_backup_zip(_minimal_manifest())
    denied = await _upload_backup(client, member, zip_bytes)
    assert denied.status_code == 403
    assert denied.json()["detail"] == "IMPORT_ADMIN_REQUIRED"


async def test_backup_rejects_invalid_and_bomb_zips(
    client, acting_user, session, monkeypatch
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)

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


async def test_backup_confirm_include_map_skips_tools(
    client, acting_user, session, monkeypatch, role_session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
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
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
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
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
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


async def test_backup_admin_revoked_before_apply_fails_closed(
    client, acting_user, session, monkeypatch, role_session
):
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    entry, envelope = _queue_entry()
    zip_bytes = _make_backup_zip(
        _minimal_manifest(entries=[entry]),
        {entry["path"]: json.dumps(envelope).encode()},
    )
    resp = await _upload_backup(client, a, zip_bytes)
    job_id = resp.json()["id"]
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )

    a.membership.role = GuildRole.member
    session.add(a.membership)
    await session.commit()

    await _run_import_worker(monkeypatch, role_session)
    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_ADMIN_REQUIRED"


async def test_backup_quota_exceeded_fails_job(
    client, acting_user, session, monkeypatch, role_session
):
    from sqlmodel import select

    from app.models.platform.guild import Guild

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild = (await session.exec(select(Guild).where(Guild.id == a.guild.id))).one()
    guild.max_storage_bytes = 1
    session.add(guild)
    await session.commit()

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
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
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

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    zip_bytes = _make_backup_zip(_minimal_manifest())

    staged = await _upload_backup(client, a, zip_bytes)
    job_id = staged.json()["id"]

    from app.testing import route_session_to_guild

    await route_session_to_guild(session, a.guild.id)
    row = await session.get(ImportJob, job_id)
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    session.add(row)
    await session.commit()

    await import_worker.process_import_gc()
    await session.refresh(row)
    assert row.status == ImportJobStatus.expired
    assert row.payload_ref is None

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


async def test_backup_legacy_kind_manifest_imports(
    client, acting_user, session, monkeypatch, role_session
):
    """0.56.0-era backups spell every discriminator `kind` — manifest and
    entries normalize and import."""
    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    entry, envelope = _queue_entry()
    legacy_entry = {k: v for k, v in entry.items() if k != "type"}
    legacy_entry["kind"] = "initiative-queue"
    legacy_envelope = {k: v for k, v in envelope.items() if k != "type"}
    legacy_envelope["kind"] = "initiative-queue"
    manifest = _minimal_manifest(entries=[legacy_entry])
    manifest.pop("type")
    manifest["kind"] = "initiative-backup"
    zip_bytes = _make_backup_zip(
        manifest, {entry["path"]: json.dumps(legacy_envelope).encode()}
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
    assert job["result"]["per_tool"]["queue"]["created"] == 1


async def test_backup_restores_fresh_assets_into_storage(
    client, acting_user, session, monkeypatch, role_session
):
    """A cross-guild restore: the storage key doesn't exist here, so the blob
    is written into guild storage, an uploads row is registered, and the file
    document serves from the restored key."""
    from pathlib import Path

    from sqlmodel import select

    from app.models.tenant.upload import Upload

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
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
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
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

    a = await acting_user(guild_role=GuildRole.admin, initiative=True, project=True)
    guild = (await session.exec(select(Guild).where(Guild.id == a.guild.id))).one()
    guild.max_storage_bytes = 10_000
    session.add(guild)
    await session.commit()

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
    await client.post(
        a.g(f"/imports/jobs/{job_id}/confirm"), headers=a.headers, json={}
    )
    await _run_import_worker(monkeypatch, role_session)

    job = (await client.get(a.g(f"/imports/jobs/{job_id}"), headers=a.headers)).json()
    assert job["status"] == ImportJobStatus.failed.value
    assert job["error"] == "IMPORT_QUOTA_EXCEEDED"
    # Nothing was written despite the understated claim.
    assert get_guild_storage(a.guild.id).open_readable("liar.bin") is None
