from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import delete, select

from app.services.tenant import attachments as attachments_service
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    plugin_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.models.tenant.project import (
    Project,
)
from app.models.tenant.resource_grant import (
    ResourceGrant,
)
from app.models.tenant.project_order import ProjectOrder
from app.models.tenant.project_favorite import ProjectFavorite
from app.models.tenant.recent_view import RecentView
from app.models.tenant.task import (
    Task,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.tenant.comment import Comment, in_thread
from app.models.platform.user import User
from app.api import resource_access, tool_copy
from app.core.tools import Tool
from app.db.query import build_paginated_response, paginated_query
from app.db.session import require_actor_context
from app.services import notifications as notifications_service
from app.services.tenant import ownership as ownership_service
from app.services import permissions as permissions_service
from app.services import reachability
from app.services.tenant import named_people
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import archive as archive_service
from app.services.tenant import tool_listing
from app.services.tenant import task_statuses as task_statuses_service
from app.core.messages import ProjectMessages
from app.schemas.tenant.project import (
    project_can,
    ProjectCreate,
    ProjectRead,
    ProjectTaskSummary,
    ProjectReorderRequest,
    ProjectUpdate,
    ProjectActivityEntry,
    ProjectActivityResponse,
)
from app.schemas.tenant.comment import CommentAuthor
from app.services.tenant import project_grants
from app.schemas.tenant.tool import serialize_tool

router = APIRouter(route_class=ActorRoute)

#: The routes an installed plug-in may call, under the projects scopes.
ProjectsRead = Annotated[ActorContext, Depends(plugin_scope("projects:read"))]
ProjectsWrite = Annotated[ActorContext, Depends(plugin_scope("projects:write"))]


async def _attach_task_summaries(session: SessionDep, projects: List[Project]) -> None:
    if not projects:
        return
    project_ids = [project.id for project in projects if project.id is not None]
    summary_map: dict[int, ProjectTaskSummary] = {}
    if project_ids:
        done_case = case((TaskStatus.category == TaskStatusCategory.done, 1), else_=0)
        stmt = (
            select(
                Task.project_id,
                func.count(Task.id),
                func.coalesce(func.sum(done_case), 0),
            )
            .join(Task.task_status)
            .where(Task.project_id.in_(tuple(project_ids)))
            .group_by(Task.project_id)
        )
        result = await session.exec(stmt)
        for project_id, total, completed in result.all():
            summary_map[int(project_id)] = ProjectTaskSummary(
                total=int(total or 0),
                completed=int(completed or 0),
            )

    for project in projects:
        summary = summary_map.get(project.id or 0, ProjectTaskSummary())
        object.__setattr__(project, "task_summary", summary)


async def _get_project_or_404(
    project_id: int,
    session: SessionDep,
    guild_id: int,
    *,
    user_id: int | None,
    populate_existing: bool = False,
) -> Project:
    """Load a project with everything a ``ProjectRead`` reads, or refuse.

    The eager loads are the registry's (``project_grants.get_project_hydrated``
    — the same ones ``resource_access.load_authorized(..., hydrated=True)``
    takes), so a project reaches a response the same way whichever door it came
    through. For callers with no ``GuildContext`` to authorize against: the
    re-read a write answers with, and the export seams, which replay on a
    worker.
    """
    project = await project_grants.get_project_hydrated(
        session, project_id, populate_existing=populate_existing
    )
    if not project:
        raise await reachability.missing_or_denied(
            Tool.project.plural,
            project_id,
            user_id,
            guild_id,
            not_found=Tool.project.not_found_code,
            denied=Tool.project.no_access_code,
        )
    return project


def project_load_options(*, slim: bool = False) -> list:
    """Eager loads for a page of projects.

    The full set serializes a whole ``ProjectRead`` (owner, nested initiative,
    linked files with their DAC, tags, grants). The slim one carries only
    what the level and the owner need — the grants and the level itself —
    since the slim projection drops the owner, files, tags and the
    initiative.
    """
    if slim:
        return [
            selectinload(Project.grants),
            selectinload(Project.initiative),
            undefer(Project.actions),
        ]
    return [
        selectinload(Project.grants).selectinload(ResourceGrant.user),
        selectinload(Project.initiative),
        undefer(Project.actions),
    ]


def visible_project_conditions(
    user_id: int | None,
    *,
    context: ActorContext,
    archived: Optional[bool],
    is_template: Optional[bool],
    search: Optional[str] = None,
    tag_ids: Optional[List[int]] = None,
    initiative_id: Optional[int] = None,
) -> list:
    """WHERE clauses for the guild's DAC-visible projects.

    The guild, the projects switch, sharing, the search box and the tag filter
    are the shared set (:func:`tool_listing.base_conditions`). An archived
    project shows only when asked for, as on every tool list; ``is_template``
    narrows to templates or to the rest, and unset leaves both, as it does for
    files.
    """
    conditions = tool_listing.base_conditions(
        Tool.project,
        Project,
        user_id,
        context=context,
        initiative_id=initiative_id,
        search=search,
        tag_ids=tag_ids,
    )
    if is_template is not None:
        conditions.append(Project.is_template.is_(is_template))
    conditions.append(archive_service.archive_filter_clause(Project, archived))
    return conditions


async def _project_reads(
    session: SessionDep,
    user_id: int | None,
    projects: List[Project],
) -> List[ProjectRead]:
    """``ProjectRead`` for each project, in the order given, with the reader's
    own favourites and last visits. An installed plug-in (``user_id`` ``None``)
    keeps neither."""
    if not projects:
        return []

    project_ids = [project.id for project in projects if project.id is not None]

    await _attach_task_summaries(session, projects)
    await tags_service.annotate_tags(session, projects)
    await properties_service.annotate_properties(session, projects)
    await ownership_service.annotate_owner_plugins(session, projects)
    favorite_ids: set[int] = set()
    view_map: dict[int, datetime] = {}
    if user_id is not None:
        favorite_ids, view_map = await _project_metadata_for_user(
            session, user_id, project_ids
        )

    context = require_actor_context(session)
    return [
        serialize_tool(
            ProjectRead,
            project,
            context=context,
            user_id=user_id,
            is_favorited=project.id in favorite_ids,
            last_viewed_at=view_map.get(project.id or 0),
        )
        for project in projects
    ]


def _slim_project_reads(
    projects: List[Project], user_id: int | None, *, context: ActorContext
) -> List[ProjectRead]:
    """Build lightweight ``ProjectRead`` rows for the slim projection.

    Carries only ``{id, name, icon, initiative_id, can}`` plus
    the cheap scalar flags and who owns it (``owner_id``, or ``owner_plugin`` as
    the caller annotated it); files/grants/tags/the owner's profile/nested
    initiative are left at their defaults so no heavy relationship is
    serialized. ``description`` is dropped too (it would run rich-text
    sanitization for no picker benefit).
    """
    reads: List[ProjectRead] = []
    for project in projects:
        reads.append(
            ProjectRead(
                id=project.id or 0,
                name=project.name,
                description=None,
                icon=project.icon,
                owner_id=ownership_service.owner_user_id_of(project),
                initiative_id=project.initiative_id,
                created_at=project.created_at,
                updated_at=project.updated_at,
                is_template=project.is_template,
                archived_at=project.archived_at,
                pinned_at=project.pinned_at,
                community_id=context.guild_id,
                can=project_can(project, user_id, context=context),
            ).model_copy(
                # Set after construction: the field's alias keeps
                # ``model_validate`` off the ORM row.
                update={"owner_plugin": ownership_service.owner_plugin_of(project)}
            )
        )
    return reads


async def serialize_project_page(
    session: SessionDep,
    user_id: int | None,
    projects: List[Project],
    *,
    slim: bool,
) -> List[ProjectRead]:
    """Serialize one page of the projects list.

    The order is already settled in SQL. The slim projection is a plain
    per-row build with no follow-up queries — that is what makes it slim.
    """
    if slim:
        await ownership_service.annotate_owner_plugins(session, projects)
        return _slim_project_reads(
            projects, user_id, context=require_actor_context(session)
        )
    return await _project_reads(session, user_id, projects)


async def _project_metadata_for_user(
    session: SessionDep,
    user_id: int,
    project_ids: List[int],
) -> tuple[set[int], dict[int, datetime]]:
    """The reader's own favorites and last visits for these projects, as
    ``(favorite_ids, view_map)``."""
    favorites = await session.exec(
        select(ProjectFavorite.project_id).where(
            ProjectFavorite.user_id == user_id,
            ProjectFavorite.project_id.in_(project_ids),
        )
    )
    views = await session.exec(
        select(RecentView.entity_id, RecentView.last_viewed_at).where(
            RecentView.user_id == user_id,
            RecentView.entity_type == Tool.project.value,
            RecentView.entity_id.in_(project_ids),
        )
    )
    return set(favorites.all()), dict(views.all())


async def _project_read_for_user(
    session: SessionDep,
    user_id: int | None,
    project: Project,
) -> ProjectRead:
    return (await _project_reads(session, user_id, [project]))[0]


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> ProjectRead:
    resource_access.refuse_plugin_sharing(guild_context, project_in, "grants")
    if project_in.template_id is not None:
        # Reaching the blueprint is settled first: whether it is a blueprint at
        # all is a fact about a project the caller can already read.
        template = await resource_access.load_authorized(
            session, Tool.project, project_in.template_id, current_user, guild_context
        )
        if not template.is_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ProjectMessages.INVALID_TEMPLATE,
            )
        # A copy of the template with what the request says on top. The
        # schedule is deliberately not inherited: it belongs to the run, not
        # to the blueprint.
        project = await tool_copy.duplicate(
            session,
            Tool.project,
            template,
            initiative_id=project_in.initiative_id,
            name=project_in.name,
            user=current_user,
            actor=guild_context,
            payload=project_in,
            values={
                "is_template": project_in.is_template,
                "start_date": project_in.start_date,
                "end_date": project_in.end_date,
                **project_in.model_dump(
                    include={"icon", "description"}, exclude_none=True
                ),
            },
            grants=project_in.grants,
        )
    else:
        if project_in.initiative_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ProjectMessages.INITIATIVE_REQUIRED,
            )
        await resource_access.prepare_create(
            session, Tool.project, project_in.initiative_id, current_user, guild_context
        )
        project = Project(
            name=project_in.name,
            icon=project_in.icon,
            description=project_in.description,
            initiative_id=project_in.initiative_id,
            is_template=project_in.is_template,
            start_date=project_in.start_date,
            end_date=project_in.end_date,
        )
        session.add(project)
        await session.flush()
        # Sharing before anything that hangs off it: a status is reached
        # through the project, so the project has to be reachable first.
        await resource_access.grant_initial_sharing(
            session,
            guild_context,
            Tool.project,
            user=current_user,
            resource_id=project.id,
            initiative_id=project.initiative_id,
            payload=project_in,
            grants=project_in.grants,
        )
        await session.flush()
        await task_statuses_service.ensure_default_statuses(session, project.id)
        await attachments_service.claim_uploads(session, project)
    await properties_service.write_on_create(session, project, project_in.properties)
    settled = named_people.Governing.of(Tool.project, project)
    await session.commit()
    if project_in.template_id is not None:
        # As for any copy: those the new project's sharing does not reach are
        # let go of its tasks once that sharing is committed.
        await named_people.sweep(session, settled)
        await session.commit()
    project = await _get_project_or_404(
        settled.resource_id,
        session,
        guild_context.guild_id,
        user_id=guild_context.user_id,
    )
    if current_user is not None:
        await notifications_service.notify_project_added(session, project, current_user)
        await session.commit()
    return await _project_read_for_user(session, guild_context.user_id, project)


