"""Project source adapter: backup envelope (json) and project report
(pdf/csv/xlsx), engine-delivered.

The json format is the self-contained backup the import endpoint consumes —
its payload is the envelope verbatim. The report formats project the same
envelope into the shared columns/rows payload: a formatted PDF via the
``project-report`` template, or a task table via the tabular renderers.
Archived tasks stay in the backup (it must round-trip everything) but are
excluded from the report formats, matching the on-screen list defaults.

Access rule for every format: WRITE on the project (read-only members can't
take backups), enforced by the ``projects.py`` seams at both count and build
time, under the caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
    export_stem,
)
from app.services.export.contract import RenderItem
from app.services.export.i18n import et, export_locale
from app.core.user_display import display_name

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


class ProjectAdapter(ToolExportAdapter):
    tool = Tool.project
    template_id = "project-report"
    formats = frozenset({"json", "pdf", "csv", "xlsx"})

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
        self, session: AsyncSession, user: User, guild_id: int, project_id: int, /
    ) -> ProjectExportEnvelope:
        from app.api.v1.tenant_endpoints.projects import build_project_export_for_user

        # The seam enforces WRITE per project — one read-only project in
        # the selection fails the whole export, never a silent gap.
        return await build_project_export_for_user(
            session, user, guild_id, project_id=project_id
        )

    def item(self, envelope: ProjectExportEnvelope, ctx: BuildContext, /) -> RenderItem:
        return build_project_item(envelope, ctx.format, ctx.user, ctx.now)


def build_project_item(
    envelope: ProjectExportEnvelope, format: str, user: User, now: datetime
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
        key=export_stem(name, date), data=_report_payload(envelope, user, now)
    )


def _report_payload(envelope: ProjectExportEnvelope, user: User, now: datetime) -> dict:
    tasks = [t for t in envelope.tasks if t.archived_at is None]
    loc = export_locale(user)
    generated_at = now.strftime("%Y-%m-%d %H:%M %Z")
    # Both attribution fields can be absent (some OAuth-provisioned accounts
    # carry neither) — never render the literal "None".
    author = display_name(user) or et("fallback.unknownAuthor", loc)
    return {
        # The project name is user data — never translated.
        "title": envelope.project.name,
        "subtitle": " · ".join(
            [
                et("summary.tasks", loc, count=len(tasks)),
                et("generatedBy", loc, date=generated_at, author=author),
            ]
        ),
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
