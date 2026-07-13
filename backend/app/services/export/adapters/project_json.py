"""Project-envelope source adapter: the project backup JSON, engine-delivered.

Replaces the retired ``GET /projects/{id}/export`` route. The envelope itself
is unchanged (same schema the import endpoint consumes); what the engine adds
is size-aware delivery — a large project becomes a background job with the
inbox-notification pickup — plus the job-gated download and artifact expiry.

Access rule carried over verbatim: WRITE on the project (read-only members
can't take backups), enforced by the ``projects.py`` seams at both count and
build time, under the caller's RLS session.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.messages import ExportMessages
from app.models.platform.user import User
from app.services.export.contract import RenderItem, RenderRequest
from app.services.export.engine import ExportError
from app.services.platform.csv_export import safe_filename_component


class ProjectJsonAdapter:
    source = "project"
    template_id = "project-envelope"  # no PDF template yet; unused for json
    formats = frozenset({"json"})

    async def count(
        self, session: AsyncSession, *, user: User, guild_id: int, params: dict
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
        # Preserve the historical download convention:
        # <project-name>-<date>.initiative-project.json
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        stem = safe_filename_component(envelope.project.name).lower()
        return RenderRequest(
            guild_id=guild_id,
            template_id=self.template_id,
            format=format,
            batch=(
                RenderItem(
                    key=f"{stem}-{date}.initiative-project",
                    data=envelope.model_dump(mode="json"),
                ),
            ),
        )


def _project_id(params: dict) -> int:
    """The job row's params round-trip through JSON — validate, don't trust."""
    try:
        return int(params["project_id"])
    except (KeyError, TypeError, ValueError):
        raise ExportError(ExportMessages.EXPORT_INVALID_PARAMS)
