"""An initiative's views of a tool — the set a target shows, saved whole.

A target is one instance of a tool (``tool`` and ``tool_id``: a project), or,
for a tool whose page the initiative shares, the initiative (``tool`` and
``initiative_id``: its calendar). Reading follows reading the instance, or
being in the initiative. Changing the set follows the ``configure`` action on
the instance — its owner, the initiative's managers, the community's admins —
with write access to it, or, for a shared page, managing the initiative.
"""

from dataclasses import dataclass
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import undefer
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    GuildContextDep,
    RLSSessionDep,
    get_current_active_user,
)
from app.core.messages import InitiativeMessages, ToolViewMessages
from app.core.tools import VIEWS_PER_INSTANCE, VIEWS_SHARED, Tool
from app.models.platform.user import User
from app.models.tenant.initiative import Initiative
from app.models.tenant.project import Project
from app.schemas.tenant.tool_view import (
    InitiativeToolViewsRead,
    ToolViewSetRead,
    ToolViewSetWrite,
    ToolViewSummary,
)
from app.services import permissions as permissions_service
from app.services.permissions import Action
from app.services.tenant import tool_views as tool_views_service
from app.services.tenant.tool_views import Target

router = APIRouter(prefix="/views")

CurrentUser = Annotated[User, Depends(get_current_active_user)]


@dataclass(frozen=True)
class _Resolved:
    """A target, whether the reader may change its set, and the instance it
    names (None for a shared page)."""

    target: Target
    can_configure: bool
    row: Any


async def _resolve(
    session: AsyncSession,
    context: GuildContext,
    user: User,
    tool: Tool,
    tool_id: Optional[int],
    initiative_id: Optional[int],
) -> _Resolved:
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ToolViewMessages.TARGET_INVALID,
    )
    if tool in VIEWS_PER_INSTANCE:
        if tool_id is None or initiative_id is not None:
            raise invalid
        row = await resource_access.load_authorized(
            session, tool, tool_id, user, context
        )
        if row.initiative_id is None:
            raise invalid
        return _Resolved(
            Target(tool, tool_id, row.initiative_id), _configures(row), row
        )

    if tool not in VIEWS_SHARED or tool_id is not None or initiative_id is None:
        raise invalid
    await _require_initiative(session, context, initiative_id)
    can_configure = not context.content_read_only and (
        context.is_admin or initiative_id in context.manager_initiatives
    )
    return _Resolved(Target(tool, None, initiative_id), can_configure, None)


def _configures(row: Any) -> bool:
    """Whether the reader may change an instance's set: configure it, with
    write access to it, as the database answered when it loaded the row."""
    return permissions_service.allows(
        row, Action.configure
    ) and permissions_service.allows(row, Action.contribute)


async def _require_initiative(
    session: AsyncSession, context: GuildContext, initiative_id: int
) -> None:
    """A 404 unless the initiative exists and the reader is in it."""
    found = await session.exec(
        select(Initiative.id).where(Initiative.id == initiative_id)
    )
    if found.one_or_none() is None or not (
        context.is_admin
        or context.is_pam
        or initiative_id in context.member_initiatives
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )


def _require_configure(resolved: _Resolved, context: GuildContext) -> None:
    if resolved.row is None:
        if not resolved.can_configure:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=InitiativeMessages.MANAGER_REQUIRED,
            )
        return
    resource = permissions_service.DAC_RESOURCES[resolved.target.tool]
    for action in (Action.configure, Action.contribute):
        permissions_service.require_access(
            resource, resolved.row, context=context, action=action
        )


async def _read(session: AsyncSession, resolved: _Resolved) -> ToolViewSetRead:
    rows = await tool_views_service.list_rows(session, resolved.target)
    views, layouts = tool_views_service.read_set(resolved.target.tool, rows)
    return ToolViewSetRead(
        views=views,
        item_layouts=layouts,
        stored=bool(rows),
        can_configure=resolved.can_configure,
    )


@router.get("/", response_model=ToolViewSetRead)
async def get_views(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    tool: Tool = Query(),
    tool_id: Optional[int] = Query(default=None),
    initiative_id: Optional[int] = Query(default=None),
) -> ToolViewSetRead:
    """The target's views and item layouts: its own, or the shipped views
    when it has stored none (``stored`` false)."""
    resolved = await _resolve(
        session, guild_context, current_user, tool, tool_id, initiative_id
    )
    return await _read(session, resolved)


@router.get("/initiative", response_model=List[InitiativeToolViewsRead])
async def get_initiative_views(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    initiative_id: int = Query(),
) -> List[InitiativeToolViewsRead]:
    """The views of every project in the initiative the reader can open, by
    name, each its own set or the shipped one, for the initiative's settings.
    A set is changed on its own target."""
    await _require_initiative(session, guild_context, initiative_id)
    # Which projects the reader can open is the projects' own policy's answer.
    projects = (
        await session.exec(
            select(Project)
            .where(
                Project.initiative_id == initiative_id,
                col(Project.archived_at).is_(None),
                col(Project.deleted_at).is_(None),
            )
            .options(undefer(Project.actions))
            .order_by(col(Project.name), col(Project.id))
        )
    ).all()
    stored = await tool_views_service.rows_by_instance(
        session, initiative_id, Tool.project, [project.id for project in projects]
    )
    listed: List[InitiativeToolViewsRead] = []
    for project in projects:
        rows = stored.get(project.id, [])
        views, layouts = tool_views_service.read_set(Tool.project, rows)
        listed.append(
            InitiativeToolViewsRead(
                tool=Tool.project,
                tool_id=project.id,
                name=project.name,
                views=[
                    ToolViewSummary(
                        name=view.name,
                        slug=view.slug,
                        layout=view.definition.layout.type,
                        is_default=view.is_default,
                    )
                    for view in views
                ],
                stored=bool(rows),
                has_item_layout=bool(layouts),
                can_configure=_configures(project),
            )
        )
    return listed


@router.put("/", response_model=ToolViewSetRead)
async def put_views(
    payload: ToolViewSetWrite,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    tool: Tool = Query(),
    tool_id: Optional[int] = Query(default=None),
    initiative_id: Optional[int] = Query(default=None),
) -> ToolViewSetRead:
    """Replace the target's whole set with ``payload``, in its order."""
    resolved = await _resolve(
        session, guild_context, current_user, tool, tool_id, initiative_id
    )
    _require_configure(resolved, guild_context)
    rows = tool_views_service.check_set(resolved.target, payload)
    await tool_views_service.replace_set(session, resolved.target, rows)
    await session.commit()
    return await _read(session, resolved)


@router.delete("/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_views(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    tool: Tool = Query(),
    tool_id: Optional[int] = Query(default=None),
    initiative_id: Optional[int] = Query(default=None),
) -> None:
    """Return the target to the shipped views."""
    resolved = await _resolve(
        session, guild_context, current_user, tool, tool_id, initiative_id
    )
    _require_configure(resolved, guild_context)
    await tool_views_service.clear(session, resolved.target)
    await session.commit()
