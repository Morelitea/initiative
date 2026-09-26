"""Deleting a tool — one route, mounted once for every tool.

``DELETE /{tool}/{id}`` puts a tool in the trash with everything inside it.
Nine copies of it said the same thing: load and authorize with the delete
action, hand the row to ``soft_delete.trash``, commit. None of that depends on
which tool it is, so the route is mounted per ``Tool`` straight out of the
resource-access registry rather than written nine times over.

What goes in with it is the lifecycle tree's (``services.tenant.lifecycle_tree``),
and restoring or purging it is the trash's (``tenant_endpoints/trash.py``).

Afterwards the tool's room is told it was deleted, so an open window refetches
and finds it gone.

Each route keeps the path, method, status code, tag and name its tool already
had, so the generated client is unchanged.
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
from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS
from app.core.tools import Tool
from app.models.platform.user import User
from app.services.content_sockets import sockets
from app.services.permissions import Action
from app.services.tenant.soft_delete import trash

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]


def _title(path_param: str) -> str:
    """The schema title a parameter of this name would be given."""
    return path_param.replace("_", " ").title()


def _mount(tool: Tool, cfg: resource_access.ResourceAccessConfig) -> None:
    """Mount ``DELETE`` ``/{id}`` for one tool."""
    entity_id_param = Annotated[
        int, Path(alias=cfg.path_param, title=_title(cfg.path_param))
    ]

    async def delete(
        entity_id: entity_id_param,
        session: RLSSessionDep,
        current_user: CurrentUserDep,
        guild_context: GuildContextDep,
    ) -> None:
        """Move it to the trash with everything inside it. Restoring it brings
        all of that back; the trash purges it after the community's retention.
        Requires the delete right on it: its owner, or a guild admin."""
        row = await resource_access.load_authorized(
            session, tool, entity_id, current_user, guild_context, action=Action.delete
        )
        await trash(session, row, deleted_by_user_id=current_user.id)
        await session.commit()
        sockets.signal(guild_context.guild_id, tool, entity_id, "deleted")

    tags: list[str | Enum] = [TOOL_LISTS[tool].tag or tool.plural]
    router.add_api_route(
        f"/{tool.route_segment}/{{{cfg.path_param}}}",
        delete,
        methods=["DELETE"],
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"delete_{tool.value}",
        tags=tags,
    )


for _tool, _cfg in resource_access.RESOURCE_ACCESS.items():
    _mount(_tool, _cfg)
