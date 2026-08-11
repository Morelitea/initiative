"""Dashboard service — loaders and helpers for the dashboard tool.

A dashboard is a shareable DAC resource (``resource_type='dashboard'``) whose
``definition`` is a validated presentation spec. It owns no child content: the
data it displays lives in other tools and is fetched per viewer through those
tools' own gated endpoints, so the loaders here only need what serialization
and the permission engine read.
"""

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.tools import Tool
from app.models.tenant.dashboard import Dashboard
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant
from app.services.tenant import tags as tags_service


def dashboard_loader_options() -> list:
    """Eager-load everything dashboard serialization + authorization needs."""
    return [
        selectinload(Dashboard.grants).selectinload(ResourceGrant.role),
        selectinload(Dashboard.initiative).selectinload(Initiative.memberships),
        tags_service.TOOL_TAG_LINKS[Tool.dashboard].load_options(),
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
    return result.one_or_none()