@router.get("/favorites", response_model=List[ProjectRead])
async def favorite_projects(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    """The reader's favorite projects, most recently favorited first, in the
    slim projection the projects list returns for ``slim=true``."""
    favorites = await session.exec(
        select(Project)
        .join(ProjectFavorite, ProjectFavorite.project_id == Project.id)
        .where(
            ProjectFavorite.user_id == current_user.id,
            *visible_project_conditions(
                current_user.id,
                context=guild_context,
                archived=None,
                is_template=None,
            ),
        )
        .order_by(ProjectFavorite.created_at.desc())
        .options(*project_load_options(slim=True))
    )
    reads = await serialize_project_page(
        session, current_user.id, list(favorites.all()), slim=True
    )
    # Every row here is a favorite, so the flag is known without a lookup.
    return [read.model_copy(update={"is_favorited": True}) for read in reads]


@router.post("/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
async def favorite_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Favorite a project. Idempotent: the pair is the row's key, so a second
    favorite is a no-op rather than a conflict."""
    project = await resource_access.load_authorized(
        session, Tool.project, project_id, current_user, guild_context
    )
    await session.exec(
        pg_insert(ProjectFavorite)
        .values(
            user_id=current_user.id,
            project_id=project.id,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "project_id"])
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{project_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
async def unfavorite_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    project = await resource_access.load_authorized(
        session, Tool.project, project_id, current_user, guild_context
    )
    await session.exec(
        delete(ProjectFavorite).where(
            ProjectFavorite.user_id == current_user.id,
            ProjectFavorite.project_id == project.id,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/activity", response_model=ProjectActivityResponse)
async def project_activity_feed(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=20),
) -> ProjectActivityResponse:
    project = await resource_access.load_authorized(
        session, Tool.project, project_id, current_user, guild_context
    )
    on_project = and_(Task.project_id == project.id, in_thread())
    rows, total_count, actual_page = await paginated_query(
        session,
        select(Comment, Task)
        .join(Task, Comment.task_id == Task.id)
        .where(on_project)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.desc(), Comment.id.desc()),
        select(func.count())
        .select_from(Comment)
        .join(Task, Comment.task_id == Task.id)
        .where(on_project),
        page,
        page_size,
    )
    entries: list[ProjectActivityEntry] = []
    for comment, task in rows:
        author = comment.author
        author_payload = CommentAuthor.model_validate(author) if author else None
        entries.append(
            ProjectActivityEntry(
                comment_id=comment.id,
                content=comment.content,
                created_at=comment.created_at,
                author=author_payload,
                task_id=task.id,
                task_title=task.title,
            )
        )
    return ProjectActivityResponse(
        **build_paginated_response(entries, total_count, actual_page, page_size)
    )


@router.get("/{project_id}", response_model=ProjectRead)
async def read_project(
    project_id: int,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsRead,
    include_deleted: IncludeDeletedDep = False,
) -> ProjectRead:
    project = await resource_access.load_authorized(
        session, Tool.project, project_id, current_user, guild_context, hydrated=True
    )
    return await _project_read_for_user(session, guild_context.user_id, project)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> ProjectRead:
    project = await resource_access.load_authorized(
        session, Tool.project, project_id, current_user, guild_context, access="write"
    )
    update_data = project_in.model_dump(exclude_unset=True)
    # Pinning configures the project itself rather than describing it: it
    # needs a project manager, the project owner, or a guild admin, where plain
    # write access is enough for the rest of the payload.
    if "pinned" in update_data:
        permissions_service.require_project_configure(project, context=guild_context)
        pinned = update_data.pop("pinned")
        project.pinned_at = datetime.now(timezone.utc) if pinned else None

    for field, value in update_data.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)

    session.add(project)
    await attachments_service.claim_uploads(session, project)
    await session.commit()
    return await read_after_write(session, project_id, current_user, guild_context)


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_projects(
    reorder_in: ProjectReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Put the reader's own projects in the order given. Ids the reader cannot
    see are ignored, and those left out keep their place after the rest."""
    visible_ids = (
        await session.exec(
            select(Project.id).where(
                *visible_project_conditions(
                    current_user.id,
                    context=guild_context,
                    archived=None,
                    is_template=False,
                )
            )
        )
    ).all()
    existing_orders = {
        order.project_id: order
        for order in (
            await session.exec(
                select(ProjectOrder).where(
                    ProjectOrder.user_id == current_user.id,
                    ProjectOrder.project_id.in_(visible_ids),
                )
            )
        ).all()
    }
    # The order as it stands: those the reader has placed first, then the
    # rest by id.
    current_ids = sorted(
        visible_ids,
        key=lambda pid: (
            pid not in existing_orders,
            existing_orders[pid].sort_order if pid in existing_orders else 0.0,
            pid,
        ),
    )
    visible = set(visible_ids)
    final_order = list(
        dict.fromkeys(
            [pid for pid in reorder_in.project_ids if pid in visible] + current_ids
        )
    )
    if final_order != current_ids:
        for index, project_id in enumerate(final_order):
            order = existing_orders.get(project_id) or ProjectOrder(
                user_id=current_user.id, project_id=project_id
            )
            order.sort_order = float(index)
            session.add(order)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def read_after_write(
    session: RLSSessionDep,
    project_id: int,
    user: Optional[User],
    guild_context: ActorContext,
) -> ProjectRead:
    """The project a write answers with: re-read after the commit, serialized.

    Registered in ``tool_lists.TOOL_LISTS`` so the shared sharing route
    (``tool_grants.py``) answers in this tool's own shape.
    """
    project = await _get_project_or_404(
        project_id,
        session,
        guild_context.guild_id,
        user_id=guild_context.user_id,
        populate_existing=True,
    )
    return await _project_read_for_user(session, guild_context.user_id, project)
