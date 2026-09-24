"""Sharing a tool — one route, mounted once for every tool.

``PUT /{tool}/{id}/grants`` replaces a resource's whole sharing state. Nine
copies of it said the same thing: hand the body to
``resource_access.set_resource_grants``, then answer with the row as a read
would return it. Neither half depends on which tool it is beyond the Read model
and the tool's own re-read, so the route is mounted per ``Tool`` straight out of
the resource-access registry rather than written nine times over.

The decision itself stays in ``resource_access.set_resource_grants`` — load,
authorize managing access, rebuild every non-owner grant, run the tool's
post-change side effect — so this module adds no gate of its own.

Afterwards every tool tells its room that sharing moved. The event carries the
new grant list and nothing else; each open window refetches, and what it may
then see is settled by the same gates any other read goes through. Queues and
counters already did this; the other seven did not, which meant a window left
open kept showing a tool it had just been dropped from until something else
refreshed it.

Each route keeps the path, method, tag, name, summary, description and
parameters its tool already had, so the published surface and the generated
client are unchanged.

An installed app reaches the route for each tool that serves apps, under
``sharing:write``. What it may change is decided as for a person, by its rung
on the resource, with the tool's write scope beside the sharing scope
(``resource_access.require_install_may_share``).
"""

# NOT ``from __future__ import annotations``: the handlers are built per tool
# with ``Annotated[int, Path(alias=cfg.path_param)]`` closing over a local, and
# stringized annotations re-evaluate it where that local is out of scope.

from enum import Enum
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Path

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    GuildContext,
    RLSSessionDep,
    app_scope,
    get_current_active_user,
    get_guild_membership,
)
from app.api.v1.tenant_endpoints.tool_lists import TOOL_LISTS, ToolListSpec
from app.core.tools import Tool
from app.models.platform.user import User
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services.stream_authz import authority as stream_authority

router = APIRouter(route_class=ActorRoute)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
CurrentUserDep = Annotated[User, Depends(get_current_active_user)]
SharingWrite = Annotated[
    ActorContext, Depends(app_scope(resource_access.SHARING_WRITE))
]


def _segment(tool: Tool) -> str:
    """The URL segment a tool is addressed by — its plural in kebab case."""
    return tool.plural.replace("_", "-")


def _title(path_param: str) -> str:
    """The schema title a parameter of this name would be given."""
    return path_param.replace("_", " ").title()


def _mount(
    tool: Tool, cfg: resource_access.ResourceAccessConfig, spec: ToolListSpec
) -> None:
    """Mount ``PUT`` ``/{id}/grants`` for one tool."""
    entity_id_param = Annotated[
        int, Path(alias=cfg.path_param, title=_title(cfg.path_param))
    ]

    async def replace(
        session: Any,
        entity_id: int,
        grants: list[ResourceGrantSchema],
        current_user: Optional[User],
        guild_context: ActorContext,
    ):
        await resource_access.set_resource_grants(
            session, tool, entity_id, current_user, guild_context, grants
        )
        result = await spec.read_row(session, entity_id, current_user, guild_context)
        await stream_authority.emit(
            guild_context.guild_id,
            tool.value,
            entity_id,
            "permissions_changed",
            {"grants": [grant.model_dump(mode="json") for grant in result.grants]},
        )
        return result

    if spec.serves_apps:

        async def set_grants(
            entity_id: entity_id_param,
            grants: list[ResourceGrantSchema],
            session: ActorSessionDep,
            current_user: ActorUserDep,
            guild_context: SharingWrite,
        ):
            return await replace(
                session, entity_id, grants, current_user, guild_context
            )

    else:

        async def set_grants(
            entity_id: entity_id_param,
            grants: list[ResourceGrantSchema],
            session: RLSSessionDep,
            current_user: CurrentUserDep,
            guild_context: GuildContextDep,
        ):
            return await replace(
                session, entity_id, grants, current_user, guild_context
            )

    tags: list[str | Enum] = [spec.tag or tool.plural]
    router.add_api_route(
        f"/{_segment(tool)}/{{{cfg.path_param}}}/grants",
        set_grants,
        methods=["PUT"],
        response_model=spec.read_model,
        name=f"set_{tool.value}_grants",
        description=spec.grants_doc,
        tags=tags,
    )


for _tool, _cfg in resource_access.RESOURCE_ACCESS.items():
    _mount(_tool, _cfg, TOOL_LISTS[_tool])
