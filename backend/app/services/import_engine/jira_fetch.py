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
from typing import Any, Awaitable, Callable, Optional

from app.core.config import settings
from app.core.messages import ImportEngineMessages
from app.services.import_engine import jira_attachments, jira_mapping, jira_sprints
from app.services.import_engine.atlassian import (
    AtlassianCredential,
    get_bytes,
    get_json,
)
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

#: The fields the fetch asks for: every one a person can see on an issue.
#: Narrower than ``*all`` (no internal bookkeeping), but it has to be all the
#: navigable ones — which of a site's own fields anybody filled in is only
#: known by reading them, and that is the rule a property is created by
#: (§6.5).
ISSUE_FIELDS = ("*navigable",)

#: Asked for beside those when comments are wanted. The search returns the
#: first page of each issue's comments with its ``total``, so only an issue
#: with more than that costs a call of its own.
COMMENT_FIELD = "comment"

#: Asked for beside those when images are wanted: each issue's attachments,
#: with the size and type the download is decided by.
ATTACHMENT_FIELD = "attachment"

#: Held back from the bundle's byte and member bounds for the manifest and
#: the envelopes, so images cannot crowd them out.
_BUNDLE_RESERVE_BYTES = 64 * 1024 * 1024
_BUNDLE_RESERVE_FILES = 500

#: Comments per page when an issue's have to be read on their own.
COMMENT_PAGE_SIZE = 100

