"""Dashboard source adapter: the importable backup envelope (json).

A dashboard owns no child content — its ``definition`` is a presentation spec
naming where data lives, and the data itself belongs to the tools it points
at. So the envelope is the spec plus the canvas config, and nothing else: a
restored dashboard finds its data through the tools around it, exactly as the
original did.

Dashboards were excluded from export while the marketplace's definition format
was the only one in play. The rule that replaced the exclusion is narrower and
lives in ``export.provenance``: a dashboard built on an app this build does
not ship is not ours to put in a file, while a hand-built one — the common
case — is ordinary content.

Access rule: READ on the dashboard (exporting is a formatted read), enforced
by the ``get_dashboard_for_export`` seam at both count and build time, under
the caller's RLS session.
"""

from __future__ import annotations

from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.dashboard import Dashboard
from app.services.export.adapters._common import (
    BuildContext,
    ToolExportAdapter,
    envelope_key,
)
from app.services.export.contract import RenderItem


class DashboardAdapter(ToolExportAdapter):
    tool = Tool.dashboard
    formats = frozenset({"json"})

    async def fetch(
        self, session: AsyncSession, user: User, guild_id: int, dashboard_id: int, /
    ) -> Dashboard:
        from app.services.tenant.dashboards import get_dashboard_for_export

        return await get_dashboard_for_export(
            session, user, guild_id, dashboard_id=dashboard_id
        )

    def rows(self, dashboard: Dashboard, /) -> int:
        """A dashboard is worth its widgets: the definition is the size, and a
        canvas of eighty widgets is not the same export as a canvas of one."""
        widgets = (dashboard.definition or {}).get("widgets")
        return max(1, len(widgets) if isinstance(widgets, list) else 1)

    def item(self, dashboard: Dashboard, ctx: BuildContext, /) -> RenderItem:
        return build_dashboard_item(dashboard, ctx.date)


def build_dashboard_item(dashboard: Dashboard, date: str) -> RenderItem:
    return RenderItem(
        key=envelope_key(Tool.dashboard, dashboard.name, date),
        data=_envelope(dashboard),
    )


def _envelope(dashboard: Dashboard) -> dict[str, Any]:
    return {
        "type": "initiative-dashboard",
        "schema_version": 1,
        "name": dashboard.name,
        "description": dashboard.description,
        # Present only for a dashboard installed from a built-in app — the
        # provenance filter has already refused anything else. Carried so a
        # restore can re-resolve the definition from the catalog instead of
        # pinning the copy in this file.
        "listing_uid": dashboard.listing_uid,
        "listing_version": dashboard.listing_version,
        "definition": dict(dashboard.definition or {}),
        "config": dict(dashboard.config or {}),
        "tags": sorted(tag.name for tag in getattr(dashboard, "tags", None) or []),
    }
