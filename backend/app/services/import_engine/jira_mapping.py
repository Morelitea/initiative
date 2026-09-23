"""Jira's JSON → this app's project envelope.

Pure, and deliberately so. Everything here takes decoded Jira payloads and
returns the envelope an ordinary import already knows how to apply — no
session, no network, no storage. The half that talks to Atlassian lives in
``atlassian.py``; the half that writes rows is the importer that has existed
since long before any of this. This module is the seam between them, which
means the mapping can be tested against real captured payloads without a
site to call.

The envelope it produces is the *same* one a project export writes, so a Jira
import is a restore of something this app could have exported. Nothing about
the apply path knows Jira exists.

**What a Jira status means here.** Jira's own categories are the only thing
that survives a workflow somebody invented: ``new`` is work not started,
``indeterminate`` is work in flight, ``done`` is finished. Names are per-site
and unmappable — except "Backlog", which is a name this app has a category
for and Jira does not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.core.relationships import RelationshipType
from app.models.tenant.task import TaskPriority, TaskStatusCategory
from app.services.import_engine.adf import adf_to_markdown
from app.services.import_engine.mapping import (
    DEFAULT_TAG_COLOR,
    POSITION_STEP,
    MappedProject,
    build_envelope,
    fallback_statuses,
)

#: Jira's five priorities to this app's four. Two of Jira's collapse into
#: ``low`` — the field has to land somewhere, and the property mapping keeps
#: what Jira actually said (a separate checklist item).
PRIORITY_BY_NAME: dict[str, TaskPriority] = {
    "highest": TaskPriority.urgent,
    "high": TaskPriority.high,
    "medium": TaskPriority.medium,
    "low": TaskPriority.low,
    "lowest": TaskPriority.low,
}

#: Jira's status categories to ours. ``new`` is ``todo`` unless the status is
#: actually called Backlog, which is the one status name worth reading.
CATEGORY_BY_JIRA_KEY: dict[str, TaskStatusCategory] = {
    "new": TaskStatusCategory.todo,
    "indeterminate": TaskStatusCategory.in_progress,
    "done": TaskStatusCategory.done,
}


def map_priority(field: Any) -> TaskPriority:
    """A Jira priority object to ours, medium when it says nothing.

    Matched on the name rather than the id: ids are per-site, names are
    Jira's own five and stable across every Cloud site.
    """
    name = ""
    if isinstance(field, dict):
        name = str(field.get("name") or "")
    return PRIORITY_BY_NAME.get(name.strip().lower(), TaskPriority.medium)


def map_status_category(status: Any) -> TaskStatusCategory:
    """Which of our four columns a Jira status belongs in."""
    if not isinstance(status, dict):
        return TaskStatusCategory.todo
    category = status.get("statusCategory")
    key = ""
    if isinstance(category, dict):
        key = str(category.get("key") or "").strip().lower()
    mapped = CATEGORY_BY_JIRA_KEY.get(key, TaskStatusCategory.todo)
    if mapped is TaskStatusCategory.todo:
        name = str(status.get("name") or "").strip().lower()
        if name == "backlog":
            return TaskStatusCategory.backlog
    return mapped


def _status_key(status: dict) -> str:
    return str(status.get("name") or "").strip()


def collect_statuses(
    issue_type_statuses: Iterable[Any],
    *,
    board_column_order: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Every status this project can be in, in the order a person sees them.

    Jira reports statuses per issue type, so the same status appears under
    Story and under Bug; the union is what the project's board actually has.

    ``board_column_order`` is the board's own columns, which is the order the
    team arranged rather than the order the workflow happens to list. When
    there is no board — a project can have none — the workflow order stands.
    A status the board does not show still has to exist, or the issues in it
    would have nowhere to land, so anything unplaced follows in workflow
    order.
    """
    seen: dict[str, dict[str, Any]] = {}
    for entry in issue_type_statuses or []:
        if not isinstance(entry, dict):
            continue
        for status in entry.get("statuses") or []:
            if not isinstance(status, dict):
                continue
            name = _status_key(status)
            if name and name not in seen:
                seen[name] = status

    ordered: list[dict[str, Any]] = []
    if board_column_order:
        for column in board_column_order:
            key = (column or "").strip()
            if key in seen:
                ordered.append(seen.pop(key))
    ordered.extend(seen.values())

    statuses: list[dict[str, Any]] = []
    default_index = _default_status_index(ordered)
    for index, status in enumerate(ordered):
        statuses.append(
            {
                "name": _status_key(status),
                "category": map_status_category(status).value,
                "position": index,
                "is_default": index == default_index,
            }
        )
    return statuses


def _default_status_index(ordered: list[dict[str, Any]]) -> int:
    """Where a new task lands: the first not-started status.

    Jira has no notion of a default, so this picks the one a person would —
    the leftmost column work has not begun in. A workflow with no such status
    at all (everything is in-flight or done) defaults to the first column,
    because something has to be default and the board's own first column is
    the least surprising answer.
    """
    for index, status in enumerate(ordered):
        if map_status_category(status) in (
            TaskStatusCategory.todo,
            TaskStatusCategory.backlog,
        ):
            return index
    return 0


