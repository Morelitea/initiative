"""Advanced tool endpoints — CRUD + sharing for the automation tools.

An advanced tool is a normal DAC content resource (like a counter group): the
external automation service (or an in-app UI) creates/reads/updates it here, and
its ``data`` blob is what the service runs. Authorization goes through the shared
``resource_access`` enforcement path.

Scope: ``initiative_id`` set → an initiative-scoped tool (needs
``advanced_tools_enabled`` + the create permission, shared via ``resource_grants``).
``initiative_id`` NULL → **guild-wide**, which only a guild admin may create, and
which is admin-only by RLS (no per-user grants).
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import AdvancedToolMessages, InitiativeMessages
from app.core.tools import Tool
from app.schemas.tenant.tag import TagSetRequest
from app.services.tenant import tags as tags_service
from app.models.platform.user import User
from app.models.tenant.advanced_tool import AdvancedTool
from app.models.tenant.initiative import Initiative, PermissionKey
from app.models.tenant.resource_grant import ResourceAccessLevel, ResourceGrant
from app.schemas.tenant.advanced_tool import (
    AdvancedToolCreate,
    AdvancedToolListResponse,
    AdvancedToolRead,
    AdvancedToolRunRequest,
    AdvancedToolRunResult,
    AdvancedToolUpdate,
    serialize_advanced_tool,
)
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.tenant import advanced_tool as advanced_tool_service

logger = logging.getLogger(__name__)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _compute_my_permission(
    tool: AdvancedTool, user: User, guild_context: GuildContext
) -> str | None:
    return resource_access.my_permission_level(
        tool, Tool.advanced_tool, user, guild_context
    )


async def _refetch(session: RLSSessionDep, tool_id: int) -> AdvancedTool:
    tool = await advanced_tool_service.get_advanced_tool(
        session, tool_id, populate_existing=True
    )
    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=AdvancedToolMessages.NOT_FOUND
        )
    return tool


@router.get("/", response_model=AdvancedToolListResponse)
async def list_advanced_tools(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    initiative_id: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdvancedToolListResponse:
    conditions = [AdvancedTool.guild_id == guild_context.guild_id]

    if initiative_id is not None:
        initiative = await session.get(Initiative, initiative_id)
        if initiative and not initiative.advanced_tools_enabled:
            return AdvancedToolListResponse(
                items=[], total_count=0, page=page, page_size=page_size, has_next=False
            )
        conditions.append(AdvancedTool.initiative_id == initiative_id)
    else:
        # Guild-wide (NULL) rows, plus initiative-scoped rows in an enabled
        # initiative. RLS hides guild-wide rows from non-admins; the DAC narrowing
        # below removes any initiative-scoped row the user has no grant on.
        conditions.append(
            or_(
                AdvancedTool.initiative_id.is_(None),
                AdvancedTool.initiative_id.in_(
                    select(Initiative.id).where(
                        Initiative.advanced_tools_enabled == True  # noqa: E712
                    )
                ),
            )
        )

    # DAC narrowing for ordinary members (a PAM grantee / guild admin sees all the
    # RLS lets through). visible_resource_ids_subquery is grant-based, so it also
    # naturally excludes guild-wide rows (which hold no grants).
    if not rls_service.is_guild_admin(guild_context.role) and not guild_context.is_pam:
        conditions.append(
            AdvancedTool.id.in_(
                permissions_service.visible_resource_ids_subquery(
                    Tool.advanced_tool.value, current_user.id
                )
            )
        )

    count_subq = select(AdvancedTool.id).where(*conditions).subquery()
    total_count = (
        await session.exec(select(func.count()).select_from(count_subq))
    ).one()

    stmt = (
        select(AdvancedTool)
        .where(*conditions)
        .options(
            selectinload(AdvancedTool.grants).selectinload(ResourceGrant.role),
            selectinload(AdvancedTool.initiative).selectinload(Initiative.memberships),
            tags_service.TOOL_TAG_LINKS[Tool.advanced_tool].load_options(),
        )
        .order_by(AdvancedTool.updated_at.desc(), AdvancedTool.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    tools = (await session.exec(stmt)).unique().all()

    items = [
        serialize_advanced_tool(
            t,
            my_permission_level=_compute_my_permission(t, current_user, guild_context),
        )
        for t in tools
    ]
    return AdvancedToolListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total_count,
    )


@router.get("/{advanced_tool_id}", response_model=AdvancedToolRead)
async def read_advanced_tool(
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    tool: Annotated[
        AdvancedTool,
        Depends(resource_access.resource_dependency(Tool.advanced_tool, "read")),
    ],
) -> AdvancedToolRead:
    """Access enforced by resource_dependency before the body runs."""
    return serialize_advanced_tool(
        tool,
        my_permission_level=_compute_my_permission(tool, current_user, guild_context),
    )


@router.post("/{advanced_tool_id}/run", response_model=AdvancedToolRunResult)
async def run_advanced_tool(
    advanced_tool_id: int,
    run_in: AdvancedToolRunRequest,
    request: Request,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> AdvancedToolRunResult:
    """The automation service's delegated run call.

    Only a caller authenticated with an initiative-auto delegation token may
    start a run — interactive sessions and API keys are refused. The delegated
    user then goes through the standard DAC path (write access to the tool), so
    a run carries exactly the authority that user holds at fire time. A tool
    that is trashed, out of reach, or nonexistent answers 404, which the runner
    treats as "tool gone" and cancels the run.

    We don't interpret the definition: the response hands back the current
    ``data`` blob (plus the echoed run context) for the service to execute.
    """
    if getattr(request.state, "delegated_guild_id", None) is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AdvancedToolMessages.DELEGATED_RUN_ONLY,
        )
    tool = await resource_access.load_authorized(
        session,
        Tool.advanced_tool,
        advanced_tool_id,
        current_user,
        guild_context,
        access="write",
    )
    ran_at = datetime.now(timezone.utc)
    logger.info(
        "advanced tool run: guild=%s tool=%s user=%s node_key=%s cause=%s "
        "source_event_id=%s",
        tool.guild_id,
        tool.id,
        current_user.id,
        run_in.node_key,
        run_in.cause,
        run_in.source_event_id,
    )
    return AdvancedToolRunResult(
        advanced_tool_id=tool.id,
        guild_id=tool.guild_id,
        initiative_id=tool.initiative_id,
        node_key=run_in.node_key,
        cause=run_in.cause,
        source_event_id=run_in.source_event_id,
        data=tool.data,
        ran_at=ran_at,
    )


@router.post("/", response_model=AdvancedToolRead, status_code=status.HTTP_201_CREATED)
async def create_advanced_tool(
    tool_in: AdvancedToolCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> AdvancedToolRead:
    if tool_in.initiative_id is None:
        # Guild-wide: guild admins only. Admin-only by RLS, so no grants.
        if not rls_service.is_guild_admin(guild_context.role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AdvancedToolMessages.GUILD_WIDE_REQUIRES_ADMIN,
            )
        tool = AdvancedTool(
            guild_id=guild_context.guild_id,
            initiative_id=None,
            created_by_id=current_user.id,
            name=tool_in.name.strip(),
            data=tool_in.data,
        )
        session.add(tool)
        await session.commit()
    else:
        initiative = (
            await session.exec(
                select(Initiative)
                .where(Initiative.id == tool_in.initiative_id)
                .options(selectinload(Initiative.memberships))
            )
        ).one_or_none()
        if not initiative:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=InitiativeMessages.NOT_FOUND,
            )
        if not initiative.advanced_tools_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=AdvancedToolMessages.NOT_ENABLED,
            )
        if not rls_service.is_guild_admin(guild_context.role):
            has_perm = await rls_service.check_initiative_permission(
                session,
                initiative_id=initiative.id,
                user=current_user,
                permission_key=PermissionKey.create_advanced_tools,
            )
            if not has_perm:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=AdvancedToolMessages.CREATE_PERMISSION_REQUIRED,
                )
        tool = AdvancedTool(
            guild_id=guild_context.guild_id,
            initiative_id=initiative.id,
            created_by_id=current_user.id,
            name=tool_in.name.strip(),
            data=tool_in.data,
        )
        session.add(tool)
        await session.flush()

        session.add(
            ResourceGrant(
                resource_type=Tool.advanced_tool.value,
                resource_id=tool.id,
                user_id=current_user.id,
                role_id=None,
                level=ResourceAccessLevel.owner,
                guild_id=guild_context.guild_id,
                initiative_id=tool.initiative_id,
            )
        )
        await permissions_service.replace_resource_grants(
            session,
            resource_type=Tool.advanced_tool.value,
            resource_id=tool.id,
            guild_id=guild_context.guild_id,
            initiative_id=tool.initiative_id,
            owner_id=current_user.id,
            grants=tool_in.grants,
        )
        await session.commit()

    hydrated = await _refetch(session, tool.id)
    return serialize_advanced_tool(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )


@router.patch("/{advanced_tool_id}", response_model=AdvancedToolRead)
async def update_advanced_tool(
    advanced_tool_id: int,
    tool_in: AdvancedToolUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> AdvancedToolRead:
    tool = await resource_access.load_authorized(
        session,
        Tool.advanced_tool,
        advanced_tool_id,
        current_user,
        guild_context,
        access="write",
    )
    update_data = tool_in.model_dump(exclude_unset=True)
    updated = False
    if "name" in update_data and update_data["name"] is not None:
        tool.name = update_data["name"].strip()
        updated = True
    if "data" in update_data and update_data["data"] is not None:
        tool.data = update_data["data"]
        updated = True

    if updated:
        tool.updated_at = datetime.now(timezone.utc)
        session.add(tool)
        await session.commit()

    hydrated = await _refetch(session, tool.id)
    return serialize_advanced_tool(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )


@router.put("/{advanced_tool_id}/tags", response_model=AdvancedToolRead)
async def set_advanced_tool_tags(
    advanced_tool_id: int,
    tags_in: TagSetRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> AdvancedToolRead:
    """Set tags on an advanced tool. Replaces all existing tags. Requires
    write access."""
    tool = await resource_access.load_authorized(
        session,
        Tool.advanced_tool,
        advanced_tool_id,
        current_user,
        guild_context,
        access="write",
    )
    await tags_service.set_entity_tags(
        session,
        tags_service.TOOL_TAG_LINKS[Tool.advanced_tool],
        guild_id=guild_context.guild_id,
        entity_id=tool.id,
        tag_ids=tags_in.tag_ids,
    )
    tool.updated_at = datetime.now(timezone.utc)
    session.add(tool)
    await session.commit()

    hydrated = await _refetch(session, tool.id)
    return serialize_advanced_tool(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )


@router.delete("/{advanced_tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_advanced_tool(
    advanced_tool_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    tool = await resource_access.load_authorized(
        session,
        Tool.advanced_tool,
        advanced_tool_id,
        current_user,
        guild_context,
        access="read",
    )
    # Owner (or guild admin) may delete — matches the other tools.
    if not rls_service.is_guild_admin(guild_context.role):
        permissions_service.require_access(
            permissions_service.DAC_RESOURCES[Tool.advanced_tool],
            tool,
            current_user,
            require_owner=True,
        )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session, tool, deleted_by_user_id=current_user.id, retention_days=retention_days
    )
    await session.commit()


@router.put("/{advanced_tool_id}/grants", response_model=AdvancedToolRead)
async def set_advanced_tool_grants(
    advanced_tool_id: int,
    grants: list[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> AdvancedToolRead:
    """Replace an initiative-scoped advanced tool's sharing. Guild-wide tools are
    admin-only and reject sharing (see the grant hook)."""
    await resource_access.set_resource_grants(
        session,
        Tool.advanced_tool,
        advanced_tool_id,
        current_user,
        guild_context,
        grants,
    )
    hydrated = await _refetch(session, advanced_tool_id)
    return serialize_advanced_tool(
        hydrated,
        my_permission_level=_compute_my_permission(
            hydrated, current_user, guild_context
        ),
    )
