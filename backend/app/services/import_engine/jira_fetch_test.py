"""Reading a Jira project into a bundle.

The load-bearing test is `test_the_bundle_is_one_the_backup_importer_reads`:
the whole design rests on a Jira import being a restore of something this app
could have exported, so if the applier cannot open what the fetch writes, the
idea does not hold. The rest is the paging and the failure behaviour — a
foreign server is allowed to be slow, partial, hostile or absent, and none of
those may take the job down with it.
"""

import io
import json
import zipfile

import httpx
import pytest

from app.core.messages import ImportEngineMessages
from app.services.import_engine import atlassian, jira_fetch
from app.services.import_engine.contract import ImportEngineError

pytestmark = pytest.mark.unit

CREDENTIAL = atlassian.AtlassianCredential(
    site_url="https://acme.atlassian.net",
    email="someone@example.com",
    api_token="shhh",
)


def _issue(key, summary, status="To Do", **fields):
    return {
        "key": key,
        "fields": {"summary": summary, "status": {"name": status}, **fields},
    }


STATUSES = [
    {
        "name": "Story",
        "statuses": [
            {"id": "1", "name": "To Do", "statusCategory": {"key": "new"}},
            {"id": "2", "name": "Done", "statusCategory": {"key": "done"}},
        ],
    }
]


def _site(monkeypatch, *, issues=None, pages=None, project_status=200, boards=True):
    """A Jira site answering the calls a fetch makes.

    ``pages`` is a list of (issues, next_token) for testing the walk; ``issues``
    is the single-page shorthand.
    """
    calls: list[dict] = []
    state = {"page": 0}

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        calls.append({"method": method, "url": url, "json": json})
        if "/rest/api/3/project/" in url and url.endswith("/statuses"):
            return httpx.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            if project_status != 200:
                return httpx.Response(project_status, json={})
            key = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"key": key, "name": f"{key} Board"})
        if "/rest/agile/1.0/board?" in url:
            if not boards:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"values": [{"id": 7}]})
        if "/configuration" in url:
            return httpx.Response(
                200,
                json={
                    "columnConfig": {
                        "columns": [
                            {"name": "Doing", "statuses": [{"id": "2"}]},
                            {"name": "Queue", "statuses": [{"id": "1"}]},
                        ]
                    }
                },
            )
        if "/rest/api/3/search/jql" in url:
            if pages is not None:
                idx = state["page"]
                state["page"] += 1
                if idx >= len(pages):
                    return httpx.Response(200, json={"issues": []})
                page_issues, next_token = pages[idx]
                body = {"issues": page_issues}
                if next_token:
                    body["nextPageToken"] = next_token
                return httpx.Response(200, json=body)
            return httpx.Response(200, json={"issues": issues or []})
        return httpx.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    return calls


async def _bundle(monkeypatch, **kw):
    return await jira_fetch.fetch_projects_bundle(
        CREDENTIAL,
        project_keys=kw.pop("project_keys", ["ACME"]),
        guild_id=1,
        guild_name="Acme",
        target_initiative_id=42,
        app_version="0.0.0-test",
        **kw,
    )


# --- the bundle ------------------------------------------------------------


async def test_the_bundle_is_one_the_backup_importer_reads(monkeypatch):
    """The whole design rests on this: a Jira import is a restore of something
    this app could have exported, so the applier's own reader has to open what
    the fetch writes without knowing where it came from."""
    from app.services.import_engine.backup import open_backup_zip, read_manifest

    _site(monkeypatch, issues=[_issue("ACME-1", "One"), _issue("ACME-2", "Two")])
    payload, report = await _bundle(monkeypatch)

    archive = open_backup_zip(payload)
    manifest = read_manifest(archive)

    assert manifest.type == "initiative-backup"
    assert len(manifest.entries) == 1
    entry = manifest.entries[0]
    assert entry.tool == "project"
    assert entry.type == "initiative-project"

    # And the entry it names is really in there, and really an envelope.
    from app.schemas.tenant.project_export import ProjectExportEnvelope

    envelope = ProjectExportEnvelope.model_validate(
        json.loads(archive.read(entry.path))
    )
    assert [t.title for t in envelope.tasks] == ["One", "Two"]
    assert report.projects == 1 and report.tasks == 2


