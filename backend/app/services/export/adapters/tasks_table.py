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


# Column spec shared by every format: the PDF template reads the row keys it
# knows; the tabular renderers project rows through this list in order.
_COLUMNS = (
    {"key": "title", "label": "Task"},
    {"key": "project", "label": "Project"},
    {"key": "status", "label": "Status"},
    {"key": "priority", "label": "Priority"},
    {"key": "due", "label": "Due"},
    {"key": "assignees", "label": "Assignees"},
)


class TasksTableAdapter:
    source = "tasks"
    template_id = "task-table"
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
        from app.api.v1.tenant_endpoints.tasks import query_tasks_for_export

        tasks = await query_tasks_for_export(
            session,
            user,
            guild_id,
            **_selector(params),
            max_rows=settings.EXPORT_MAX_ROWS,
        )
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        # Both attribution fields can be absent (some OAuth-provisioned
        # accounts carry neither) — never render the literal "None".
        author = user.full_name or user.email or "unknown"
        data = {
            "title": "Tasks",
            "subtitle": (
                f"{len(tasks)} task{'s' if len(tasks) != 1 else ''}"
                f" · generated {generated_at} by {author}"
            ),
            "footer": "Tasks export",
            "columns": [dict(c) for c in _COLUMNS],
            "rows": [_row(t) for t in tasks],
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


def _selector(params: dict) -> dict[str, Any]:
    """Whitelist the selector keys — a job row's params round-trip through
    JSON, so never splat them into the query functions unfiltered."""
    return {
        "conditions": params.get("conditions"),
        "sorting": params.get("sorting"),
        "tz": params.get("tz"),
        "include_archived": bool(params.get("include_archived", False)),
    }


def _row(task: Task) -> dict[str, Any]:
    return {
        "title": task.title,
        "project": task.project.name if task.project else "",
        "status": task.task_status.name if task.task_status else "",
        "priority": task.priority.value if task.priority else "",
        "due": task.due_date.strftime("%Y-%m-%d") if task.due_date else "",
        "assignees": ", ".join(a.full_name or a.email for a in (task.assignees or [])),
        # Not a projected column (absent from _COLUMNS): drives the checklist
        # layout's checkbox state.
        "done": bool(
            task.task_status and task.task_status.category == TaskStatusCategory.done
        ),
    }
