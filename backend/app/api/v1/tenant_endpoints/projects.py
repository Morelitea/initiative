from datetime import datetime, timezone
from typing import Annotated, List, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, func
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import selectinload, undefer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.relationships import (
    Related,
    RelationshipType,
)
from app.core.search import SearchEntityType
from app.services.permissions import Action
from app.services.tenant import attachments as attachments_service
from app.services.tenant import relationships
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    RLSSessionDep,
    SessionDep,
    app_scope,
    get_current_active_user,
    GuildContextDep,
)
from app.models.tenant.project import (
    Project,
)
from app.models.tenant.resource_grant import (
    ResourceGrant,
    ResourceAccessLevel,
)
from app.models.tenant.project_order import ProjectOrder
from app.models.tenant.project_activity import ProjectFavorite
from app.models.tenant.recent_view import RecentView
from app.models.tenant.task import (
    Task,
    TaskStatus,
    TaskStatusCategory,
)
from app.models.tenant.comment import Comment, in_thread
from app.models.tenant.initiative import Initiative
from app.models.platform.user import User
from app.models.tenant.document import Document
from app.api import resource_access, tool_copy
from app.core.tools import Tool
from app.db.query import build_paginated_response, paginated_query
from app.db.session import require_actor_context, require_guild_context
from app.services import notifications as notifications_service
from app.services.tenant import ownership as ownership_service
from app.services import permissions as permissions_service
from app.services import reachability
from app.services.tenant import named_people
from app.services.tenant import properties as properties_service
from app.services.tenant import tags as tags_service
from app.services.tenant import archive as archive_service
from app.services.tenant import tool_listing
from app.services.tenant import filter_presets as filter_presets_service
from app.services.tenant import task_statuses as task_statuses_service
from app.core.messages import ProjectMessages
from app.schemas.tenant.project import (
    ProjectCan,
    ProjectCreate,
    ProjectRead,
    ProjectTaskSummary,
    ProjectReorderRequest,
    ProjectUpdate,
    ProjectFavoriteStatus,
    ProjectActivityEntry,
    ProjectActivityResponse,
)
from app.schemas.tenant.task_status import TaskStatusRead
from app.schemas.platform.user import UserPublic
from app.schemas.tenant.comment import CommentAuthor
from app.schemas.tenant.initiative import (
    InitiativeSummary,
)
from app.schemas.tenant.document import (
    ProjectDocumentSummary,
    serialize_project_document_link,
)
from app.services.tenant import project_grants
from app.schemas.tenant.property import annotated_properties
from app.schemas.tenant.tag import annotated_tags

router = APIRouter(route_class=ActorRoute)

#: The routes an installed app may call, under the projects scopes.
ProjectsRead = Annotated[ActorContext, Depends(app_scope("projects:read"))]
ProjectsWrite = Annotated[ActorContext, Depends(app_scope("projects:write"))]


async def _documents_for_projects(
    session: AsyncSession, projects: Sequence[Project]
) -> dict[int, list[Related]]:
    """Attached documents for a whole page of projects, in two queries."""
    return await relationships.related_for_many(
        session,
        SearchEntityType.project,
        [p.id for p in projects if p.id is not None],
        relationship_type=RelationshipType.attached,
        other_kind=SearchEntityType.document,
        model=Document,
    )