def board_column_statuses(configuration: Any) -> list[str]:
    """The status names a board's columns hold, left to right.

    A column can hold several statuses (a "In Progress" column covering both
    *In Progress* and *In Review*), and they are listed in the column's own
    order, so the flattened sequence is the reading order of the board.
    """
    if not isinstance(configuration, dict):
        return []
    column_config = configuration.get("columnConfig")
    if not isinstance(column_config, dict):
        return []
    names: list[str] = []
    for column in column_config.get("columns") or []:
        if not isinstance(column, dict):
            continue
        for status in column.get("statuses") or []:
            if isinstance(status, dict) and status.get("id") is not None:
                names.append(str(status["id"]))
    return names


def board_column_status_names(
    configuration: Any, status_names_by_id: dict[str, str]
) -> list[str]:
    """The board's columns as status *names*, which is how statuses are
    matched everywhere else here — the board reports ids."""
    return [
        status_names_by_id[status_id]
        for status_id in board_column_statuses(configuration)
        if status_id in status_names_by_id
    ]


def map_issue(
    issue: Any,
    *,
    position: float,
    status_names: set[str],
    default_status_name: str,
) -> Optional[tuple[dict[str, Any], int]]:
    """One Jira issue as a task in the envelope.

    Returns the task and how many ADF nodes its description lost, or ``None``
    for something that is not an issue — the search API is somebody else's,
    and a malformed row should be skipped rather than fail the fetch.

    The status is matched by name against the ones the project actually
    carries; an issue in a status the enumeration did not report (it can
    happen when a workflow changes mid-fetch) lands in the default rather
    than inventing a column.
    """
    if not isinstance(issue, dict):
        return None
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return None
    summary = str(fields.get("summary") or "").strip()
    if not summary:
        # A task with no title has nothing to show in a list. Jira does not
        # allow it, so this is a malformed row rather than a real issue.
        return None

    status = fields.get("status")
    status_name = ""
    if isinstance(status, dict):
        status_name = str(status.get("name") or "").strip()
    if status_name not in status_names:
        status_name = default_status_name

    rendered = adf_to_markdown(fields.get("description"), lift_tasks=True)

    task: dict[str, Any] = {
        "title": summary,
        "description": rendered.markdown or None,
        "status_name": status_name,
        "priority": map_priority(fields.get("priority")).value,
        "position": position,
        "tags": [
            {"name": label, "color": DEFAULT_TAG_COLOR} for label in _labels(fields)
        ],
        "assignee_handles": [],
        "checklist": [
            {"text": line.text, "done": line.done} for line in rendered.checklist
        ],
        "property_values": [],
        "links": map_links(fields),
        "comments": [],
        "external_ref": _external_ref(issue),
    }

    assignee = _display_name(fields.get("assignee"))
    if assignee:
        # A display name, not a handle: who this is *here* is the wizard's
        # people step to answer, and it resolves against the roster at apply
        # time like every other imported name.
        task["assignee_handles"] = [assignee]

    due = _date(fields.get("duedate"))
    if due:
        task["due_date"] = due
    created = _timestamp(fields.get("created"))
    if created:
        task["created_at"] = created
    updated = _timestamp(fields.get("updated"))
    if updated:
        task["updated_at"] = updated
    return task, rendered.dropped_nodes


def _is_blocking(link_type: Any) -> bool:
    """Whether a Jira link type says one issue cannot proceed without the
    other.

    Known by name or by its outward verb, because a site can rename the type
    but a blocking link still reads "blocks". Everything else — relates,
    duplicates, clones, a site's own types — has no rule attached to it here.
    """
    if not isinstance(link_type, dict):
        return False
    name = str(link_type.get("name") or "").strip().lower()
    outward = str(link_type.get("outward") or "").strip().lower()
    return name == "blocks" or outward == "blocks"


def _issue_key(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("key") or "").strip()


def map_links(fields: dict) -> list[dict[str, Any]]:
    """The edges this issue asserts, as envelope links.

    Jira shows every issue link on **both** of its issues — as an
    ``outwardIssue`` on one and an ``inwardIssue`` on the other — so each is
    emitted from exactly one side, or it would be written twice:

    * **Blocks** becomes ``depends_on``, from the blocked issue to its
      blocker. That is the side that sees its blocker as ``inwardIssue``
      ("is blocked by"); the blocker's own copy is skipped.
    * **Every other type** becomes ``related_to``, emitted from the outward
      side. The finer words — duplicates, clones, causes — have no home: a
      relationship's subtype ships empty (§6.3).
    * **The parent** — a sub-task's parent, a story's epic — makes this issue
      ``part_of`` it. Only the child names its parent, so there is nothing to
      deduplicate.

    A far end outside the import is still emitted; the deferred pass counts
    it as unresolved when nothing answers to the ref.
    """
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(relationship_type: RelationshipType, key: str) -> None:
        if not key:
            return
        target = f"jira:{key}"
        marker = (relationship_type.value, target)
        if marker in seen:
            return
        seen.add(marker)
        links.append({"type": relationship_type.value, "target_external_ref": target})

    parent_key = _issue_key(fields.get("parent"))
    if parent_key:
        add(RelationshipType.part_of, parent_key)

    for link in fields.get("issuelinks") or []:
        if not isinstance(link, dict):
            continue
        inward = _issue_key(link.get("inwardIssue"))
        outward = _issue_key(link.get("outwardIssue"))
        if _is_blocking(link.get("type")):
            if inward:
                add(RelationshipType.depends_on, inward)
        elif outward:
            add(RelationshipType.related_to, outward)
    return links