#: A hard stop on one issue's comment pages, for the same reason the issue
#: walk has one: the site decides how many pages there are.
MAX_COMMENT_PAGES = 50

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
    #: Links and parents whose both ends were fetched — the edges the apply
    #: will draw.
    links: int = 0
    #: Links and parents whose other end is outside what was fetched: another
    #: project, an issue a narrowing left out, one the token cannot see. Said
    #: before anybody commits, because those connections will not come over.
    links_outside_selection: int = 0
    #: Every property the bundle declares, by name: its type, and how many
    #: tasks carry a value. The review step lists these for somebody to
    #: untick what they do not want (§5.4).
    properties: dict[str, tuple[str, int]] = field(default_factory=dict)
    #: Fields some issue filled that have no home here, by name.
    dropped_fields: list[str] = field(default_factory=list)
    #: Distinct sprints the fetched issues were in.
    sprints: int = 0
    #: Calendars they will land on — one per board.
    sprint_calendars: int = 0
    #: Sprints planned but never started: no dates, so no event.
    sprints_undated: int = 0
    #: Images that will come over as uploads, and their bytes.
    images: int = 0
    image_bytes: int = 0
    #: Images over the per-image cap or past the bundle's budget.
    images_oversize: int = 0
    #: Images the site would not hand over.
    images_unreadable: int = 0
    #: Attachments that are not images — file documents are a later item.
    other_attachments: int = 0
    #: Comments that will come over.
    comments: int = 0
    #: Comments visible only to a role or group at the source, left behind
    #: rather than shown to the whole initiative.
    comments_restricted: int = 0
    #: Why sprints will not come over at all, as a code — the target
    #: initiative has no calendars, or the importer cannot create one there.
    #: ``None`` when they will.
    sprints_skipped: Optional[str] = None


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

    Being throttled is the exception. That is about the site, not the board,
    and quietly importing without the column order would hide it — so it is
    raised like everywhere else.
    """
    try:
        boards = await get_json(
            credential,
            f"/rest/agile/1.0/board?projectKeyOrId={project_key}&maxResults=1",
        )
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
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
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
        return None
    return jira_mapping.board_column_statuses(configuration)


async def fetch_issues(
    credential: AtlassianCredential,
    project_key: str,
    *,
    jql_extra: str | None = None,
    max_issues: int,
    include_comments: bool = False,
    include_attachments: bool = False,
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
            "fields": [
                *ISSUE_FIELDS,
                *([COMMENT_FIELD] if include_comments else []),
                *([ATTACHMENT_FIELD] if include_attachments else []),
            ],
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


async def fetch_field_catalog(credential: AtlassianCredential) -> list[Any]:
    """Every field the site defines, with the schema that says its type.

    Read once per fetch, since it is the site's and not a project's. A site
    that will not answer is not worth failing the import over: the built-in
    fields still map by their own ids, and only the site's own fields go
    without a type — so they are left out rather than guessed at. Being
    throttled is the exception, as everywhere else.
    """
    try:
        payload = await get_json(credential, "/rest/api/3/field")
    except ImportEngineError as exc:
        if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
            raise
        logger.info("jira field catalog unreadable code=%s", exc.code)
        return []
    return payload if isinstance(payload, list) else []


async def complete_comments(credential: AtlassianCredential, issue: Any) -> None:
    """Fill in the rest of an issue's comments when the search held back some.

    The search carries each issue's first page with a ``total``; an issue
    with more is read on its own, oldest first, and the comment field is
    replaced with the whole list. One that will not answer keeps the page it
    had — a partial thread beats failing the project over it.
    """
    fields = issue.get("fields") if isinstance(issue, dict) else None
    field = fields.get(COMMENT_FIELD) if isinstance(fields, dict) else None
    if not isinstance(field, dict):
        return
    have = field.get("comments")
    total = field.get("total")
    if not isinstance(have, list) or not isinstance(total, int) or total <= len(have):
        return
    key = str(issue.get("key") or "").strip()
    if not key:
        return
    comments: list[Any] = []
    for page in range(MAX_COMMENT_PAGES):
        try:
            payload = await get_json(
                credential,
                f"/rest/api/3/issue/{key}/comment"
                f"?startAt={page * COMMENT_PAGE_SIZE}"
                f"&maxResults={COMMENT_PAGE_SIZE}&orderBy=created",
            )
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            logger.info("jira comments unreadable key=%s code=%s", key, exc.code)
            return
        batch = payload.get("comments") if isinstance(payload, dict) else None
        if not isinstance(batch, list) or not batch:
            break
        comments.extend(batch)
        if len(comments) >= total:
            break
    if comments:
        field["comments"] = comments


@dataclass
class FetchedProject:
    """One project read from the site, and what the bundle-wide passes need
    from it once every project is in."""

    mapped: jira_mapping.MappedProject
    #: Issues the search returned, usable or not — what the row budget spent.
    issues_used: int
    #: ``(link id, far key)`` pairs, counted once all projects are read.
    link_ends: list[tuple[str, str]]
    #: Each issue's sprints, by issue key.
    sprints: dict[str, list[jira_sprints.Sprint]]
    #: Comments visible only to a role or group, left behind.
    restricted_comments: int
    #: The images downloaded for this project's issues.
    images: jira_attachments.ImageReport


@dataclass
class ImageBudget:
    """What the bundle can still hold, shared across every project.

    Kept under the bounds the restore checks when it opens the zip — its
    uncompressed size and its member count — with room left for the
    manifest and the envelopes, so a bundle the fetch wrote is never one the
    apply refuses whole.
    """

    bytes_left: int
    files_left: int


async def fetch_project_envelope(
    credential: AtlassianCredential,
    project: dict,
    *,
    app_version: str,
    jql_extra: str | None = None,
    max_issues: int,
    field_catalog: Any = None,
    include_comments: bool = False,
    image_budget: Optional[ImageBudget] = None,
    guild_id: Optional[int] = None,
) -> FetchedProject:
    """One Jira project as an envelope, how many issues it cost, and what its
    issues are linked to.

    The issue count is returned separately from the mapping's own counts so
    the caller can spend a shared row budget across several projects rather
    than letting the first one take all of it — what it spent is how many
    issues came back, including the ones that turned out to be unusable.

    The link ends are ``(link id, far key)`` pairs. They come back raw
    because whether a far end was fetched is only known once every project
    has been read — a link between two ticked projects is not outside the
    selection.
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
        credential,
        key,
        jql_extra=jql_extra,
        max_issues=max_issues,
        include_comments=include_comments,
        include_attachments=image_budget is not None,
    )
    if include_comments:
        for issue in issues:
            await complete_comments(credential, issue)

    images = jira_attachments.ImageReport()
    if image_budget is not None and guild_id is not None:

        async def download(attachment_id: str, max_bytes: int) -> bytes:
            # redirect=false: the content itself, not a hop to a media host
            # this client would refuse to follow.
            return await get_bytes(
                credential,
                f"/rest/api/3/attachment/content/{attachment_id}?redirect=false",
                max_bytes=max_bytes,
            )

        images = await jira_attachments.download_images(
            issues,
            download=download,
            budget_bytes=image_budget.bytes_left,
            max_files=image_budget.files_left,
        )
        image_budget.bytes_left -= images.image_bytes
        image_budget.files_left -= images.images

    mapped = jira_mapping.build_project_envelope(
        project=project,
        issue_type_statuses=statuses,
        issues=issues,
        board_column_order=column_names,
        app_version=app_version,
        site_url=credential.site_url,
        field_catalog=field_catalog,
        include_comments=include_comments,
        images_by_issue=images.by_issue,
        guild_id=guild_id,
    )
    link_ends = [end for issue in issues for end in jira_mapping.link_far_ends(issue)]
    # Which sprints each issue was in, keyed by issue key. Built into events
    # only once every project is read: one sprint can hold issues from several.
    sprint_fields = jira_sprints.sprint_field_ids(field_catalog)
    sprints = {
        str(issue.get("key") or ""): found
        for issue in issues
        if isinstance(issue, dict)
        and (found := jira_sprints.issue_sprints(issue, sprint_fields))
    }
    restricted = (
        sum(
            jira_mapping.restricted_comment_count(issue.get("fields"))
            for issue in issues
            if isinstance(issue, dict)
        )
        if include_comments
        else 0
    )
    return FetchedProject(
        mapped=mapped,
        issues_used=len(issues),
        link_ends=link_ends,
        sprints=sprints,
        restricted_comments=restricted,
        images=images,
    )


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
    calendars: list[dict[str, Any]] | None = None,
    images: list[jira_attachments.StoredImage] | None = None,
) -> bytes:
    """The zip the applier reads: a manifest, one envelope per project, and
    one calendar per board whose sprints came along.

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
    for index, calendar in enumerate(calendars or [], start=1):
        safe = "".join(c for c in calendar["name"] if c.isalnum() or c in "-_")
        path = (
            f"initiatives/1-imported/calendars/{index}-{safe or 'sprints'}"
            ".initiative-calendar.json"
        )
        files[path] = json.dumps(calendar).encode("utf-8")
        entries.append(
            {
                "path": path,
                "tool": "calendar",
                "type": "initiative-calendar",
                "schema_version": 1,
                "entity_id": index,
                "title": calendar["name"],
                "initiative_id": 1,
                "tags": [],
                "properties": [],
                "asset": None,
            }
        )

    assets = []
    for image in images or []:
        path = f"assets/{image.storage_key}"
        files[path] = image.data
        assets.append(
            {
                "path": path,
                "storage_key": image.storage_key,
                "original_filename": image.filename,
                "content_type": image.content_type,
                "size_bytes": len(image.data),
            }
        )

    tools = {"project": "included"}
    if calendars:
        tools["calendar"] = "included"
    manifest = {
        "type": "initiative-backup",
        "schema_version": 1,
        "app_version": app_version,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_instance_url": site_url,
        "guild": {"id": guild_id, "name": guild_name},
        "include_uploads": bool(assets),
        "initiatives": [
            {
                "id": 1,
                "name": "Imported from Jira",
                "tools": tools,
                # Apply into the initiative the person chose. Without this the
                # applier would create one, which is the wrong answer for a
                # fetch: they already said where it goes.
                "target_initiative_id": target_initiative_id,
            }
        ],
        "entries": entries,
        "assets": assets,
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

    Assignees, and whoever a person field names — a Reporter, a site's own
    user fields — since both are placed through the step's answer. Comments
    are a later item. Counted per mention so the step can say how much hangs
    on getting one row right, and ordered most-named first.
    """
    from app.services.import_engine.people import user_reference_handles

    counts: dict[str, int] = {}
    comments: dict[str, int] = {}
    for _key, envelope in envelopes:
        for task in envelope.get("tasks") or []:
            named = [
                *(task.get("assignee_handles") or []),
                *user_reference_handles(task.get("property_values") or []),
            ]
            for handle in named:
                name = str(handle).strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
            for comment in task.get("comments") or []:
                name = str(comment.get("author_handle") or "").strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
                    comments[name] = comments.get(name, 0) + 1
    return [
        {"handle": name, "name": name, "comment_count": comments.get(name, 0)}
        for name, _count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def _count_links(
    report: FetchReport,
    envelopes: list[tuple[str, dict[str, Any]]],
    link_ends: list[tuple[str, str]],
) -> None:
    """Split the links into those that will be drawn and those that cannot.

    A link is counted once however many of its issues reported it (both sides
    of a Jira link do), and it is drawn only if its far end is among the tasks
    this bundle carries — in any of the projects ticked, not only its own.
    """
    fetched = {
        task["external_ref"].removeprefix("jira:")
        for _key, envelope in envelopes
        for task in envelope["tasks"]
        if task.get("external_ref")
    }
    far_by_link: dict[str, set[str]] = {}
    for link_id, far_key in link_ends:
        far_by_link.setdefault(link_id, set()).add(far_key)
    for far_keys in far_by_link.values():
        if far_keys <= fetched:
            report.links += 1
        else:
            report.links_outside_selection += 1


async def fetch_projects_bundle(
    credential: AtlassianCredential,
    *,
    project_keys: list[str],
    guild_id: int,
    guild_name: str,
    target_initiative_id: int,
    app_version: str,
    jql_extra: str | None = None,
    progress: Optional[Callable[[FetchReport], Awaitable[None]]] = None,
    sprints_blocked_by: str | None = None,
    include_comments: bool = True,
    include_attachments: bool = True,
) -> tuple[bytes, FetchReport]:
    """Read the chosen projects and return the bundle plus what it found.

    ``progress`` hears the running report after every project, read or not.
    It is how the job row shows the fetch moving, and how a cancelled job
    stops one: the callback raising ends the walk at the next project rather
    than after the last.

    A project the token cannot read is **counted, not fatal**: somebody who
    ticked four projects and can reach three should get the three and be told
    about the fourth, rather than a failed job and no explanation. Every
    project unreadable is a different matter — that is the selection being
    wrong, and it fails.

    ``sprints_blocked_by`` is the code for why sprints cannot land in the
    target initiative — its calendars are off, or the importer may not create
    one there. They are still counted, so the plan can say how many are being
    left behind, and no task is linked to a sprint that will not exist.
    """
    if not project_keys:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_NOTHING_SELECTED)

    report = FetchReport()
    link_ends: list[tuple[str, str]] = []
    remaining = settings.IMPORT_MAX_ROWS
    envelopes: list[tuple[str, dict[str, Any]]] = []
    field_catalog = await fetch_field_catalog(credential)
    dropped_fields: set[str] = set()
    all_sprints: dict[int, jira_sprints.Sprint] = {}
    all_images: list[jira_attachments.StoredImage] = []
    image_budget = (
        ImageBudget(
            bytes_left=max(
                0, settings.IMPORT_MAX_BACKUP_UNCOMPRESSED_BYTES - _BUNDLE_RESERVE_BYTES
            ),
            files_left=max(0, settings.IMPORT_MAX_ZIP_MEMBERS - _BUNDLE_RESERVE_FILES),
        )
        if include_attachments
        else None
    )
    sprint_membership: dict[str, list[int]] = {}

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
            fetched = await fetch_project_envelope(
                credential,
                project,
                app_version=app_version,
                jql_extra=jql_extra,
                max_issues=remaining,
                field_catalog=field_catalog,
                include_comments=include_comments,
                image_budget=image_budget,
                guild_id=guild_id,
            )
            mapped = fetched.mapped
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                # Being throttled is about the site, not this project, and the
                # next one would be throttled too.
                raise
            logger.info("jira project unreadable key=%s code=%s", key, exc.code)
            report.unreadable_projects.append(key)
        else:
            envelopes.append((key, mapped.envelope))
            link_ends.extend(fetched.link_ends)
            images = fetched.images
            report.images += images.images
            report.image_bytes += images.image_bytes
            report.images_oversize += images.oversize
            report.images_unreadable += images.unreadable
            report.other_attachments += images.other_files
            for stored in images.by_issue.values():
                all_images.extend(stored)
            for issue_key, found in fetched.sprints.items():
                for sprint in found:
                    all_sprints.setdefault(sprint.id, sprint)
                sprint_membership[issue_key] = [sprint.id for sprint in found]
            report.sprints = len(all_sprints)
            report.projects += 1
            report.tasks += len(mapped.envelope["tasks"])
            report.dropped_nodes += mapped.dropped_nodes
            report.skipped_issues += mapped.skipped_rows
            # Summed across projects: the same field on two boards is one
            # property in the initiative they land in.
            for name, (ptype, count) in mapped.properties.items():
                _type, total = report.properties.get(name, (ptype, 0))
                report.properties[name] = (ptype, total + count)
            dropped_fields.update(mapped.dropped_fields)
            report.dropped_fields = sorted(dropped_fields, key=str.lower)
            # A comment is a row like a task is, so it spends the same budget:
            # ten tasks carrying four thousand comments is a large import.
            project_comments = sum(
                len(task["comments"]) for task in mapped.envelope["tasks"]
            )
            report.comments += project_comments
            report.comments_restricted += fetched.restricted_comments
            remaining -= fetched.issues_used + project_comments
        if progress is not None:
            await progress(report)

    if not envelopes:
        raise ImportEngineError(ImportEngineMessages.IMPORT_SOURCE_UNREACHABLE)

    _count_links(report, envelopes, link_ends)
    calendars: list[dict[str, Any]] = []
    if all_sprints and sprints_blocked_by is not None:
        report.sprints_skipped = sprints_blocked_by
    elif all_sprints:
        board_names = await fetch_board_names(
            credential,
            {s.board_id for s in all_sprints.values() if s.board_id is not None},
        )
        calendars, placed = jira_sprints.build_sprint_calendars(
            all_sprints, board_names
        )
        report.sprint_calendars = len(calendars)
        report.sprints_undated = len(all_sprints) - len(placed)
        _link_tasks_to_sprints(envelopes, sprint_membership, placed)

    bundle = build_bundle(
        envelopes,
        guild_id=guild_id,
        guild_name=guild_name,
        target_initiative_id=target_initiative_id,
        app_version=app_version,
        site_url=credential.site_url,
        calendars=calendars,
        images=all_images,
    )
    return bundle, report


