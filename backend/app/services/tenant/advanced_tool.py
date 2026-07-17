"""Advanced tool service — loading for authorization/serialization.

The advanced tool is a normal local DAC resource (an ``advanced_tools`` row), so
this loader mirrors the other tool loaders (``get_queue`` etc.): fetch by id with
the ``grants`` and the (possibly NULL) initiative's memberships eager-loaded, so
the generic DAC engine can resolve access. A guild-wide tool (``initiative_id``
NULL) simply has no initiative → the engine falls back to the guild-admin/PAM
legs, which is the intended admin-only behavior.
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.tenant.advanced_tool import AdvancedTool
from app.core.tools import Tool
from app.services.tenant import tags as tags_service
from app.models.tenant.initiative import Initiative
from app.models.tenant.resource_grant import ResourceGrant


async def get_advanced_tool(
    session: AsyncSession,
    advanced_tool_id: int,
    *,
    populate_existing: bool = False,
) -> AdvancedTool | None:
    """Fetch an advanced tool with grants + initiative memberships loaded, or
    ``None`` if it isn't visible (RLS) / doesn't exist. ``populate_existing``
    refreshes an identity-map copy (e.g. after rewriting grants)."""
    stmt = (
        select(AdvancedTool)
        .where(AdvancedTool.id == advanced_tool_id)
        .options(
            selectinload(AdvancedTool.grants).selectinload(ResourceGrant.role),
            selectinload(AdvancedTool.initiative).selectinload(Initiative.memberships),
            tags_service.TOOL_TAG_LINKS[Tool.advanced_tool].load_options(),
        )
    )
    if populate_existing:
        stmt = stmt.execution_options(populate_existing=True)
    return (await session.exec(stmt)).first()
