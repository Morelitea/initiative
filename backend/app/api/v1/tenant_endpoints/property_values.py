"""Custom property values on any tool or sub-tool — the one write route.

Every target in ``PROPERTY_TARGETS`` is written here and nowhere else; each
target's read carries its values as ``properties``. Which tool governs a target
and how a row reaches it come from the properties seam
(``properties_service.PROPERTY_LINKS``), so a new tool is writable here the
moment it exists.
"""

from typing import Annotated, Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    plugin_scope_by,
)
from app.core.plugin_scopes import tool_resource
from app.schemas.tenant.property import (
    PropertySummary,
    PropertyTarget,
    PropertyValuesSetRequest,
)
from app.services.tenant import properties as properties_service

router = APIRouter(route_class=ActorRoute)

#: An installed app writes a target's values with the write scope of the tool
#: that governs it — a task's with ``projects:write``.
PropertiesWrite = Annotated[
    ActorContext,
    Depends(
        plugin_scope_by(
            "target",
            {
                target: f"{tool_resource(spec.tool).value}:write"
                for target, spec in properties_service.PROPERTY_LINKS.items()
            },
        )
    ),
]


@router.put("/{target}/{entity_id}", response_model=List[PropertySummary])
async def set_properties(
    target: PropertyTarget,
    entity_id: int,
    payload: PropertyValuesSetRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: PropertiesWrite,
) -> List[PropertySummary]:
    """Replace the custom property values on one tool or sub-tool.

    Requires write on the tool that governs it: a tool itself, or the tool a
    sub-tool sits in (a task's project, an event's calendar). Each value's
    definition must belong to the same initiative, so a row that belongs to no
    initiative carries none. Values are validated against each definition's
    type and options. An installed app names the person a person-valued
    property holds by its reference for them. An empty list clears them all.
    """
    spec = properties_service.PROPERTY_LINKS[target.value]
    row: Any
    if spec.via is None:
        row = await resource_access.load_authorized(
            session, spec.tool, entity_id, current_user, guild_context, access="write"
        )
        initiative_id = row.initiative_id
    else:
        row = (
            await session.exec(select(spec.model).where(spec.model.id == entity_id))
        ).one_or_none()
        if row is None:
            # Every sub-tool's code follows the one spelling: TASK_NOT_FOUND,
            # CALENDAR_EVENT_NOT_FOUND, WIKI_PAGE_NOT_FOUND, …
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{target.value.upper()}_NOT_FOUND",
            )
        governing = await resource_access.load_authorized(
            session,
            spec.tool,
            spec.governing_id(row),
            current_user,
            guild_context,
            access="write",
        )
        initiative_id = governing.initiative_id

    try:
        await properties_service.set_values(
            session, row, payload.values, initiative_id=initiative_id
        )
    except HTTPException:
        await session.rollback()
        raise
    await session.commit()
    summaries = await properties_service.summaries_by_id(
        session, target.value, [entity_id]
    )
    return summaries.get(entity_id, [])