def _project_documents(
    attached: Sequence[Related],
) -> List[ProjectDocumentSummary]:
    """Serialize a project's attached documents.

    No sharing check here. The edge row carries the document's own gate 4 —
    ``relationships`` asks ``resource_access`` of BOTH ends — so a document this
    reader holds no grant on never arrives, and the entity query behind
    ``Related`` passes the documents' policies a second time. Restating it here
    would be a rule said twice, which can only agree or drift.
    """
    documents: List[ProjectDocumentSummary] = []
    for link in attached:
        summary = serialize_project_document_link(link)
        if summary:
            documents.append(summary)
    documents.sort(key=lambda item: (item.name.lower(), item.document_id))
    return documents


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
        setattr(project, "_task_summary", summary)


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
            "projects",
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
    linked documents with their DAC, tags, grants). The slim one carries only
    what the level and the owner need — the grants and the level itself —
    since the slim projection drops the owner, documents, tags and the
    initiative.
    """
    if slim:
        return [
            selectinload(Project.grants),
            selectinload(Project.initiative),
            undefer(Project.actions),
        ]
    return [
        selectinload(Project.grants).options(
            selectinload(ResourceGrant.role), selectinload(ResourceGrant.user)
        ),
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
    documents.
    """
    conditions = tool_listing.base_conditions(
        Tool.project,
        Project,
        Initiative.projects_enabled,
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


async def _visible_projects(session: SessionDep, current_user: User) -> List[Project]:
    """The live, non-template projects the user's sharing reaches."""
    conditions = visible_project_conditions(
        current_user.id,
        context=require_guild_context(session),
        archived=None,
        is_template=False,
    )
    base_statement = select(Project).where(*conditions).options(*project_load_options())
    result = await session.exec(base_statement)
    return list(result.all())


async def _project_reads_with_order(
    session: SessionDep,
    user_id: int | None,
    projects: List[Project],
    *,
    preserve_order: bool = False,
) -> List[ProjectRead]:
    """``ProjectRead`` for each project, with the reader's own order,
    favourites and last visits. An installed app (``user_id`` ``None``) keeps
    none of those."""
    if not projects:
        return []

    project_ids = [project.id for project in projects if project.id is not None]

    await _attach_task_summaries(session, projects)
    await tags_service.annotate_tags(session, projects)
    await properties_service.annotate_properties(session, projects)
    await ownership_service.annotate_owner_apps(session, projects)
    order_map: dict[int, float] = {}
    favorite_ids: set[int] = set()
    view_map: dict[int, datetime] = {}
    if user_id is not None:
        order_map, favorite_ids, view_map = await _project_metadata_for_user(
            session,
            user_id,
            project_ids,
        )

    sorted_projects = (
        projects if preserve_order else _in_reader_order(projects, order_map)
    )

    attached = await _documents_for_projects(session, sorted_projects)
    context = require_actor_context(session)
    payloads: List[ProjectRead] = []
    for project in sorted_projects:
        payloads.append(
            _build_project_payload(
                project,
                context=context,
                sort_order=order_map.get(project.id),
                favorite_ids=favorite_ids,
                view_map=view_map,
                user_id=user_id,
                attached_documents=attached.get(project.id, []),
            )
        )
    return payloads


def _project_can(
    project: Project, user_id: int | None, *, context: ActorContext
) -> ProjectCan:
    """What the reader may do to the project, configuring it included."""
    return ProjectCan(
        **permissions_service.client_access(project, user_id, context=context),
        configure=permissions_service.allows(project, Action.configure),
    )


def _slim_project_reads(
    projects: List[Project], user_id: int | None, *, context: ActorContext
) -> List[ProjectRead]:
    """Build lightweight ``ProjectRead`` rows for the slim projection.

    Carries only ``{id, name, icon, initiative_id, can}`` plus
    the cheap scalar flags and who owns it (``owner_id``, or ``owner_app`` as
    the caller annotated it); documents/grants/tags/the owner's profile/nested
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
                can=_project_can(project, user_id, context=context),
            ).model_copy(
                # Set after construction: the field's alias keeps
                # ``model_validate`` off the ORM row.
                update={"owner_app": ownership_service.owner_app_of(project)}
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

    The order is already settled in SQL, so it is preserved rather than
    re-derived. The slim projection is a plain per-row build with no follow-up
    queries — that is what makes it slim.
    """
    if slim:
        await ownership_service.annotate_owner_apps(session, projects)
        return _slim_project_reads(
            projects, user_id, context=require_actor_context(session)
        )
    return await _project_reads_with_order(
        session, user_id, projects, preserve_order=True
    )


def _in_reader_order(
    projects: List[Project], order_map: dict[int, float]
) -> List[Project]:
    """The projects in the reader's own order: those they have placed first,
    then the rest by id."""

    def sort_key(project: Project) -> tuple[bool, float, int]:
        order_value = order_map.get(project.id)
        return (
            order_value is None,
            float(order_value) if order_value is not None else 0.0,
            project.id or 0,
        )

    return sorted(projects, key=sort_key)


async def _project_metadata_for_user(
    session: SessionDep,
    user_id: int,
    project_ids: List[int],
) -> tuple[dict[int, float], set[int], dict[int, datetime]]:
    """The reader's own sort orders, favorites and last visits for these
    projects, as ``(order_map, favorite_ids, view_map)``."""
    orders = await session.exec(
        select(ProjectOrder.project_id, ProjectOrder.sort_order).where(
            ProjectOrder.user_id == user_id,
            ProjectOrder.project_id.in_(project_ids),
        )
    )
    favorites = await session.exec(
        select(ProjectFavorite.project_id).where(
            ProjectFavorite.user_id == user_id,
            ProjectFavorite.project_id.in_(project_ids),
        )
    )
    views = await session.exec(
        select(RecentView.entity_id, RecentView.last_viewed_at).where(
            RecentView.user_id == user_id,
            RecentView.entity_type == "project",
            RecentView.entity_id.in_(project_ids),
        )
    )
    return dict(orders.all()), set(favorites.all()), dict(views.all())


def _project_task_statuses(project: Project) -> List[TaskStatusRead]:
    """Serialize the project's task statuses (ordered by position).

    Returns an empty list when the relationship wasn't eager-loaded — the slim
    and list projections don't load it, so this must never trigger a lazy load
    on the async session (which would raise). Detail reads load it via
    ``_get_project_or_404``.
    """
    if "task_statuses" in sa_inspect(project).unloaded:
        return []
    statuses = sorted(project.task_statuses, key=lambda s: (s.position, s.id or 0))
    return [TaskStatusRead.model_validate(status) for status in statuses]


def _project_owner(project: Project) -> Optional[UserPublic]:
    """The user holding the project's owner grant, or None when it is unowned.

    Read off the eagerly-loaded grants rather than a column on the project:
    ``resource_grants`` is where ownership is recorded, so there is nothing to
    keep in step.
    """
    for grant in project.grants or []:
        if (
            grant.user_id is not None
            and grant.level == ResourceAccessLevel.owner
            and grant.user is not None
        ):
            return UserPublic.model_validate(grant.user)
    return None


def _build_project_payload(
    project: Project,
    *,
    context: ActorContext,
    sort_order: Optional[float],
    favorite_ids: set[int],
    view_map: dict[int, datetime],
    user_id: int | None = None,
    attached_documents: Sequence[Related] = (),
) -> ProjectRead:
    payload = ProjectRead.model_validate(project)
    if project.initiative:
        payload.initiative = InitiativeSummary.model_validate(project.initiative)
    project_id = project.id or 0
    summary = getattr(project, "_task_summary", None)
    if not isinstance(summary, ProjectTaskSummary):
        summary = ProjectTaskSummary()
    return payload.model_copy(
        update={
            "community_id": context.guild_id,
            "sort_order": sort_order,
            "is_favorited": project_id in favorite_ids,
            "last_viewed_at": view_map.get(project_id),
            "documents": _project_documents(attached_documents),
            "task_summary": summary,
            "task_statuses": _project_task_statuses(project),
            "tags": annotated_tags(project),
            "properties": annotated_properties(project),
            "grants": permissions_service.serialize_grants(project, context=context),
            "can": _project_can(project, user_id, context=context),
            "owner_id": ownership_service.owner_user_id_of(project),
            "owner": _project_owner(project),
            "owner_app": ownership_service.owner_app_of(project),
        }
    )


async def _set_favorite_state(
    session: SessionDep,
    *,
    user_id: int,
    project_id: int,
    favorited: bool,
) -> bool:
    stmt = select(ProjectFavorite).where(
        ProjectFavorite.user_id == user_id,
        ProjectFavorite.project_id == project_id,
    )
    result = await session.exec(stmt)
    record = result.one_or_none()
    if favorited:
        if record is None:
            session.add(ProjectFavorite(user_id=user_id, project_id=project_id))
            await session.commit()
        return True

    if record:
        await session.delete(record)
        await session.commit()
    return False


async def _project_read_for_user(
    session: SessionDep,
    user_id: int | None,
    project: Project,
) -> ProjectRead:
    payloads = await _project_reads_with_order(session, user_id, [project])
    return payloads[0]


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: ProjectsWrite,
) -> ProjectRead:
    resource_access.refuse_app_sharing(guild_context, project_in, "grants")
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
        # Sharing before anything that hangs off it: a status or a preset is
        # reached through the project, so the project has to be reachable first.
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
        await filter_presets_service.ensure_default_presets(session, project.id)
        await attachments_service.claim_uploads(session, project)
    await properties_service.write_on_create(session, project, project_in.properties)
    settled = named_people.Governing.of(Tool.project, project)
    await session.commit()
    if project_in.template_id is not None:
        # As for any copy: those the new project's sharing does not reach are
        # let go of its tasks once that sharing is committed.
        await named_people.sweep(session, settled)
        await session.commit()
    project_id = settled.resource_id

    project = await _get_project_or_404(
        project_id, session, guild_context.guild_id, user_id=guild_context.user_id
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
        .where(ProjectFavorite.user_id == current_user.id)
        .order_by(ProjectFavorite.created_at.desc())
        .options(*project_load_options(slim=True))
    )
    readable: List[Project] = []
    for project in favorites.all():
        try:
            resource_access.authorize(
                Tool.project, project, current_user, context=guild_context
            )
        except HTTPException:
            continue
        readable.append(project)
    reads = await serialize_project_page(session, current_user.id, readable, slim=True)
    # Every row here is a favorite, so the flag is known without a lookup.
    return [read.model_copy(update={"is_favorited": True}) for read in reads]