async def test_the_bundle_files_into_the_initiative_somebody_chose(monkeypatch):
    """A Jira project belongs in an initiative somebody already runs, not in a
    new one named after somebody else's site. That is what §8.2 was for."""
    from app.services.import_engine.backup import open_backup_zip, read_manifest

    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)

    manifest = read_manifest(open_backup_zip(payload))
    assert len(manifest.initiatives) == 1
    assert manifest.initiatives[0].target_initiative_id == 42


async def test_the_bundle_names_the_people_it_quotes(monkeypatch):
    """The wizard's people step is rendered from this."""
    from app.services.import_engine.backup import open_backup_zip, read_manifest

    _site(
        monkeypatch,
        issues=[
            _issue("ACME-1", "One", assignee={"displayName": "Alice Chen"}),
            _issue("ACME-2", "Two", assignee={"displayName": "Alice Chen"}),
            _issue("ACME-3", "Three", assignee={"displayName": "Bob Ray"}),
        ],
    )
    payload, _ = await _bundle(monkeypatch)

    manifest = read_manifest(open_backup_zip(payload))
    # Most-named first, so the row that matters most is at the top.
    assert [p.handle for p in manifest.people] == ["Alice Chen", "Bob Ray"]


async def test_the_bundle_holds_no_token(monkeypatch):
    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)
    assert b"shhh" not in payload


# --- the conversation ------------------------------------------------------


async def test_issues_are_asked_for_in_rank_order(monkeypatch):
    """Rank is what the team dragged them into, and the only ordering worth
    carrying across."""
    calls = _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    await _bundle(monkeypatch)

    search = [c for c in calls if "search/jql" in c["url"]]
    assert search and search[0]["method"] == "POST"
    assert search[0]["json"]["jql"] == 'project = "ACME" ORDER BY Rank ASC'


async def test_a_narrowing_narrows_rather_than_replaces(monkeypatch):
    """The selection is the project. A narrowing that could widen it would not
    be one."""
    calls = _site(monkeypatch, issues=[])
    await _bundle(monkeypatch, jql_extra="created >= -30d")

    jql = [c for c in calls if "search/jql" in c["url"]][0]["json"]["jql"]
    assert jql == 'project = "ACME" AND (created >= -30d) ORDER BY Rank ASC'


async def test_the_board_decides_the_column_order(monkeypatch):
    """The stub board puts Done before To Do; the workflow lists them the
    other way round. The board wins."""
    from app.services.import_engine.backup import open_backup_zip, read_manifest

    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)
    archive = open_backup_zip(payload)
    entry = read_manifest(archive).entries[0]
    envelope = json.loads(archive.read(entry.path))

    assert [s["name"] for s in envelope["task_statuses"]] == ["Done", "To Do"]


async def test_a_project_with_no_board_still_fetches(monkeypatch):
    """A project can have no board, and a board this token cannot read is the
    same thing. Neither is worth failing over."""
    _site(monkeypatch, issues=[_issue("ACME-1", "One")], boards=False)
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 1


