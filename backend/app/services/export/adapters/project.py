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

Access rule for every format: the owner rung on the project, or read from an
initiative or community backup, enforced by ``ToolExportAdapter.fetch`` at
both count and build time, under the caller's RLS session.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import Subquery, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.core.user_input_validators import resolve_zone
from app.db.session import require_guild_context
from app.models.platform.user import User
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
    get_for_export,
)
from app.services.export.contract import RenderItem
from app.services.export.filters import narrow, parse_filters
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
        from app.models.tenant.task import Task

        # Every selected project is authorized, as the build fetches each; the
        # size is what the filters leave of them.
        selection = self.selection(params)
        for project_id in selection:
            await get_for_export(
                session, user, guild_id, self.tool, project_id, self.get_row
            )
        filters = parse_filters(self.tool, params.get("filters"))
        kept = await narrow(session, user, self.tool, filters, selection)
        tasks = getattr(filters, "tasks", None)
        if tasks is None:
            return (
                await session.exec(
                    select(func.count())
                    .select_from(Task)
                    .where(Task.project_id.in_(kept))
                )
            ).one()
        return await count_matching_tasks(
            session, user, kept, tasks, resolve_zone(params.get("tz")).key
        )

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
        from app.core.config import settings
        from app.core.user_display import handle_of
        from app.services.tenant.project_export import build_project_export

        # The seam enforces the rung per project — one project short of it in
        # the selection fails the whole export, never a silent gap. Cross-row
        # references (tags, statuses, properties, assignees) travel by name or
        # handle, so the file imports cleanly on another instance.
        project = await super().fetch(
            session, user, guild_id, project_id, access=access
        )
        return await build_project_export(
            session,
            project_id=project.id,
            exported_by_handle=handle_of(user),
            source_instance_url=settings.APP_URL,
            source_guild_id=guild_id,
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
        keeps every task."""
        from app.services.tenant.project_export import task_ref

        tasks = getattr(ctx.filters, "tasks", None)
        if tasks is None:
            return None
        from app.models.tenant.task import Task

        ids = [
            int(task.external_ref.removeprefix("task:"))
            for envelope in envelopes
            for task in envelope.tasks
            if task.external_ref
        ]
        projects = set(
            await session.exec(select(Task.project_id).where(Task.id.in_(ids)))
        )
        kept = await matching_tasks(
            session, ctx.user, projects, tasks, getattr(ctx.now.tzinfo, "key", None)
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


async def _matching(
    session: AsyncSession,
    user: User,
    project_ids: Collection[int],
    tasks: TaskFilters,
    tz: str | None,
) -> Subquery | None:
    """The ids of these projects' tasks that the task list shows with
    ``tasks``, as one statement; ``None`` when there are no projects.

    The export has already been allowed these projects, so the list's question
    about which projects the reader reaches is not asked again: the filters
    only narrow."""
    from app.models.tenant.task import Task
    from app.services.tenant import task_queries

    query = await task_queries.parse_task_list_query(
        session, tasks.conditions, None, tz
    )
    build = await task_queries.guild_task_query_builder(
        session,
        user,
        require_guild_context(session),
        q=query,
        include_archived=tasks.include_archived,
        projects=project_ids,
    )
    return build(select(Task.id)).subquery() if build is not None else None


async def matching_tasks(
    session: AsyncSession,
    user: User,
    project_ids: Collection[int],
    tasks: TaskFilters,
    tz: str | None,
) -> set[int]:
    """The ids of these projects' tasks that the task list shows with
    ``tasks``."""
    matched = await _matching(session, user, project_ids, tasks, tz)
    if matched is None:
        return set()
    return set(await session.exec(select(matched.c.id)))


async def count_matching_tasks(
    session: AsyncSession,
    user: User,
    project_ids: Collection[int],
    tasks: TaskFilters,
    tz: str | None,
) -> int:
    """How many of these projects' tasks the task list shows with ``tasks``,
    counted in the database."""
    matched = await _matching(session, user, project_ids, tasks, tz)
    if matched is None:
        return 0
    return (await session.exec(select(func.count()).select_from(matched))).one()


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
