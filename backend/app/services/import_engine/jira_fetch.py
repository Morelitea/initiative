"""Reading a Jira project into a bundle the ordinary backup importer applies.

This is the orchestration half of the Jira fetch: the calls, the paging, and
the zip. The mapping it feeds is pure and lives in ``jira_mapping``; the
applying is ``backup.apply_backup``, which has existed since long before any
of this and knows nothing about Jira.

**It writes no content row.** The whole fetch produces exactly one artifact —
a zip in guild storage — and touches no table a person could see. That is what
makes it the one phase a crashed job can simply start over: there is nothing
half-applied to duplicate, only a partial payload to throw away (see the
worker's re-claim rule for ``fetching``).

**It never opens a routed session either.** Nothing here needs one: the
credential is read on the system engine and the bundle goes to storage under
an engine-internal key. The routed, RLS-enforced session appears in the apply
phase, unchanged, where rows are actually written.

The bundle is deliberately backup-shaped rather than a format of its own. A
Jira project becomes a manifest naming one initiative — the one the person
picked, carried as ``target_initiative_id`` so the applier files into it
rather than creating something — and one project envelope per project. Every
gate, every count and every report that a restore already has therefore
applies to an import from Jira without being written twice.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.core.messages import ImportEngineMessages
from app.services.import_engine import jira_mapping
from app.services.import_engine.atlassian import AtlassianCredential, get_json
from app.services.import_engine.contract import ImportEngineError

logger = logging.getLogger(__name__)

#: Issues per search page. Jira allows far more, but a page is held in memory
#: whole and every issue carries its description, so this trades a few more
#: round trips for a bounded footprint.
ISSUE_PAGE_SIZE = 100

#: A hard stop on paging, whatever the site says. ``nextPageToken`` is the
#: site's to hand back, and a loop that trusts it without a bound is a loop
#: somebody else controls.
MAX_ISSUE_PAGES = 500

#: The fields the fetch asks for. Named rather than ``*``: every extra field
#: is bytes over the wire and, for a custom field, a schema lookup nobody
#: asked for. The property mapping (§6.5) widens this when it lands.
ISSUE_FIELDS = (
    "summary",
    "description",
    "status",
    "priority",
    "labels",
    "assignee",
    "duedate",
    "created",
    "updated",
)

_MANIFEST_NAME = "manifest.json"


@dataclass
class FetchReport:
    """What the fetch found, for the plan the wizard shows.

    Counts only — never a title, never a body. A job row records what
    happened, and a foreign server's content is not something to park in one.
    """

    projects: int = 0
    tasks: int = 0
    #: ADF nodes the walker could not render, summed over every description.
    #: The honest half of the degradation contract: it says what will be lost
    #: before anybody commits to the import.
    dropped_nodes: int = 0
    #: Issues the search returned that were not usable as tasks.
    skipped_issues: int = 0
    #: Projects asked for that the token could not read. Named so the plan can
    #: say which, rather than quietly importing fewer than were ticked.
    unreadable_projects: list[str] = field(default_factory=list)


async def fetch_issue_type_statuses(
    credential: AtlassianCredential, project_key: str
) -> list[Any]:
    """Every status this project's issue types can be in.

    Reported per issue type, so the same status arrives under Story and under
    Bug; the mapping takes the union.
    """
    payload = await get_json(credential, f"/rest/api/3/project/{project_key}/statuses")
    return payload if isinstance(payload, list) else []


async def fetch_board_column_order(
    credential: AtlassianCredential, project_key: str
) -> Optional[list[str]]:
    """The board's columns as status ids, or ``None`` when there is no board.

    A project can have none, and a board this token cannot read is the same
    thing as far as the import is concerned: the workflow order stands
    instead. Neither is worth failing a fetch over, so both come back
    ``None`` rather than raising.
    """
    try:
        boards = await get_json(
            credential,
            f"/rest/agile/1.0/board?projectKeyOrId={project_key}&maxResults=1",
        )
    except ImportEngineError:
        return None
    values = boards.get("values") if isinstance(boards, dict) else None
    if not isinstance(values, list) or not values:
        return None
    board = values[0]
    board_id = board.get("id") if isinstance(board, dict) else None
    if board_id is None:
        return None
    try:
        configuration = await get_json(
            credential, f"/rest/agile/1.0/board/{board_id}/configuration"
        )
    except ImportEngineError:
        return None
    return jira_mapping.board_column_statuses(configuration)


async def fetch_issues(
    credential: AtlassianCredential,
    project_key: str,
    *,
    jql_extra: str | None = None,
    max_issues: int,
) -> list[Any]:
    """Every issue in the project, in Rank order, a page at a time.

    Rank order is what the team dragged them into, and it is the only ordering
    worth carrying — so it is asked for explicitly rather than left to
    whatever the index returns.

    ``jql_extra`` is the wizard's optional narrowing (a date range, an issue
    type), appended to the project clause rather than replacing it: the
    selection is the project, and a narrowing that could widen it would not be
    one.

    Paging stops at ``max_issues`` or :data:`MAX_ISSUE_PAGES`, whichever comes
    first. The cap is the caller's row budget; the page bound is the loop
    refusing to be driven forever by somebody else's cursor.
    """
    clause = f'project = "{project_key}"'
    if jql_extra and jql_extra.strip():
        clause = f"{clause} AND ({jql_extra.strip()})"
    jql = f"{clause} ORDER BY Rank ASC"

    issues: list[Any] = []
    token: str | None = None
    for _ in range(MAX_ISSUE_PAGES):
        body: dict[str, Any] = {
            "jql": jql,
            "maxResults": min(ISSUE_PAGE_SIZE, max_issues - len(issues)),
            "fields": list(ISSUE_FIELDS),
        }
        if token:
            body["nextPageToken"] = token
        payload = await get_json(
            credential, "/rest/api/3/search/jql", method="POST", json=body
        )
        if not isinstance(payload, dict):
            break
        page = payload.get("issues")
        if isinstance(page, list):
            issues.extend(page)
        # The cursor is the site's to hand back, so it is checked rather
        # than trusted: anything that is not a non-empty string ends the walk.
        cursor = payload.get("nextPageToken")
        if not isinstance(cursor, str) or not cursor or len(issues) >= max_issues:
            break
        token = cursor
    return issues[:max_issues]


async def fetch_project_envelope(
    credential: AtlassianCredential,
    project: dict,
    *,
    app_version: str,
    jql_extra: str | None = None,
    max_issues: int,
) -> tuple[jira_mapping.MappedProject, int]:
    """One Jira project as an envelope, and how many issues it cost.

    The issue count is returned separately from the mapping's own counts so
    the caller can spend a shared row budget across several projects rather
    than letting the first one take all of it — what it spent is how many
    issues came back, including the ones that turned out to be unusable.
    """
    key = str(project.get("key") or "").strip()
    statuses = await fetch_issue_type_statuses(credential, key)
    column_ids = await fetch_board_column_order(credential, key)

    column_names: Optional[list[str]] = None
    if column_ids:
        names_by_id = {
            str(status.get("id")): str(status.get("name") or "")
            for entry in statuses
            if isinstance(entry, dict)
            for status in entry.get("statuses") or []
            if isinstance(status, dict) and status.get("id") is not None
        }
        column_names = [
            names_by_id[status_id]
            for status_id in column_ids
            if status_id in names_by_id
        ]

    issues = await fetch_issues(
        credential, key, jql_extra=jql_extra, max_issues=max_issues
    )
    mapped = jira_mapping.build_project_envelope(
        project=project,
        issue_type_statuses=statuses,
        issues=issues,
        board_column_order=column_names,
        app_version=app_version,
        site_url=credential.site_url,
    )
    return mapped, len(issues)


def _entry_path(index: int, project_key: str) -> str:
    """Where a project's envelope sits inside the bundle.

    Mirrors what a backup writes, because the applier reads both and should
    not be able to tell which it is holding.
    """
    safe = "".join(c for c in project_key if c.isalnum() or c in "-_") or "project"
    return f"initiatives/1-imported/projects/{index}-{safe}.initiative-project.json"


def build_bundle(
    envelopes: list[tuple[str, dict[str, Any]]],
    *,
    guild_id: int,
    guild_name: str,
    target_initiative_id: int,
    app_version: str,
    site_url: str,
) -> bytes:
    """The zip the applier reads: a manifest and one envelope per project.

    The manifest names **one** initiative and gives it ``target_initiative_id``
    — the one the person picked in the wizard. That is the whole reason §8.2
    exists: a Jira project belongs in an initiative somebody already runs, not
    in a new one named after somebody else's site.
    """
    entries = []
    files: dict[str, bytes] = {}
    for index, (project_key, envelope) in enumerate(envelopes, start=1):
        path = _entry_path(index, project_key)
        files[path] = json.dumps(envelope).encode("utf-8")
        entries.append(
            {
                "path": path,
                "tool": "project",
                "type": "initiative-project",
                "schema_version": 1,
                "entity_id": index,
                "title": envelope["project"]["name"],
                "initiative_id": 1,
                "tags": [],
                "properties": [],
                "asset": None,
            }
        )

    manifest = {
        "type": "initiative-backup",
        "schema_version": 1,
        "app_version": app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_instance_url": site_url,
        "guild": {"id": guild_id, "name": guild_name},
        "include_uploads": False,
        "initiatives": [
            {
                "id": 1,
                "name": "Imported from Jira",
                "tools": {"project": "included"},
                # Apply into the initiative the person chose. Without this the
                # applier would create one, which is the wrong answer for a
                # fetch: they already said where it goes.
                "target_initiative_id": target_initiative_id,
            }
        ],
        "entries": entries,
        "assets": [],
        "skipped": [],
        "people": _people(envelopes),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(_MANIFEST_NAME, json.dumps(manifest))
        for path, blob in files.items():
            archive.writestr(path, blob)
    return buffer.getvalue()


def _people(envelopes: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Everyone the bundle names, for the wizard's people step.

    Assignees only, for now: comments are a later item, and an assignee is the
    one person a task currently names. Counted per mention so the step can say
    how much hangs on getting one row right, and ordered most-named first.
    """
    counts: dict[str, int] = {}
    for _key, envelope in envelopes:
        for task in envelope.get("tasks") or []:
            for handle in task.get("assignee_handles") or []:
                name = str(handle).strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
    return [
        {"handle": name, "name": name, "comment_count": 0}
        for name, _count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


async def fetch_projects_bundle(
    credential: AtlassianCredential,
    *,
    project_keys: list[str],
    guild_id: int,
    guild_name: str,
    target_initiative_id: int,
    app_version: str,
    jql_extra: str | None = None,
) -> tuple[bytes, FetchReport]:
    """Read the chosen projects and return the bundle plus what it found.

    A project the token cannot read is **counted, not fatal**: somebody who
    ticked four projects and can reach three should get the three and be told
    about the fourth, rather than a failed job and no explanation. Every
    project unreadable is a different matter — that is the selection being
    wrong, and it fails.
    """
    if not project_keys:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED)

    report = FetchReport()
    remaining = settings.IMPORT_MAX_ROWS
    envelopes: list[tuple[str, dict[str, Any]]] = []

    for key in project_keys:
        if remaining <= 0:
            # The budget is spent. Stopping here is better than a bundle the
            # applier will refuse whole.
            logger.info("jira fetch row budget spent, stopping at project=%s", key)
            break
        try:
            project = await get_json(credential, f"/rest/api/3/project/{key}")
            if not isinstance(project, dict):
                raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)
            mapped, used = await fetch_project_envelope(
                credential,
                project,
                app_version=app_version,
                jql_extra=jql_extra,
                max_issues=remaining,
            )
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                # Being throttled is about the site, not this project, and the
                # next one would be throttled too.
                raise
            logger.info("jira project unreadable key=%s code=%s", key, exc.code)
            report.unreadable_projects.append(key)
            continue

        envelopes.append((key, mapped.envelope))
        report.projects += 1
        report.tasks += len(mapped.envelope["tasks"])
        report.dropped_nodes += mapped.dropped_nodes
        report.skipped_issues += mapped.skipped_issues
        remaining -= used

    if not envelopes:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)

    bundle = build_bundle(
        envelopes,
        guild_id=guild_id,
        guild_name=guild_name,
        target_initiative_id=target_initiative_id,
        app_version=app_version,
        site_url=credential.site_url,
    )
    return bundle, report