async def test_paging_follows_the_cursor_to_the_end(monkeypatch):
    _site(
        monkeypatch,
        pages=[
            ([_issue("ACME-1", "One")], "cursor-1"),
            ([_issue("ACME-2", "Two")], None),
        ],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 2


async def test_a_cursor_that_is_not_a_string_ends_the_walk(monkeypatch):
    """The cursor is the site's to hand back, so it is checked rather than
    trusted — otherwise a junk value drives the loop."""
    _site(
        monkeypatch,
        pages=[([_issue("ACME-1", "One")], 12345), ([_issue("ACME-2", "Two")], None)],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 1


async def test_the_row_budget_is_shared_across_projects(monkeypatch):
    """One enormous project must not eat the whole import's ceiling and leave
    the others empty without saying so."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "IMPORT_MAX_ROWS", 3)
    _site(monkeypatch, issues=[_issue(f"ACME-{i}", f"Task {i}") for i in range(10)])
    _payload, report = await _bundle(monkeypatch, project_keys=["ACME", "OTHER"])

    assert report.tasks == 3
    assert report.projects == 1


# --- when the site misbehaves ----------------------------------------------


async def test_an_unreadable_project_is_counted_not_fatal(monkeypatch):
    """Somebody who ticked two projects and can reach one should get the one
    and be told about the other."""

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/rest/api/3/project/LOCKED" in url and not url.endswith("/statuses"):
            return httpx.Response(403, json={})
        if "/rest/api/3/project/" in url and url.endswith("/statuses"):
            return httpx.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"key": key, "name": key})
        if "/rest/agile/1.0/board?" in url:
            return httpx.Response(404, json={})
        if "search/jql" in url:
            return httpx.Response(200, json={"issues": [_issue("ACME-1", "One")]})
        return httpx.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    _payload, report = await _bundle(monkeypatch, project_keys=["ACME", "LOCKED"])

    assert report.projects == 1
    assert report.unreadable_projects == ["LOCKED"]


async def test_progress_hears_every_project_read_or_not(monkeypatch):
    """The job row climbs one project at a time, and a locked project is
    still a step taken — otherwise a fetch stuck behind it looks stalled."""

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        if "/rest/api/3/project/LOCKED" in url:
            return httpx.Response(403, json={})
        if url.endswith("/statuses"):
            return httpx.Response(200, json=STATUSES)
        if "/rest/api/3/project/" in url:
            key = url.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"key": key, "name": key})
        if "search/jql" in url:
            return httpx.Response(200, json={"issues": [_issue("ACME-1", "One")]})
        return httpx.Response(404, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    heard: list[tuple[int, int, list[str]]] = []

    async def progress(report):
        heard.append((report.projects, report.tasks, list(report.unreadable_projects)))

    await _bundle(monkeypatch, project_keys=["ACME", "LOCKED"], progress=progress)

    assert heard == [(1, 1, []), (1, 1, ["LOCKED"])]


async def test_a_progress_listener_can_stop_the_walk(monkeypatch):
    """What a cancel looks like from in here: the listener raises, and no
    further project is asked for."""
    calls = _site(monkeypatch, issues=[_issue("ACME-1", "One")])

    class Stop(Exception):
        pass

    async def progress(report):
        raise Stop

    with pytest.raises(Stop):
        await _bundle(monkeypatch, project_keys=["ACME", "OTHER"], progress=progress)
    assert not any("/project/OTHER" in call["url"] for call in calls)


async def test_every_project_unreadable_is_a_failure(monkeypatch):
    """That is the selection being wrong, not one project being locked."""
    _site(monkeypatch, project_status=403)
    with pytest.raises(ImportEngineError) as exc:
        await _bundle(monkeypatch, project_keys=["ACME", "OTHER"])
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE


async def test_being_throttled_stops_the_whole_fetch(monkeypatch):
    """Rate limiting is about the site, not one project — the next project
    would be throttled too, and hammering it is how a short block becomes a
    long one."""

    async def fake_request(method, url, *, headers=None, json=None, timeout=None, **kw):
        return httpx.Response(429, json={})

    monkeypatch.setattr(atlassian, "request_public_target", fake_request)
    with pytest.raises(ImportEngineError) as exc:
        await _bundle(monkeypatch, project_keys=["ACME", "OTHER"])
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED


async def test_nothing_selected_is_its_own_answer(monkeypatch):
    with pytest.raises(ImportEngineError) as exc:
        await _bundle(monkeypatch, project_keys=[])
    assert exc.value.code == ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED


async def test_what_the_description_lost_is_reported(monkeypatch):
    """The honest half of the degradation contract: the plan says what will be
    lost before anybody commits to the import."""
    _site(
        monkeypatch,
        issues=[
            _issue(
                "ACME-1",
                "One",
                description={
                    "type": "doc",
                    "content": [{"type": "somethingNew", "attrs": {"x": 1}}],
                },
            )
        ],
    )
    _payload, report = await _bundle(monkeypatch)
    assert report.dropped_nodes == 1


async def test_a_malformed_issue_is_counted_as_skipped(monkeypatch):
    _site(monkeypatch, issues=[_issue("ACME-1", "Good"), {"key": "ACME-2"}])
    _payload, report = await _bundle(monkeypatch)
    assert report.tasks == 1
    assert report.skipped_issues == 1


async def test_the_zip_stays_inside_the_members_bound(monkeypatch):
    """open_backup_zip refuses an archive with too many members, so the fetch
    must not build one it would then refuse."""
    _site(monkeypatch, issues=[_issue("ACME-1", "One")])
    payload, _ = await _bundle(monkeypatch)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert len(archive.infolist()) == 2  # manifest + one envelope
