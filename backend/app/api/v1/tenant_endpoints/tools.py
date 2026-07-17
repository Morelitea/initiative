"""Generic per-tool endpoints — the ``Tool`` enum is the path parameter.

One route serves every tool, so a new ``Tool`` member gets the surface with no
per-tool endpoint: loading + authorization go through the unified
resource-access registry and tag assignment through the tag-link registry.
Only the content-level extras (tasks, queue items) keep hand-written tag
routes — they are sub-resources of a tool, not tools themselves.
"""

from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.tools import Tool
from app.models.platform.user import User
from app.models.tenant.tag import Tag
from app.schemas.tenant.tag import TagSetRequest, TagSummary
from app.services.stream_authz import authority as stream_authority
from app.services.tenant import tags as tags_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]

# Tools with a live stream room: (channel, event_type) for the content-free
# update signal — subscribed views refetch through the REST path on any event.
_STREAM_ROOMS: dict[Tool, tuple[str, str]] = {
    Tool.queue: ("queue", "queue_updated"),
    Tool.counter_group: ("counter_group", "group_updated"),
}


@router.put("/{tool}/{tool_id}/tags", response_model=List[TagSummary])
async def set_tool_tags(
    tool: Tool,
    tool_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[TagSummary]:
    """Set tags on any tool entity. Replaces all existing tags with the
    provided list and returns the entity's new tags. Requires write access."""
    row = await resource_access.load_authorized(
        session,
        tool,
        tool_id,
        current_user,
        guild_context,
        access="write",
    )
    tag_ids = await tags_service.set_entity_tags(
        session,
        tags_service.TOOL_TAG_LINKS[tool],
        guild_id=guild_context.guild_id,
        entity_id=row.id,
        tag_ids=tags_in.tag_ids,
    )
    row.updated_at = datetime.now(timezone.utc)
    session.add(row)
    await session.commit()

    room = _STREAM_ROOMS.get(tool)
    if room is not None:
        channel, event_type = room
        await stream_authority.emit(
            guild_context.guild_id, channel, row.id, event_type, {"id": row.id}
        )

    if not tag_ids:
        return []
    tags_by_id = {
        tag.id: tag
        for tag in (await session.exec(select(Tag).where(Tag.id.in_(tag_ids)))).all()
    }
    return [
        TagSummary(id=tag.id, name=tag.name, color=tag.color)
        for tag in (tags_by_id[tag_id] for tag_id in tag_ids)
    ]