async def fetch_board_names(
    credential: AtlassianCredential, board_ids: set[int]
) -> dict[int, str]:
    """What each board is called, for the calendar its sprints land on.

    A board the token cannot read keeps no name, and its calendar gets the
    fallback one: not worth failing an import over. Being throttled is.
    """
    names: dict[int, str] = {}
    for board_id in sorted(board_ids):
        try:
            board = await get_json(credential, f"/rest/agile/1.0/board/{board_id}")
        except ImportEngineError as exc:
            if exc.code == ImportEngineMessages.IMPORT_SOURCE_RATE_LIMITED:
                raise
            continue
        name = board.get("name") if isinstance(board, dict) else None
        if isinstance(name, str) and name.strip():
            names[board_id] = name.strip()
    return names


def _link_tasks_to_sprints(
    envelopes: list[tuple[str, dict[str, Any]]],
    membership: dict[str, list[int]],
    placed: set[int],
) -> None:
    """Relate each task to the sprints it was in — only the ones that became
    events, so no link points at a sprint that will not exist."""
    for _key, envelope in envelopes:
        for task in envelope["tasks"]:
            issue_key = str(task.get("external_ref") or "").removeprefix("jira:")
            for sprint_id in membership.get(issue_key, []):
                if sprint_id in placed:
                    task["links"].append(
                        {
                            "type": "related_to",
                            "target_external_ref": jira_sprints.sprint_ref(sprint_id),
                        }
                    )
