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

from datetime import datetime, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.models.platform.user import User
from app.schemas.tenant.project_export import ProjectExportEnvelope
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.export.i18n import et, export_locale
from app.services.platform.csv_export import safe_filename_component

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


class ProjectAdapter:
    source = "project"
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
        from app.api.v1.tenant_endpoints.projects import count_project_export_rows

        return await count_project_export_rows(
            session, user, guild_id, project_id=_project_id(params)
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
        from app.api.v1.tenant_endpoints.projects import build_project_export_for_user

        envelope = await build_project_export_for_user(
            session, user, guild_id, project_id=_project_id(params)
        )
        # One clock read: the filename date and the subtitle timestamp must
        # not straddle midnight into disagreeing dates.
        now = datetime.now(timezone.utc)
        date = now.strftime("%Y-%m-%d")
        stem = safe_filename_component(envelope.project.name).lower()
        if format == "json":
            # Preserve the historical backup convention:
            # <project-name>-<date>.initiative-project.json
            item = RenderItem(
                key=f"{stem}-{date}.initiative-project",
                data=envelope.model_dump(mode="json"),
            )
        else:
            item = RenderItem(
                key=f"{stem}-{date}", data=_report_payload(envelope, user, now)
            )
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(item,),
        )


def _report_payload(envelope: ProjectExportEnvelope, user: User, now: datetime) -> dict:
    tasks = [t for t in envelope.tasks if not t.is_archived]
    loc = export_locale(user)
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")
    # Both attribution fields can be absent (some OAuth-provisioned accounts
    # carry neither) — never render the literal "None".
    author = user.full_name or user.email or et("fallback.unknownAuthor", loc)
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
                "assignees": ", ".join(t.assignee_emails),
            }
            for t in tasks
        ],
    }


def _project_id(params: dict) -> int:
    """The job row's params round-trip through JSON — validate, don't trust."""
    try:
        return int(params["project_id"])
    except (KeyError, TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
