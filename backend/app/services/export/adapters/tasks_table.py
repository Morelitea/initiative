"""Tasks-table source adapter: "export tasks" is "list tasks, but render".

Queries through ``query_tasks_for_export`` — the same visibility/filter/sort
pipeline as the ``list_tasks`` endpoint, executed under the caller's RLS
session (that query IS the authorization) — then shapes rows into the
backend-agnostic data payload the ``task-table`` template reads.

``params`` is the user's own filter selector, exactly what the list endpoint
accepts: ``{"conditions", "sorting", "tz", "include_archived"}``. It is what
an ExportJob row persists, and what the worker replays here at render time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.platform.user import User
from app.models.tenant.task import Task, TaskStatusCategory
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.i18n import et, export_locale

# Column spec: (row key, ``exports`` label key, Typst width hint). The PDF
# template reads the label + width from the payload; the tabular renderers
# project rows through the keys in order. Labels resolve to the creator's
# locale at build time.
_COLUMNS = (
    ("title", "columns.task", "2fr"),
    ("project", "columns.project", "1fr"),
    ("status", "columns.status", "auto"),
    ("priority", "columns.priority", "auto"),
    ("due", "columns.due", "auto"),
    ("assignees", "columns.assignees", "1fr"),
)


def _columns(locale: str) -> list[dict]:
    return [
        {"key": key, "label": et(label_key, locale), "width": width}
        for key, label_key, width in _COLUMNS
    ]


class TasksTableAdapter:
    source = "tasks"
    template_id = "task-table"
    # The one-task-per-page detailed report (layout=detailed, PDF only).
    detail_template_id = "task-detail"
    formats = frozenset({"pdf", "csv", "xlsx", "md"})

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        from app.api.v1.tenant_endpoints.tasks import count_tasks_for_export

        return await count_tasks_for_export(
            session, user, guild_id, **_selector(params)
        )

    async def build(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> RenderRequest:
        # The detailed report is a distinct, richer shape (one task per page
        # with description/subtasks/comments) — PDF only; for other formats
        # ``layout=detailed`` falls through to the table.
        if format == "pdf" and params.get("layout") == "detailed":
            return await self._build_detailed(session, user, guild_id, params)

        from app.api.v1.tenant_endpoints.tasks import query_tasks_for_export

        tasks = await query_tasks_for_export(
            session,
            user,
            guild_id,
            **_selector(params),
            max_rows=settings.EXPORT_MAX_ROWS,
        )
        loc = export_locale(user)
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        # Both attribution fields can be absent (some OAuth-provisioned
        # accounts carry neither) — never render the literal "None".
        author = user.full_name or user.email or et("fallback.unknownAuthor", loc)
        subtitle = " · ".join(
            [
                et("summary.tasks", loc, count=len(tasks)),
                et("generatedBy", loc, date=generated_at, author=author),
            ]
        )
        data = {
            "title": et("title.tasks", loc),
            "subtitle": subtitle,
            "footer": et("footer.tasks", loc),
            "columns": _columns(loc),
            "rows": [_row(t, loc) for t in tasks],
            "empty_message": et("empty.tasks", loc),
            "untitled": et("fallback.untitled", loc),
        }
        # Layout variant within a format (markdown table vs checklist) — part
        # of the selector, so a queued job renders the same shape on replay.
        if params.get("layout") == "checklist":
            data["layout"] = "checklist"
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(RenderItem(key="tasks", data=data),),
        )

    async def _build_detailed(
        self, session: AsyncSession, user: User, guild_id: int, params: dict
    ) -> RenderRequest:
        from app.api.v1.tenant_endpoints.tasks import (
            query_tasks_for_detailed_export,
        )

        tasks, comments = await query_tasks_for_detailed_export(
            session,
            user,
            guild_id,
            **_selector(params),
            max_rows=settings.EXPORT_MAX_ROWS,
        )
        loc = export_locale(user)
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        author = user.full_name or user.email or et("fallback.unknownAuthor", loc)
        data = {
            "title": et("title.tasks", loc),
            "subtitle": " · ".join(
                [
                    et("summary.tasks", loc, count=len(tasks)),
                    et("generatedBy", loc, date=generated_at, author=author),
                ]
            ),
            "footer": et("footer.tasks", loc),
            "empty_message": et("empty.tasks", loc),
            # The template is content-free: every field label arrives already
            # localized (columns.* reuses the table headers; detail.* adds the
            # section labels unique to this report).
            "labels": {
                "status": et("columns.status", loc),
                "priority": et("columns.priority", loc),
                "due": et("columns.due", loc),
                "start": et("detail.start", loc),
                "assignees": et("columns.assignees", loc),
                "tags": et("columns.tags", loc),
                "description": et("detail.description", loc),
                "noDescription": et("detail.noDescription", loc),
                "subtasks": et("detail.subtasks", loc),
                "comments": et("detail.comments", loc),
            },
            "tasks": [_detail(t, comments.get(t.id, []), loc) for t in tasks],
        }
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.detail_template_id,
            format="pdf",
            batch=(RenderItem(key="tasks", data=data),),
        )


def _selector(params: dict) -> dict[str, Any]:
    """Whitelist the selector keys — a job row's params round-trip through
    JSON, so never splat them into the query functions unfiltered."""
    return {
        "conditions": params.get("conditions"),
        "sorting": params.get("sorting"),
        "tz": params.get("tz"),
        "include_archived": bool(params.get("include_archived", False)),
    }


def _row(task: Task, locale: str) -> dict[str, Any]:
    return {
        "title": task.title,
        "project": task.project.name if task.project else "",
        # Status names are user-created (not translatable); priority is an app
        # enum, so it localizes.
        "status": task.task_status.name if task.task_status else "",
        "priority": et(f"priority.{task.priority.value}", locale)
        if task.priority
        else "",
        "due": task.due_date.strftime("%Y-%m-%d") if task.due_date else "",
        "assignees": ", ".join(a.full_name or a.email for a in (task.assignees or [])),
        # Not a projected column (absent from _COLUMNS): drives the checklist
        # layout's checkbox state.
        "done": bool(
            task.task_status and task.task_status.category == TaskStatusCategory.done
        ),
    }


def _detail(task: Task, comments: list, locale: str) -> dict[str, Any]:
    """One task's full record for the detailed report. Free-text fields
    (title, description, subtask content, comment bodies, names) are user data
    and stay verbatim; only the priority enum localizes."""
    return {
        "title": task.title,
        "project": task.project.name if task.project else "",
        "status": task.task_status.name if task.task_status else "",
        "priority": et(f"priority.{task.priority.value}", locale)
        if task.priority
        else "",
        "due": task.due_date.strftime("%Y-%m-%d") if task.due_date else "",
        "start": task.start_date.strftime("%Y-%m-%d") if task.start_date else "",
        "assignees": [a.full_name or a.email for a in (task.assignees or [])],
        "tags": sorted(
            link.tag.name for link in task.tag_links if link.tag is not None
        ),
        "description": task.description or "",
        "subtasks": [
            {"content": s.content, "done": bool(s.is_completed)}
            for s in sorted(task.subtasks or [], key=lambda s: s.position)
        ],
        "comments": [
            {
                "author": (c.author.full_name or c.author.email) if c.author else "",
                "date": c.created_at.strftime("%Y-%m-%d"),
                # ``content`` is NOT NULL today, but guard anyway: a present-but
                # -null value would reach the template's multiline() as `none`
                # (unlike an absent key, which takes the default) and abort the
                # compile. Same `or ""` guard as description.
                "content": c.content or "",
                # Nesting level: a reply renders indented under its parent, so
                # the thread reads like the on-screen discussion, not a flat
                # chronological dump.
                "depth": depth,
            }
            for c, depth in _thread_comments(comments)
        ],
    }


def _thread_comments(comments: list) -> list[tuple]:
    """Order comments as a reply tree — each parent immediately followed by its
    replies (indented one level deeper), preserving the incoming chronological
    order within every level. Returns ``(comment, depth)`` pairs.

    A comment whose parent isn't in the set (parent deleted, or a reply loaded
    without its root) is treated as a root, so nothing is dropped."""
    ids = {c.id for c in comments}
    children: dict[int, list] = {}
    roots: list = []
    for comment in comments:
        parent_id = comment.parent_comment_id
        if parent_id is None or parent_id not in ids:
            roots.append(comment)
        else:
            children.setdefault(parent_id, []).append(comment)

    ordered: list[tuple] = []

    def walk(comment, depth: int) -> None:
        ordered.append((comment, depth))
        for child in children.get(comment.id, []):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    return ordered