@router.post("/{project_id}/favorite", response_model=ProjectFavoriteStatus)
async def favorite_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFavoriteStatus:
    project = await resource_access.load_authorized(
        session, Tool.project, project_id, current_user, guild_context
    )
    await _set_favorite_state(
        session, user_id=current_user.id, project_id=project.id, favorited=True
    )
    return ProjectFavoriteStatus(project_id=project.id, is_favorited=True)


@router.delete("/{project_id}/favorite", response_model=ProjectFavoriteStatus)
async def unfavorite_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFavoriteStatus:
    project = await resource_access.load_authorized(
        session, Tool.project, project_id, current_user, guild_context
    )
    await _set_favorite_state(
        session, user_id=current_user.id, project_id=project.id, favorited=False
    )
    return ProjectFavoriteStatus(project_id=project.id, is_favorited=False)


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
    # Fields that configure the project itself rather than describe it: they
    # need a project manager, the project owner, or a guild admin, where plain
    # write access is enough for the rest of the payload.
    sentinel = object()
    pinned_value = update_data.pop("pinned", sentinel)
    view_mode_value = update_data.pop("default_view_mode", sentinel)
    if pinned_value is not sentinel or view_mode_value is not sentinel:
        if not permissions_service.allows(project, Action.configure):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    ProjectMessages.PIN_PERMISSION_REQUIRED
                    if view_mode_value is sentinel
                    else ProjectMessages.CONFIGURE_REQUIRED
                ),
            )
    if pinned_value is not sentinel:
        project.pinned_at = datetime.now(timezone.utc) if bool(pinned_value) else None
    if view_mode_value is not sentinel:
        project.default_view_mode = view_mode_value

    for field, value in update_data.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)

    session.add(project)
    await attachments_service.claim_uploads(session, project)
    await session.commit()
    project = await _get_project_or_404(
        project.id,
        session,
        guild_context.guild_id,
        user_id=guild_context.user_id,
        populate_existing=True,
    )
    return await _project_read_for_user(session, guild_context.user_id, project)


