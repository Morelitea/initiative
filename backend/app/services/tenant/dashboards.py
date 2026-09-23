"""Dashboard service — loaders and helpers for the dashboard tool.

A dashboard is a shareable DAC resource (``resource_type='dashboard'``) whose
``definition`` is a validated presentation spec. It owns no child content: the
data it displays lives in other tools and is fetched per viewer through those
tools' own gated endpoints, so the loaders here only need what serialization
and the permission engine read.
"""

from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db import session as db_session
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.services.tenant import tags as tags_service


def dashboard_loader_options() -> list:
    """Eager-load everything dashboard serialization + authorization needs."""
    return [
        selectinload(Dashboard.grants).selectinload(ResourceGrant.role),
        selectinload(Dashboard.initiative),
        undefer(Dashboard.access_level),
    ]


async def get_dashboard(
    session: AsyncSession,
    dashboard_id: int,
    *,
    populate_existing: bool = False,
) -> Dashboard | None:
    """Fetch a dashboard with the relationships authorization + serialization
    need. RLS scopes the row to the request's guild."""
    stmt = (
        select(Dashboard)
        .where(Dashboard.id == dashboard_id)
        .options(*dashboard_loader_options())
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    result = await session.exec(stmt)
    dashboard = result.one_or_none()
    if dashboard is not None:
        await tags_service.annotate_tags(session, [dashboard])
    return dashboard


async def get_dashboard_for_export(
    session: AsyncSession,
    current_user,
    guild_id: int,
    *,
    dashboard_id: int,
) -> Dashboard:
    """The dashboard-export adapter's seam: fetch + authorize in one place so
    the rule holds on the worker's render-time replay too. READ access
    suffices — exporting is a formatted read.

    A dashboard built on an app this build does not ship is refused here: its
    definition belongs to its publisher, and the way to have it somewhere else
    is to install the app there. ``adapters/backup`` filters those out before
    they reach this seam, so a community's backup is not failed by one of them.
    """
    from fastapi import HTTPException, status as http_status

    from app.core.messages import ExportMessages
    from app.core.tools import Tool
    from app.services.export.provenance import builtin_listing_uids, is_exportable
    from app.services.permissions import DAC_RESOURCES, require_access

    dashboard = await get_dashboard(session, dashboard_id)
    if dashboard is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=Tool.dashboard.not_found_code,
        )
    if dashboard.initiative is not None and not dashboard.initiative.dashboards_enabled:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail=Tool.dashboard.feature_disabled_code,
        )
    require_access(
        DAC_RESOURCES[Tool.dashboard],
        dashboard,
        context=db_session.guild_context(session),
        access="read",
    )
    builtin = await builtin_listing_uids(session, [dashboard.listing_uid])
    if not is_exportable(dashboard.listing_uid, builtin):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=ExportMessages.EXPORT_THIRD_PARTY_APP,
        )
    return dashboard


async def list_dashboard_ids_for_export(
    session: AsyncSession,
    current_user,
    guild_id: int,
    *,
    initiative_ids: list[int],
) -> list[int]:
    """Ids of every dashboard the user may export in the given initiatives —
    DAC-visible to the user, feature-flag respected, and built on nothing but
    this build's own apps. Deterministic order for stable backup output."""
    if not initiative_ids:
        return []
    from app.services.export.provenance import builtin_listing_uids, is_exportable

    rows = list(
        await session.exec(
            select(Dashboard.id, Dashboard.listing_uid)
            .join(Initiative, Initiative.id == Dashboard.initiative_id)
            .where(
                Dashboard.initiative_id.in_(initiative_ids),
                Initiative.dashboards_enabled == True,  # noqa: E712
            )
            .order_by(Dashboard.id.asc())
        )
    )
    builtin = await builtin_listing_uids(session, [uid for _, uid in rows])
    return [did for did, uid in rows if is_exportable(uid, builtin)]