def link_far_ends(issue: Any) -> list[tuple[str, str]]:
    """Every link this issue takes part in, as ``(link id, far issue key)``.

    For counting rather than for writing: both sides of a Jira link report
    it, so the id is what lets the caller count one link once — and the far
    key is what says whether its other end was brought over at all. The
    parent counts too, keyed by the child, since only the child names it.
    """
    if not isinstance(issue, dict):
        return []
    fields = issue.get("fields")
    if not isinstance(fields, dict):
        return []
    ends: list[tuple[str, str]] = []
    parent_key = _issue_key(fields.get("parent"))
    own_key = str(issue.get("key") or "").strip()
    if parent_key:
        ends.append((f"parent:{own_key}", parent_key))
    for link in fields.get("issuelinks") or []:
        if not isinstance(link, dict):
            continue
        far = _issue_key(link.get("inwardIssue")) or _issue_key(
            link.get("outwardIssue")
        )
        link_id = str(link.get("id") or "").strip()
        if far and link_id:
            ends.append((f"link:{link_id}", far))
    return ends


def _labels(fields: dict) -> list[str]:
    """Jira labels, which become guild tags. Deduplicated and trimmed; Jira
    allows no spaces in a label, so what arrives is already tag-shaped."""
    out: list[str] = []
    seen: set[str] = set()
    for label in fields.get("labels") or []:
        name = str(label or "").strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _display_name(user: Any) -> str:
    """What Jira calls a person. Never their address: ``emailAddress`` is
    null under the account's own privacy settings, and the endpoint that
    returns it regardless is reserved for approved apps."""
    if not isinstance(user, dict):
        return ""
    return str(user.get("displayName") or "").strip()


def _external_ref(issue: dict) -> str:
    """What this issue was called at the source — ``jira:ACME-123``.

    The name links point at, and the only thing that can reconcile a re-run
    by hand. It lives for the length of one job and is never written to a
    column.
    """
    key = str(issue.get("key") or "").strip()
    return f"jira:{key}" if key else ""


def _date(value: Any) -> Optional[str]:
    """A Jira ``duedate`` is a plain ``YYYY-MM-DD``; the envelope wants a
    datetime, so it becomes midnight UTC."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc).isoformat()


def _timestamp(value: Any) -> Optional[str]:
    """Jira stamps are ISO 8601 with a ``+0000``-style offset, which
    ``fromisoformat`` has accepted since 3.11."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return None


def build_project_envelope(
    *,
    project: Any,
    issue_type_statuses: Iterable[Any],
    issues: Iterable[Any],
    board_column_order: Optional[list[str]] = None,
    app_version: str,
    site_url: str | None = None,
) -> MappedProject:
    """A whole Jira project as the envelope an ordinary import applies.

    ``issues`` arrive in Rank order — the order the team dragged them into —
    and keep it: position is assigned by sequence here rather than read from
    a field, because Jira's rank is an opaque LexoRank string that means
    nothing outside Jira.
    """
    statuses = collect_statuses(
        issue_type_statuses, board_column_order=board_column_order
    )
    if not statuses:
        # An envelope with no statuses cannot be applied (the importer
        # refuses it), and a project with no workflow is not a thing Jira
        # has — but the fetch must not produce something unapplyable, so one
        # honest column stands in.
        statuses = fallback_statuses()
    status_names = {status["name"] for status in statuses}
    default_status_name = next(
        (status["name"] for status in statuses if status["is_default"]),
        statuses[0]["name"],
    )

    tasks: list[dict[str, Any]] = []
    dropped_nodes = 0
    skipped_issues = 0
    for index, issue in enumerate(issues):
        mapped = map_issue(
            issue,
            position=(index + 1) * POSITION_STEP,
            status_names=status_names,
            default_status_name=default_status_name,
        )
        if mapped is None:
            skipped_issues += 1
            continue
        task, lost = mapped
        tasks.append(task)
        dropped_nodes += lost

    project_fields = project if isinstance(project, dict) else {}
    description = adf_to_markdown(project_fields.get("description")).markdown
    if not description and isinstance(project_fields.get("description"), str):
        # A project description comes back as plain text on some sites and as
        # ADF on others.
        description = str(project_fields["description"]).strip()

    return MappedProject(
        envelope=build_envelope(
            name=str(project_fields.get("name") or "Imported project"),
            description=description or None,
            statuses=statuses,
            tasks=tasks,
            app_version=app_version,
            source_url=site_url,
        ),
        dropped_nodes=dropped_nodes,
        skipped_rows=skipped_issues,
    )
