"""Recent views — one pair of routes, mounted once for every tool.

Opening a tool puts it in the layout header's tabs bar; closing the tab takes
it out again. Neither act depends on which tool it is beyond naming the row, so
the pair is mounted per ``Tool`` straight out of the resource-access registry
rather than written nine times over. Loading and authorizing is
``resource_access.load_authorized`` — the same gate every other read of that
tool goes through, so each tool keeps its own refusals without restating them —
and the storage is ``services.tenant.recent_views``, whose cross-guild read
side is ``tenant_endpoints/recents.py``.

Each route keeps the path, method, status code, tag and name its tool already
had, so the published surface and the generated client are unchanged.
"""

# NOT ``from __future__ import annotations``: the handlers are built per tool
# with ``Annotated[int, Path(alias=cfg.path_param)]`` closing over a local, and
# stringized annotations re-evaluate it where that local is out of scope.

from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Depends, Path, status

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.tools import Tool
from app.models.platform.user import User
from app.schemas.tenant.recent_view import RecentViewWrite
from app.services.tenant import recent_views as recent_views_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]

# The OpenAPI tag a tool's routes carry. It is the tool's own plural, except
# for counter groups: their router shares the wider "counters" tag with the
# individual counters underneath them.
_TAGS: dict[Tool, str] = {Tool.counter_group: "counters"}


def _segment(tool: Tool) -> str:
    """The URL segment a tool is addressed by — its plural in kebab case."""
    return tool.plural.replace("_", "-")


def _title(path_param: str) -> str:
    """The schema title a parameter of this name would be given."""
    return path_param.replace("_", " ").title()


def _mount(tool: Tool, cfg: resource_access.ResourceAccessConfig) -> None:
    """Mount ``POST``/``DELETE`` ``/{id}/view`` for one tool."""
    entity_id_param = Annotated[
        int, Path(alias=cfg.path_param, title=_title(cfg.path_param))
    ]

    async def record_view(
        entity_id: entity_id_param,
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
    ) -> RecentViewWrite:
        """Record that the caller opened this entity, for the tabs bar.

        Takes read access, the same the entity's own page takes. A PAM
        grantee's browsing is transient by design and is not stored.
        """
        row = await resource_access.load_authorized(
            session, tool, entity_id, current_user, guild_context
        )
        record = await recent_views_service.record_view(
            session,
            user_id=current_user.id,
            entity_type=tool.value,
            entity_id=row.id,
            persist=not guild_context.is_pam,
            limit=current_user.recent_tabs_limit,
        )
        return RecentViewWrite(
            entity_type=tool.value,
            entity_id=row.id,
            last_viewed_at=record.last_viewed_at,
        )

    async def clear_view(
        entity_id: entity_id_param,
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
    ) -> None:
        """Close this entity's tab: drop the caller's own recent-view row.

        Idempotent — a tab that is not open stays closed.
        """
        row = await resource_access.load_authorized(
            session, tool, entity_id, current_user, guild_context
        )
        await recent_views_service.clear_view(
            session,
            user_id=current_user.id,
            entity_type=tool.value,
            entity_id=row.id,
        )

    path = f"/{_segment(tool)}/{{{cfg.path_param}}}/view"
    tags: list[str | Enum] = [_TAGS.get(tool, tool.plural)]
    router.add_api_route(
        path,
        record_view,
        methods=["POST"],
        response_model=RecentViewWrite,
        name=f"record_{tool.value}_view",
        tags=tags,
    )
    router.add_api_route(
        path,
        clear_view,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"clear_{tool.value}_view",
        tags=tags,
    )


for _tool, _cfg in resource_access.RESOURCE_ACCESS.items():
    _mount(_tool, _cfg)
