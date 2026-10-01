"""Project source adapter: backup envelope (json) and project report
(pdf/csv/xlsx), engine-delivered.

The json format is the self-contained backup the import endpoint consumes —
its payload is the envelope verbatim. The report formats project the same
envelope into the shared columns/rows payload: a formatted PDF via the
``project-report`` template, or a task table via the tabular renderers.
Archived tasks stay in the backup (it must round-trip everything) but are
excluded from the report formats, matching the on-screen list defaults — save
the ones archived along with the project, which the list shows too.

``filters.tasks`` narrows each project's tasks to those the task list
answers with the same filters (``TaskFilters``); without it, every task rides.

Access rule for every format: WRITE on the project (read-only members can't
take backups), enforced by the ``projects.py`` seams at both count and build
time, under the caller's RLS session.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, field_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.db.session import require_guild_context
from app.models.platform.user import User
from app.schemas.query import FilterCondition, FilterOp
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
)
from app.services.export.contract import RenderItem
from app.services.export.i18n import et, export_locale
from app.services.permissions import EXPORT_ACCESS

# (row key, ``exports`` label key, Typst width hint) — labels resolve to the
# creator's locale at build time.
_COLUMNS = (
    ("title", "columns.task", "2fr"),
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


class TaskFilters(BaseModel):
    """The tasks a project's export carries: those the task list shows with
    these filters, as ``GET /tasks/`` takes them."""

    model_config = ConfigDict(extra="forbid")

    conditions: str | None = None
    include_archived: bool = False

    @field_validator("conditions")
    @classmethod
    def _readable(cls, value: str | None) -> str | None:
        # The task list's own checks, so a malformed filter is refused before a
        # job exists rather than failing it.
        from app.services.tenant.task_queries import check_task_conditions

        check_task_conditions(value)
        return value


class ProjectAdapter(ToolExportAdapter):
    tool = Tool.project
    template_id = "project-report"
    formats = ("json", "pdf", "csv", "xlsx")
    content_filters: ClassVar[dict[str, type[BaseModel]]] = {"tasks": TaskFilters}

    async def count(
        self,
        session: AsyncSession,
        *,
        user: User,
        guild_id: int,
        params: dict,
        format: str,
    ) -> int:
        # The row count is a query of its own here — a project's size is its
        # task list, which the backup envelope is built from but does not
        # have to be built to know.
        from app.api.v1.tenant_endpoints.projects import count_project_export_rows

        total = 0
        for project_id in self.selection(params):
            total += await count_project_export_rows(
                session, user, guild_id, project_id=project_id
            )
        return total

    async def fetch(
        self,
        session: AsyncSession,
        user: User,
        guild_id: int,
        project_id: int,
        /,
        *,
        access: str = EXPORT_ACCESS,
    ) -> ProjectExportEnvelope:
        from app.api.v1.tenant_endpoints.projects import build_project_export_for_user

        # The seam enforces the rung per project — one project short of it in
        # the selection fails the whole export, never a silent gap.
        return await build_project_export_for_user(
            session, user, guild_id, project_id=project_id, access=access
        )

    async def initiative_ids(
        self, session: AsyncSession, user: User, guild_id: int, initiative_id: int, /
    ) -> list[int]:
        from app.services.tenant.project_export import list_project_ids_for_export

        return await list_project_ids_for_export(
            session, user, guild_id, initiative_ids=[initiative_id]
        )

    async def reach(
        self,
        session: AsyncSession,
        params: dict,
        envelopes: list[ProjectExportEnvelope],
        /,
    ) -> set[int]:
        # The envelope is portable and names no initiative; the rows do.
        from sqlmodel import select

        from app.models.tenant.project import Project

        return set(
            await session.exec(
                select(Project.initiative_id).where(
                    Project.id.in_(self.selection(params))
                )
            )
        )

    @property
    def prepares(self) -> bool:
        # A project's tasks are filtered one project at a time; nothing is
        # gained by holding a whole initiative's envelopes at once.
        return False

    async def prepare(
        self,
        session: AsyncSession,
        envelopes: list[ProjectExportEnvelope],
        ctx: BuildContext,
        /,
    ) -> set[str | None] | None:
        """The refs of the tasks the export's task filters leave; ``None``
        keeps every task.

        Each project is asked about on its own, as its task list is: a list
        that names its project reads it by the rule for that project, which
        is what the export has already been allowed."""
        from app.models.tenant.task import Task
        from app.services.tenant import task_queries
        from app.services.tenant.project_export import task_ref

        tasks = getattr(ctx.filters, "tasks", None)
        if tasks is None:
            return None
        ids = [
            int(task.external_ref.removeprefix("task:"))
            for envelope in envelopes
            for task in envelope.tasks
            if task.external_ref
        ]
        by_project: dict[int, list[int]] = defaultdict(list)
        for task_id, project_id in await session.exec(
            select(Task.id, Task.project_id).where(Task.id.in_(ids))
        ):
            by_project[project_id].append(task_id)
        query = await task_queries.parse_task_list_query(
            session, tasks.conditions, None, getattr(ctx.now.tzinfo, "key", None)
        )
        kept: set[int] = set()
        for project_id, task_ids in by_project.items():
            # Confined after parsing, so naming the project is not one more of
            # the conditions a list may hold.
            confined = replace(
                query,
                user_conditions=[
                    FilterCondition(
                        field="project_id", op=FilterOp.eq, value=project_id
                    ),
                    *query.user_conditions,
                ],
                project_id=project_id,
            )
            build = await task_queries.guild_task_query_builder(
                session,
                ctx.user,
                require_guild_context(session),
                q=confined,
                include_archived=tasks.include_archived,
            )
            if build is not None:
                kept.update(
                    await session.exec(
                        build(select(Task.id)).where(Task.id.in_(task_ids))
                    )
                )
        return {task_ref(task_id) for task_id in kept}

    def title(self, envelope: ProjectExportEnvelope, /) -> str:
        return envelope.project.name

    def item(self, envelope: ProjectExportEnvelope, ctx: BuildContext, /) -> RenderItem:
        kept: Any = ctx.prepared
        if kept is not None:
            # A link to a task this export left out has nothing to land on.
            left_out = {t.external_ref for t in envelope.tasks} - kept
            envelope = envelope.model_copy(
                update={
                    "tasks": [
                        t.model_copy(
                            update={
                                "links": [
                                    link
                                    for link in t.links
                                    if link.target_external_ref not in left_out
                                ]
                            }
                        )
                        for t in envelope.tasks
                        if t.external_ref in kept
                    ]
                }
            )
        return build_project_item(
            envelope, ctx.format, ctx.user, ctx.now, filtered=kept is not None
        )


def build_project_item(
    envelope: ProjectExportEnvelope,
    format: str,
    user: User,
    now: datetime,
    *,
    filtered: bool = False,
) -> RenderItem:
    date = now.strftime("%Y-%m-%d")
    name = envelope.project.name
    if format == "json":
        # Preserve the historical backup convention:
        # <project-name>-<date>.initiative-project.json
        return RenderItem(
            key=envelope_key(Tool.project, name, date),
            data=envelope.model_dump(mode="json"),
        )
    return RenderItem(
        key=export_stem(name, date), data=_report_payload(envelope, user, filtered)
    )


def _report_payload(
    envelope: ProjectExportEnvelope, user: User, filtered: bool
) -> dict:
    # A report shows what the task list does: the filters' answer when the
    # export has one, which already says whether archived tasks belong, and
    # the list's default otherwise.
    project_archived_at = envelope.project.archived_at
    tasks = [
        t
        for t in envelope.tasks
        if filtered or t.archived_at is None or t.archived_at == project_archived_at
    ]
    loc = export_locale(user)
    return {
        # The project name is user data — never translated.
        "title": envelope.project.name,
        "subtitle": et("summary.tasks", loc, count=len(tasks)),
        "footer": et("footer.project", loc, name=envelope.project.name),
        "page_of": et("pageOf", loc),
        "description": envelope.project.description or "",
        "columns": _columns(loc),
        "empty_message": et("empty.project", loc),
        "rows": [
            {
                "title": t.title,
                "status": t.status_name,
                "priority": et(f"priority.{t.priority.value}", loc)
                if t.priority
                else "",
                "due": t.due_date.strftime("%Y-%m-%d") if t.due_date else "",
                "assignees": ", ".join(t.assignee_handles),
            }
            for t in tasks
        ],
    }