@router.post("/reorder", response_model=List[ProjectRead])
async def reorder_projects(
    reorder_in: ProjectReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    visible_projects = await _visible_projects(session, current_user)
    if not visible_projects:
        return []

    # The order as it stands, from the order rows alone: the projects are
    # serialized once, after the write.
    existing_orders = {
        order.project_id: order
        for order in (
            await session.exec(
                select(ProjectOrder).where(
                    ProjectOrder.user_id == current_user.id,
                    ProjectOrder.project_id.in_(
                        [project.id for project in visible_projects]
                    ),
                )
            )
        ).all()
    }
    current_ids = [
        project.id
        for project in _in_reader_order(
            visible_projects,
            {pid: order.sort_order for pid, order in existing_orders.items()},
        )
        if project.id is not None
    ]

    valid_ids = set(current_ids)
    seen: set[int] = set()
    requested_ids: List[int] = []
    for project_id in reorder_in.project_ids:
        if project_id in valid_ids and project_id not in seen:
            seen.add(project_id)
            requested_ids.append(project_id)

    final_order: List[int] = requested_ids[:]
    for project_id in current_ids:
        if project_id not in seen:
            seen.add(project_id)
            final_order.append(project_id)

    if final_order != current_ids:
        for index, project_id in enumerate(final_order):
            sort_value = float(index)
            order = existing_orders.get(project_id)
            if order:
                order.sort_order = sort_value
            else:
                order = ProjectOrder(
                    user_id=current_user.id,
                    project_id=project_id,
                    sort_order=sort_value,
                )
            session.add(order)
        await session.commit()
    return await _project_reads_with_order(
        session,
        current_user.id,
        visible_projects,
    )


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
        project_id, session, guild_context.guild_id, user_id=guild_context.user_id
    )
    return await _project_read_for_user(session, guild_context.user_id, project)
