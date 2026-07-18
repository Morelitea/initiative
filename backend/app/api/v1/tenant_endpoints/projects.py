from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    RLSSessionDep,
    SessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
    GuildContext,
    require_guild_roles,
)
from app.services.cross_guild import gather_across_guilds, member_guild_ids
from app.models.tenant.project import (
    Project,
)
from app.models.tenant.resource_grant import ResourceGrant, ResourceAccessLevel
from app.models.tenant.project_order import ProjectOrder
from app.models.tenant.project_activity import ProjectFavorite
from app.models.tenant.recent_view import RecentView
from app.models.tenant.task import (
    Task,
    TaskAssignee,
    TaskStatus,
    TaskStatusCategory,
    Subtask,
)
from app.models.tenant.comment import Comment
from app.models.tenant.initiative import (
    Initiative,
    InitiativeMember,
    InitiativeRoleModel,
    PermissionKey,
)
from app.models.platform.user import User
from app.models.platform.guild import GuildRole
from app.models.tenant.document import Document, ProjectDocument
from app.models.tenant.tag import ProjectTag
from app.api import resource_access
from app.core.tools import Tool
from app.services import notifications as notifications_service
from app.services.tenant import initiatives as initiatives_service
from app.services.tenant import documents as documents_service
from app.services import permissions as permissions_service
from app.services import rls as rls_service
from app.services.tenant import tags as tags_service
from app.services.tenant import task_statuses as task_statuses_service
from app.core.messages import ProjectMessages
from app.core.config import settings as app_settings
from app.db.query import clamp_page, page_has_next, paginate_sequence
from app.core.pam_context import has_active_grant
from app.services.realtime import broadcast_event
from app.schemas.tenant.resource_grant import ResourceGrantSchema
from app.schemas.tenant.project import (
    ProjectCreate,
    ProjectDuplicateRequest,
    ProjectListResponse,
    ProjectRead,
    ProjectTaskSummary,
    ProjectReorderRequest,
    ProjectUpdate,
    ProjectFavoriteStatus,
    ProjectActivityEntry,
    ProjectActivityResponse,
)
from app.schemas.platform.user import UserSummary, UserSummaryListResponse
from app.schemas.tenant.comment import CommentAuthor
from app.schemas.tenant.initiative import serialize_initiative
from app.schemas.tenant.document import (
    ProjectDocumentSummary,
    serialize_project_document_link,
)
from app.schemas.tenant.project_export import (
    ProjectExportEnvelope,
)
from app.services.tenant import project_export as project_export_service
from app.services.tenant import recent_views as recent_views_service
from app.schemas.tenant.recent_view import RecentViewWrite

router = APIRouter()
# Cross-guild "my projects" aggregate (My Projects page). Mounted under
# /api/v1/me; user-scoped, DAC-filtered across all the user's guilds.
me_router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
GuildAdminContext = Annotated[
    GuildContext, Depends(require_guild_roles(GuildRole.admin))
]

MAX_RECENT_PROJECTS = 20


def _project_documents(
    project: Project,
    *,
    user_id: int | None = None,
) -> List[ProjectDocumentSummary]:
    """Serialize project document links, filtering by DAC permission.

    Pass ``user_id`` so only documents the user can access are included.
    """
    documents: List[ProjectDocumentSummary] = []
    for link in getattr(project, "document_links", []) or []:
        doc = getattr(link, "document", None)
        if user_id is not None and doc is not None:
            # Single source of truth: the document DAC engine (per-user / per-role /
            # all-initiative-members grants, plus guild-admin, Full-access, and PAM
            # overrides) — no re-implementation here.
            if permissions_service.compute_document_permission(doc, user_id) is None:
                continue
        summary = serialize_project_document_link(link)
        if summary:
            documents.append(summary)
    documents.sort(key=lambda item: (item.title.lower(), item.document_id))
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


async def _broadcast_project(project: Project, action: str) -> None:
    """Emit a content-free project signal to the project's initiative room.

    The realtime bus carries ids only — the client refetches through the
    RLS-gated REST path, which is the authorization gate. ``guild_id`` +
    ``initiative_id`` come straight off the row so the signal lands in the right
    per-guild-schema initiative room (ids are per-schema, so both are required).
    """
    await broadcast_event(
        project.guild_id,
        project.initiative_id,
        "project",
        action,
        {"project_id": project.id},
    )


async def _get_project_or_404(
    project_id: int,
    session: SessionDep,
    guild_id: int | None = None,
    *,
    populate_existing: bool = False,
) -> Project:
    statement = (
        select(Project)
        .where(Project.id == project_id)
        .options(
            selectinload(Project.grants).selectinload(ResourceGrant.role),
            selectinload(Project.owner),
            selectinload(Project.initiative)
            .selectinload(Initiative.memberships)
            .options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                ),
            ),
            selectinload(Project.document_links)
            .selectinload(ProjectDocument.document)
            .options(
                selectinload(Document.grants).selectinload(ResourceGrant.role),
                # Linked-doc visibility defers to the shared document DAC, which
                # reads the doc's own initiative memberships (all-members grants).
                selectinload(Document.initiative).selectinload(Initiative.memberships),
            ),
            selectinload(Project.tag_links).selectinload(ProjectTag.tag),
        )
    )
    if populate_existing:
        # Refresh identity-mapped collections (tag_links etc.) after a commit —
        # expire_on_commit=False keeps the pre-write state otherwise.
        statement = statement.execution_options(populate_existing=True)
    if guild_id is not None:
        statement = statement.join(Project.initiative).where(
            Initiative.guild_id == guild_id
        )
    result = await session.exec(statement)
    project = result.one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ProjectMessages.NOT_FOUND
        )
    return project


async def _get_initiative_or_404(
    initiative_id: int, session: SessionDep, guild_id: int | None = None
) -> Initiative:
    result = await session.exec(
        select(Initiative)
        .where(Initiative.id == initiative_id)
        .options(
            selectinload(Initiative.memberships).options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                ),
            )
        )
    )
    initiative = result.one_or_none()
    if not initiative or (guild_id is not None and initiative.guild_id != guild_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ProjectMessages.INITIATIVE_NOT_FOUND,
        )
    return initiative


def _compute_my_permission_level(
    project: Project,
    user_id: int,
) -> str | None:
    """Compute the effective permission level for a user on a project."""
    return permissions_service.compute_project_permission(project, user_id)


def _membership_from_project(project: Project, user_id: int) -> InitiativeMember | None:
    initiative = getattr(project, "initiative", None)
    if not initiative:
        return None
    memberships = getattr(initiative, "memberships", None)
    if not memberships:
        return None
    for membership in memberships:
        if membership.user_id == user_id:
            return membership
    return None


async def _get_initiative_membership(
    project: Project, user: User, session: SessionDep
) -> InitiativeMember | None:
    cached = _membership_from_project(project, user.id)
    if cached:
        return cached
    if not project.initiative_id:
        return None
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == project.initiative_id,
        InitiativeMember.user_id == user.id,
    )
    result = await session.exec(stmt)
    membership = result.one_or_none()
    if membership and project.initiative:
        project.initiative.memberships.append(membership)
    return membership


async def _get_project_permission(
    project: Project, user_id: int, session: SessionDep
) -> ResourceGrant | None:
    # The user's own grant (role grants have user_id None) from the
    # eagerly-loaded list, falling back to a query if it wasn't loaded.
    for grant in getattr(project, "grants", None) or []:
        if grant.user_id == user_id:
            return grant
    stmt = select(ResourceGrant).where(
        ResourceGrant.resource_type == "project",
        ResourceGrant.resource_id == project.id,
        ResourceGrant.user_id == user_id,
    )
    result = await session.exec(stmt)
    permission = result.one_or_none()
    if permission:
        project.grants.append(permission)
    return permission


async def _ensure_user_in_initiative(
    initiative_id: int, user_id: int, session: SessionDep
) -> None:
    stmt = select(InitiativeMember).where(
        InitiativeMember.initiative_id == initiative_id,
        InitiativeMember.user_id == user_id,
    )
    result = await session.exec(stmt)
    if not result.one_or_none():
        # Get the member role for this initiative
        member_role = await initiatives_service.get_member_role(
            session, initiative_id=initiative_id
        )
        if not member_role:
            # Create roles if they don't exist (migration safety)
            _, member_role = await initiatives_service.create_builtin_roles(
                session, initiative_id=initiative_id
            )
        session.add(
            InitiativeMember(
                initiative_id=initiative_id,
                user_id=user_id,
                role_id=member_role.id,
            )
        )
        await session.flush()


def _ensure_not_archived(project: Project) -> None:
    if project.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ProjectMessages.IS_ARCHIVED
        )


async def _duplicate_template_tasks(
    session: SessionDep,
    template: Project,
    new_project: Project,
    *,
    status_mapping: dict[int, int],
    fallback_status_ids: dict[TaskStatusCategory, int],
) -> None:
    task_stmt = (
        select(Task)
        .options(
            selectinload(Task.assignees),
            selectinload(Task.task_status),
            selectinload(Task.subtasks),
            selectinload(Task.tag_links),
        )
        .where(Task.project_id == template.id)
        .order_by(Task.position.asc(), Task.id.asc())
    )
    task_result = await session.exec(task_stmt)
    template_tasks = task_result.all()
    if not template_tasks:
        return

    for template_task in template_tasks:
        template_status_id = getattr(template_task, "task_status_id", None)
        mapped_status_id = None
        if template_status_id is not None:
            mapped_status_id = status_mapping.get(template_status_id)
        if mapped_status_id is None:
            category = getattr(
                getattr(template_task, "task_status", None), "category", None
            )
            if category is not None:
                mapped_status_id = fallback_status_ids.get(category)
        if mapped_status_id is None and fallback_status_ids:
            mapped_status_id = next(iter(fallback_status_ids.values()))
        new_task = Task(
            project_id=new_project.id,
            title=template_task.title,
            description=template_task.description,
            task_status_id=mapped_status_id,
            priority=template_task.priority,
            due_date=template_task.due_date,
            position=template_task.position,
        )
        session.add(new_task)
        await session.flush()
        if template_task.assignees:
            session.add_all(
                [
                    TaskAssignee(task_id=new_task.id, user_id=assignee.id)
                    for assignee in template_task.assignees
                ]
            )
        if template_task.subtasks:
            session.add_all(
                [
                    Subtask(
                        task_id=new_task.id,
                        content=subtask.content,
                        is_completed=subtask.is_completed,
                        position=subtask.position,
                    )
                    for subtask in template_task.subtasks
                ]
            )
        await tags_service.copy_entity_tags(
            session,
            tags_service.TAG_LINKS["task"],
            source_id=template_task.id,
            target_id=new_task.id,
        )


def _matches_filters(
    project: Project, *, archived: Optional[bool], template: Optional[bool]
) -> bool:
    if template is None:
        if project.is_template:
            return False
    elif project.is_template != template:
        return False

    if archived is None:
        return not project.is_archived
    return project.is_archived == archived


async def _visible_projects(
    session: SessionDep,
    current_user: User,
    *,
    guild_id: int,
    archived: Optional[bool],
    template: Optional[bool],
) -> List[Project]:
    """Get projects visible to the user.

    DAC: Projects with explicit ProjectPermission OR role-based permission.
    """
    # A guild admin (full access to all guild data) or a live PAM grant (acts
    # like a member of every initiative) sees all of the guild's projects in one
    # bulk, guild-scoped query; otherwise narrow to projects the user has
    # explicit/role permission for. The guild scope + RLS apply either way.
    conditions = [Initiative.guild_id == guild_id]
    if not has_active_grant(
        guild_id
    ) and not permissions_service.is_request_guild_admin(guild_id):
        conditions.append(
            Project.id.in_(
                permissions_service.visible_project_ids_subquery(current_user.id)
            )
        )

    base_statement = (
        select(Project)
        .join(Project.initiative)
        .where(*conditions)
        .options(
            selectinload(Project.grants).selectinload(ResourceGrant.role),
            selectinload(Project.owner),
            selectinload(Project.initiative)
            .selectinload(Initiative.memberships)
            .options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                ),
            ),
            selectinload(Project.document_links)
            .selectinload(ProjectDocument.document)
            .options(
                selectinload(Document.grants).selectinload(ResourceGrant.role),
                # Linked-doc visibility defers to the shared document DAC, which
                # reads the doc's own initiative memberships (all-members grants).
                selectinload(Document.initiative).selectinload(Initiative.memberships),
            ),
            selectinload(Project.tag_links).selectinload(ProjectTag.tag),
        )
    )
    result = await session.exec(base_statement)
    all_projects = result.all()

    return [
        project
        for project in all_projects
        if _matches_filters(project, archived=archived, template=template)
    ]


async def _project_reads_with_order(
    session: SessionDep,
    current_user: User,
    projects: List[Project],
    *,
    preserve_order: bool = False,
) -> List[ProjectRead]:
    if not projects:
        return []

    project_ids = [project.id for project in projects if project.id is not None]

    # Fetch task summaries, sort orders, favorites, and views in parallel-ish
    # (all independent queries batched before we iterate projects)
    await _attach_task_summaries(session, projects)
    order_map, favorite_ids, view_map = await _project_metadata_for_user(
        session,
        current_user.id,
        project_ids,
    )

    if preserve_order:
        sorted_projects = projects
    else:

        def sort_key(project: Project) -> tuple[bool, float, int]:
            order_value = order_map.get(project.id)
            return (
                order_value is None,
                float(order_value) if order_value is not None else 0.0,
                project.id or 0,
            )

        sorted_projects = sorted(projects, key=sort_key)

    payloads: List[ProjectRead] = []
    for project in sorted_projects:
        my_level = _compute_my_permission_level(project, current_user.id)
        payloads.append(
            _build_project_payload(
                project,
                sort_order=order_map.get(project.id),
                favorite_ids=favorite_ids,
                view_map=view_map,
                my_permission_level=my_level,
                user_id=current_user.id,
            )
        )
    return payloads


async def _project_meta_for_user(
    session: SessionDep,
    user_id: int,
    project_ids: List[int],
) -> tuple[set[int], dict[int, datetime]]:
    if not project_ids:
        return set(), {}
    fav_stmt = select(ProjectFavorite.project_id).where(
        ProjectFavorite.user_id == user_id,
        ProjectFavorite.project_id.in_(tuple(project_ids)),
    )
    fav_result = await session.exec(fav_stmt)
    favorite_rows = fav_result.all()
    favorite_ids = {
        row if isinstance(row, int) else row[0]  # type: ignore[index]
        for row in favorite_rows
    }

    view_stmt = select(RecentView.entity_id, RecentView.last_viewed_at).where(
        RecentView.user_id == user_id,
        RecentView.entity_type == "project",
        RecentView.entity_id.in_(tuple(project_ids)),
    )
    view_result = await session.exec(view_stmt)
    view_rows = view_result.all()
    view_map: dict[int, datetime] = {}
    for row in view_rows:
        if isinstance(row, tuple):
            project_id, last_viewed_at = row
        else:
            project_id, last_viewed_at = row.entity_id, row.last_viewed_at  # type: ignore[attr-defined]
        view_map[int(project_id)] = last_viewed_at
    return favorite_ids, view_map


async def _project_metadata_for_user(
    session: SessionDep,
    user_id: int,
    project_ids: List[int],
) -> tuple[dict[int, float], set[int], dict[int, datetime]]:
    """Fetch sort orders, favorites, and recent views in a single pass.

    Combines what was previously three separate queries (ProjectOrder,
    ProjectFavorite, RecentView) into one function that issues
    them together, reducing overall latency.

    Returns (order_map, favorite_ids, view_map).
    """
    if not project_ids:
        return {}, set(), {}

    ids_tuple = tuple(project_ids)

    # Sort orders
    order_stmt = select(ProjectOrder).where(
        ProjectOrder.user_id == user_id,
        ProjectOrder.project_id.in_(ids_tuple),
    )
    order_result = await session.exec(order_stmt)
    order_map = {order.project_id: order.sort_order for order in order_result.all()}

    # Favorites + views (reuse existing helper)
    favorite_ids, view_map = await _project_meta_for_user(session, user_id, project_ids)

    return order_map, favorite_ids, view_map


async def _projects_by_ids(
    session: SessionDep,
    project_ids: List[int],
    *,
    guild_id: int,
) -> dict[int, Project]:
    if not project_ids:
        return {}
    stmt = (
        select(Project)
        .join(Project.initiative)
        .where(
            Project.id.in_(tuple(project_ids)),
            Initiative.guild_id == guild_id,
        )
        .options(
            selectinload(Project.grants).selectinload(ResourceGrant.role),
            selectinload(Project.owner),
            selectinload(Project.initiative)
            .selectinload(Initiative.memberships)
            .options(
                selectinload(InitiativeMember.user),
                selectinload(InitiativeMember.role_ref).selectinload(
                    InitiativeRoleModel.permissions
                ),
            ),
            selectinload(Project.document_links)
            .selectinload(ProjectDocument.document)
            .options(
                selectinload(Document.grants).selectinload(ResourceGrant.role),
                # Linked-doc visibility defers to the shared document DAC, which
                # reads the doc's own initiative memberships (all-members grants).
                selectinload(Document.initiative).selectinload(Initiative.memberships),
            ),
            selectinload(Project.tag_links).selectinload(ProjectTag.tag),
        )
    )
    result = await session.exec(stmt)
    projects = result.all()
    return {project.id: project for project in projects if project.id is not None}


def _build_project_payload(
    project: Project,
    *,
    sort_order: Optional[float],
    favorite_ids: set[int],
    view_map: dict[int, datetime],
    my_permission_level: str | None = None,
    user_id: int | None = None,
) -> ProjectRead:
    payload = ProjectRead.model_validate(project)
    if project.initiative:
        payload.initiative = serialize_initiative(project.initiative)
    project_id = project.id or 0
    summary = getattr(project, "_task_summary", None)
    if not isinstance(summary, ProjectTaskSummary):
        summary = ProjectTaskSummary()
    return payload.model_copy(
        update={
            "sort_order": sort_order,
            "is_favorited": project_id in favorite_ids,
            "last_viewed_at": view_map.get(project_id),
            "documents": _project_documents(project, user_id=user_id),
            "task_summary": summary,
            "tags": tags_service.tag_summaries(project.tag_links),
            "grants": permissions_service.serialize_grants(project),
            "my_permission_level": my_permission_level,
        }
    )


# Recent project views are now stored in the polymorphic ``recent_views``
# table; record/clear is delegated to ``recent_views_service``.


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
    current_user: User,
    project: Project,
) -> ProjectRead:
    payloads = await _project_reads_with_order(session, current_user, [project])
    return payloads[0]


async def _require_project_membership(
    project: Project,
    current_user: User,
    session: SessionDep,
    *,
    access: str = "read",
    require_manager: bool = False,
    manage_access: bool = False,
):
    """Authorize a project via the shared engine. ``manage_access=True`` (member/
    permission ops) additionally rejects PAM grantees — a grant never manages
    access. Loads the permission row first in case it wasn't eager-loaded."""
    await _get_project_permission(project, current_user.id, session)
    resource_access.authorize(
        Tool.project,
        project,
        current_user,
        access=access,
        require_owner=require_manager,
        manage_access=manage_access,
    )


GLOBAL_PROJECT_SORT_FIELDS = {
    "name": func.lower(Project.name),
    "updated_at": Project.updated_at,
}


def _apply_global_project_sort(
    statement, sort_by: Optional[str], sort_dir: Optional[str]
):
    col = GLOBAL_PROJECT_SORT_FIELDS.get(sort_by) if sort_by else None
    if col is not None:
        order = col.desc() if sort_dir == "desc" else col.asc()
        statement = statement.order_by(order.nulls_last(), Project.id.desc())
    else:
        statement = statement.order_by(Project.updated_at.desc(), Project.id.desc())
    return statement


def _sort_global_project_reads(
    reads: list[ProjectRead], sort_by: Optional[str], sort_dir: Optional[str]
) -> list[ProjectRead]:
    """Order the merged cross-guild reads, mirroring _apply_global_project_sort.

    ``id`` is always the (descending) tiebreak; applied as a separate stable pass
    so it holds regardless of the primary direction. Manual per-user ordering is
    intentionally not used here — its ids are per-guild, so it can't span guilds.
    """
    reads.sort(key=lambda r: r.id, reverse=True)
    if sort_by == "name":
        reads.sort(key=lambda r: (r.name or "").lower(), reverse=sort_dir == "desc")
    elif sort_by == "updated_at":
        reads.sort(key=lambda r: r.updated_at, reverse=sort_dir == "desc")
    else:
        reads.sort(key=lambda r: r.updated_at, reverse=True)
    return reads


async def _list_global_projects(
    session: SessionDep,
    current_user: User,
    *,
    guild_ids: Optional[List[int]] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
) -> tuple[list[ProjectRead], int]:
    """List projects across every guild the user belongs to.

    Visits each guild's schema in turn (per-schema ids mean a single cross-guild
    query isn't possible) and merges, filtering through the DAC
    visible-project-ids subquery for permission checks. Membership is implied by
    only iterating the user's own guilds.
    """
    target_guilds = await member_guild_ids(
        session, current_user.id, restrict_to=guild_ids
    )

    has_permission_subq = permissions_service.visible_project_ids_subquery(
        current_user.id
    )
    conditions = [
        Project.is_archived.is_(False),
        Project.is_template.is_(False),
        Project.id.in_(has_permission_subq),
    ]
    if search:
        conditions.append(func.lower(Project.name).contains(search.strip().lower()))

    async def _fetch(guild_session: AsyncSession, _guild_id: int) -> list[ProjectRead]:
        statement = (
            select(Project)
            .where(*conditions)
            .options(
                selectinload(Project.grants).selectinload(ResourceGrant.role),
                selectinload(Project.owner),
                selectinload(Project.initiative)
                .selectinload(Initiative.memberships)
                .options(
                    selectinload(InitiativeMember.user),
                    selectinload(InitiativeMember.role_ref).selectinload(
                        InitiativeRoleModel.permissions
                    ),
                ),
                selectinload(Project.document_links)
                .selectinload(ProjectDocument.document)
                .options(
                    selectinload(Document.grants).selectinload(ResourceGrant.role),
                    # Linked-doc visibility defers to the shared document DAC, which
                    # reads the doc's own initiative memberships (all-members grants).
                    selectinload(Document.initiative).selectinload(
                        Initiative.memberships
                    ),
                ),
                selectinload(Project.tag_links).selectinload(ProjectTag.tag),
            )
        )
        projects = list((await guild_session.exec(statement)).all())
        # Convert inside the guild's routed context (relationships resolve in its
        # schema); preserve order — the merged list is sorted below.
        return await _project_reads_with_order(
            guild_session, current_user, projects, preserve_order=True
        )

    reads = await gather_across_guilds(session, current_user.id, target_guilds, _fetch)
    reads = _sort_global_project_reads(reads, sort_by, sort_dir)
    return paginate_sequence(reads, page, page_size), len(reads)


@router.get("/", response_model=ProjectListResponse)
async def list_projects(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    archived: Optional[bool] = Query(default=None),
    template: Optional[bool] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=0, ge=0, le=100),
) -> ProjectListResponse:
    projects = await _visible_projects(
        session,
        current_user,
        guild_id=guild_context.guild_id,
        archived=archived,
        template=template,
    )
    all_reads = await _project_reads_with_order(
        session,
        current_user,
        projects,
    )
    total_count = len(all_reads)
    # page_size<=0 serves FETCH_ALL_WINDOW-sized pages (bounded response,
    # SEC-14) that honor ``page`` — has_next tells the caller to keep walking.
    items = paginate_sequence(all_reads, page, page_size)
    has_next = page_has_next(page, page_size, total_count)
    return ProjectListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.get("/writable", response_model=List[ProjectRead])
async def list_writable_projects(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    projects = await _visible_projects(
        session,
        current_user,
        guild_id=guild_context.guild_id,
        archived=None,
        template=None,
    )
    writable_projects = [
        project
        for project in projects
        if permissions_service.has_project_write_access(project, current_user)
    ]
    return await _project_reads_with_order(
        session,
        current_user,
        writable_projects,
    )


@me_router.get("/projects", response_model=ProjectListResponse)
async def list_my_projects(
    # No guild context: this aggregate routes per member guild itself.
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_ids: Optional[List[int]] = Query(default=None),
    search: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sort_by: Optional[str] = Query(default=None),
    sort_dir: Optional[str] = Query(default=None),
) -> ProjectListResponse:
    """List projects across all guilds the current user belongs to.

    Returns a paginated list filtered by DAC permissions, excluding
    archived and template projects. Supports optional guild and
    name-search filters.
    """
    project_reads, total_count = await _list_global_projects(
        session,
        current_user,
        guild_ids=guild_ids,
        search=search,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return ProjectListResponse(
        items=project_reads,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=page_has_next(page, page_size, total_count),
    )


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    template_project: Project | None = None
    if project_in.template_id is not None:
        template_project = await _get_project_or_404(
            project_in.template_id, session, guild_context.guild_id
        )
        if not template_project.is_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ProjectMessages.INVALID_TEMPLATE,
            )
        await _require_project_membership(
            template_project,
            current_user,
            session,
            access="read",
        )

    owner_id = project_in.owner_id or current_user.id
    icon_value = (
        project_in.icon
        if project_in.icon is not None
        else (template_project.icon if template_project else None)
    )
    description_value = (
        project_in.description
        if project_in.description is not None
        else (template_project.description if template_project else None)
    )
    initiative_id = (
        project_in.initiative_id
        if getattr(project_in, "initiative_id", None) is not None
        else (template_project.initiative_id if template_project else None)
    )
    if initiative_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ProjectMessages.INITIATIVE_REQUIRED,
        )
    await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
    if not rls_service.is_guild_admin(guild_context.role):
        has_perm = await rls_service.check_initiative_permission(
            session,
            initiative_id=initiative_id,
            user=current_user,
            permission_key=PermissionKey.create_projects,
        )
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ProjectMessages.CREATE_PERMISSION_REQUIRED,
            )
    await _ensure_user_in_initiative(initiative_id, owner_id, session)
    project = Project(
        name=project_in.name,
        icon=icon_value,
        description=description_value,
        owner_id=owner_id,
        initiative_id=initiative_id,
        is_template=project_in.is_template,
        guild_id=guild_context.guild_id,
    )

    session.add(project)
    await session.flush()

    status_mapping: dict[int, int] = {}
    if template_project:
        status_mapping = await task_statuses_service.clone_statuses(
            session,
            source_project_id=template_project.id,
            target_project_id=project.id,
        )

    statuses = await task_statuses_service.ensure_default_statuses(session, project.id)
    fallback_status_ids = {status.category: status.id for status in statuses}

    owner_permission = ResourceGrant(
        resource_type="project",
        resource_id=project.id,
        user_id=owner_id,
        role_id=None,
        level=ResourceAccessLevel.owner,
        guild_id=guild_context.guild_id,
        initiative_id=project.initiative_id,
    )
    session.add(owner_permission)

    # Apply the initial sharing exactly the way edits do — one grant list, one
    # code path (defaults to Viewer for all members, set on ProjectCreate.grants).
    await permissions_service.replace_resource_grants(
        session,
        resource_type="project",
        resource_id=project.id,
        guild_id=guild_context.guild_id,
        initiative_id=project.initiative_id,
        owner_id=owner_id,
        grants=project_in.grants,
    )

    if template_project:
        await _duplicate_template_tasks(
            session,
            template_project,
            project,
            status_mapping=status_mapping,
            fallback_status_ids=fallback_status_ids,
        )
        # Copy tags from template project (active only)
        await tags_service.copy_entity_tags(
            session,
            tags_service.TOOL_TAG_LINKS[Tool.project],
            source_id=template_project.id,
            target_id=project.id,
        )

    await session.commit()

    project = await _get_project_or_404(project.id, session, guild_context.guild_id)
    if project.initiative_id and project.initiative:
        # Notify every member the project is shared with, derived from the grants:
        # all members, members of a granted role, or a directly granted user.
        share_all = any(g.all_initiative_members for g in project_in.grants)
        granted_roles = {g.role_id for g in project_in.grants if g.role_id is not None}
        granted_users = {g.user_id for g in project_in.grants if g.user_id is not None}
        for membership in project.initiative.memberships:
            member = membership.user
            if not member or member.id == current_user.id:
                continue
            if not (
                share_all
                or membership.role_id in granted_roles
                or membership.user_id in granted_users
            ):
                continue
            await notifications_service.notify_project_added(
                session,
                member,
                initiative_name=project.initiative.name,
                project_name=project.name,
                project_id=project.id,
                initiative_id=project.initiative.id,
                guild_id=guild_context.guild_id,
            )
    await _attach_task_summaries(session, [project])
    await _broadcast_project(project, "created")
    return await _project_read_for_user(
        session,
        current_user,
        project,
    )


@router.post("/{project_id}/archive", response_model=ProjectRead)
async def archive_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
    )
    if not project.is_archived:
        project.is_archived = True
        project.archived_at = datetime.now(timezone.utc)
        session.add(project)
        await session.commit()
    updated = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated])
    await _broadcast_project(updated, "updated")
    return await _project_read_for_user(
        session,
        current_user,
        updated,
    )


@router.post(
    "/{project_id}/duplicate",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_project(
    project_id: int,
    duplicate_in: ProjectDuplicateRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    source_project = await _get_project_or_404(
        project_id, session, guild_context.guild_id
    )
    await _require_project_membership(
        source_project,
        current_user,
        session,
        access="write",
    )

    owner_id = current_user.id
    initiative_id = source_project.initiative_id
    if initiative_id is not None:
        await _get_initiative_or_404(initiative_id, session, guild_context.guild_id)
        await _ensure_user_in_initiative(initiative_id, owner_id, session)

    new_name = (
        duplicate_in.name.strip()
        if duplicate_in.name and duplicate_in.name.strip()
        else f"{source_project.name} copy"
    )
    new_project = Project(
        name=new_name,
        icon=source_project.icon,
        description=source_project.description,
        owner_id=owner_id,
        initiative_id=initiative_id,
        is_template=False,
        guild_id=guild_context.guild_id,
    )

    session.add(new_project)
    await session.flush()

    session.add(
        ResourceGrant(
            resource_type="project",
            resource_id=new_project.id,
            user_id=owner_id,
            role_id=None,
            level=ResourceAccessLevel.owner,
            guild_id=guild_context.guild_id,
            initiative_id=new_project.initiative_id,
        )
    )

    # Add read permissions for all initiative members (except owner)
    if source_project.initiative:
        for membership in source_project.initiative.memberships:
            if membership.user_id != owner_id and membership.user:
                read_permission = ResourceGrant(
                    resource_type="project",
                    resource_id=new_project.id,
                    user_id=membership.user_id,
                    role_id=None,
                    level=ResourceAccessLevel.read,
                    guild_id=guild_context.guild_id,
                    initiative_id=new_project.initiative_id,
                )
                session.add(read_permission)

    # Copy tags from source project (active only)
    await tags_service.copy_entity_tags(
        session,
        tags_service.TOOL_TAG_LINKS[Tool.project],
        source_id=source_project.id,
        target_id=new_project.id,
    )

    # Clone task statuses from source project to new project
    status_mapping = await task_statuses_service.clone_statuses(
        session,
        source_project_id=source_project.id,
        target_project_id=new_project.id,
    )

    # Ensure default statuses exist and create fallback mapping
    statuses = await task_statuses_service.ensure_default_statuses(
        session, new_project.id
    )
    fallback_status_ids = {status.category: status.id for status in statuses}

    await _duplicate_template_tasks(
        session,
        source_project,
        new_project,
        status_mapping=status_mapping,
        fallback_status_ids=fallback_status_ids,
    )
    await session.commit()

    new_project = await _get_project_or_404(
        new_project.id, session, guild_context.guild_id
    )
    if new_project.initiative_id and new_project.initiative:
        for membership in new_project.initiative.memberships:
            member = membership.user
            if not member or member.id == current_user.id:
                continue
            await notifications_service.notify_project_added(
                session,
                member,
                initiative_name=new_project.initiative.name,
                project_name=new_project.name,
                project_id=new_project.id,
                initiative_id=new_project.initiative.id,
                guild_id=guild_context.guild_id,
            )
    await _attach_task_summaries(session, [new_project])
    await _broadcast_project(new_project, "created")
    return await _project_read_for_user(
        session,
        current_user,
        new_project,
    )


@router.post("/{project_id}/unarchive", response_model=ProjectRead)
async def unarchive_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
    )
    if project.is_archived:
        project.is_archived = False
        project.archived_at = None
        session.add(project)
        await session.commit()
    updated = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [updated])
    await _broadcast_project(updated, "updated")
    return await _project_read_for_user(
        session,
        current_user,
        updated,
    )


# Note: ``GET /projects/recent`` has been removed. The polymorphic
# ``GET /api/v1/recents`` endpoint replaces it for the layout tabs bar.


@router.get("/favorites", response_model=List[ProjectRead])
async def favorite_projects(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    stmt = (
        select(ProjectFavorite)
        .where(ProjectFavorite.user_id == current_user.id)
        .order_by(ProjectFavorite.created_at.desc())
    )
    result = await session.exec(stmt)
    favorites = result.all()
    if not favorites:
        return []
    project_ids = [favorite.project_id for favorite in favorites]
    project_map = await _projects_by_ids(
        session, project_ids, guild_id=guild_context.guild_id
    )
    favorite_ids, view_map = await _project_meta_for_user(
        session, current_user.id, project_ids
    )

    payloads: List[ProjectRead] = []
    for favorite in favorites:
        project = project_map.get(favorite.project_id)
        if not project:
            continue
        try:
            await _require_project_membership(
                project,
                current_user,
                session,
                access="read",
            )
        except HTTPException:
            continue
        payloads.append(
            _build_project_payload(
                project,
                sort_order=None,
                favorite_ids=favorite_ids,
                view_map=view_map,
                my_permission_level=_compute_my_permission_level(
                    project,
                    current_user.id,
                ),
                user_id=current_user.id,
            )
        )
    return payloads


@router.post("/{project_id}/view", response_model=RecentViewWrite)
async def record_project_view(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> RecentViewWrite:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
    )
    record = await recent_views_service.record_view(
        session,
        user_id=current_user.id,
        entity_type="project",
        entity_id=project.id,
        persist=not guild_context.is_pam,
        limit=current_user.recent_tabs_limit,
    )
    return RecentViewWrite(
        entity_type="project",
        entity_id=project.id,
        last_viewed_at=record.last_viewed_at,
    )


@router.delete("/{project_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def clear_project_view(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
    )
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type="project",
        entity_id=project.id,
    )


@router.post("/{project_id}/favorite", response_model=ProjectFavoriteStatus)
async def favorite_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFavoriteStatus:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
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
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
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
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
    )
    offset = (page - 1) * page_size
    stmt = (
        select(Comment, Task)
        .join(Task, Comment.task_id == Task.id)
        .where(Task.project_id == project.id)
        .options(selectinload(Comment.author))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(page_size + 1)
        .offset(offset)
    )
    result = await session.exec(stmt)
    rows = result.all()
    has_next = len(rows) > page_size
    entries: list[ProjectActivityEntry] = []
    for comment, task in rows[:page_size]:
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
    next_page = page + 1 if has_next else None
    return ProjectActivityResponse(items=entries, next_page=next_page)


@router.get("/{project_id}", response_model=ProjectRead)
async def read_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="read",
    )
    return await _project_read_for_user(
        session,
        current_user,
        project,
    )


@router.get("/{project_id}/members/search", response_model=UserSummaryListResponse)
async def search_project_members(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    search: Optional[str] = Query(
        default=None,
        description="Case-insensitive substring match on the member's name.",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=0, le=100),
) -> UserSummaryListResponse:
    """Slim, searchable roster of users assignable to this project's tasks.

    The assignable set is the project's **write/owner DAC set** — explicit
    per-user grants, members holding a write-access role, and every member
    when an all-initiative-members write grant exists — computed server-side
    via the shared permission engine. This replaces the client-side
    ``project.grants`` derivation the pickers used to run over the full guild
    roster. Requester needs read access to the project.
    """
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(project, current_user, session, access="read")

    # Candidate pool = the initiative's members. User-level grants are validated
    # to reference initiative members when written (see replace_resource_grants),
    # so the membership list is a complete superset of the assignable users.
    members = getattr(project.initiative, "memberships", None) or []
    assignable: list[User] = []
    seen: set[int] = set()
    for member in members:
        user = member.user
        if user is None or user.id in seen:
            continue
        if permissions_service.has_project_write_access(project, user):
            assignable.append(user)
            seen.add(user.id)

    term = (search or "").strip().lower()
    if term:
        assignable = [u for u in assignable if term in (u.full_name or "").lower()]

    assignable.sort(key=lambda u: ((u.full_name or "").lower(), u.id))

    total_count = len(assignable)
    actual_page = clamp_page(page, page_size, total_count)
    page_items = paginate_sequence(assignable, actual_page, page_size)

    return UserSummaryListResponse(
        items=[UserSummary.model_validate(user) for user in page_items],
        total_count=total_count,
        page=actual_page,
        page_size=page_size,
        has_next=page_has_next(actual_page, page_size, total_count),
        has_prev=actual_page > 1,
    )


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: int,
    project_in: ProjectUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
    )
    _ensure_not_archived(project)

    update_data = project_in.model_dump(exclude_unset=True)
    pinned_sentinel = object()
    pinned_value = update_data.pop("pinned", pinned_sentinel)
    if pinned_value is not pinned_sentinel:
        # Only guild admins and initiative managers can pin/unpin projects
        can_pin = rls_service.is_guild_admin(guild_context.role)
        if not can_pin and project.initiative_id:
            can_pin = await rls_service.is_initiative_manager(
                session,
                initiative_id=project.initiative_id,
                user=current_user,
            )
        if not can_pin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ProjectMessages.PIN_PERMISSION_REQUIRED,
            )
        project.pinned_at = datetime.now(timezone.utc) if bool(pinned_value) else None

    for field, value in update_data.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)

    session.add(project)
    await session.commit()
    project = await _get_project_or_404(project.id, session, guild_context.guild_id)
    await _attach_task_summaries(session, [project])
    await _broadcast_project(project, "updated")
    return await _project_read_for_user(
        session,
        current_user,
        project,
    )


@router.post("/{project_id}/documents/{document_id}", response_model=ProjectRead)
async def attach_project_document(
    project_id: int,
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
    )
    _ensure_not_archived(project)
    document = await documents_service.get_document(
        session,
        document_id=document_id,
        guild_id=guild_context.guild_id,
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ProjectMessages.DOCUMENT_NOT_FOUND,
        )
    if document.initiative_id != project.initiative_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ProjectMessages.DOCUMENT_WRONG_INITIATIVE,
        )
    await documents_service.attach_document_to_project(
        session,
        document=document,
        project=project,
        user_id=current_user.id,
    )
    updated_project = await _get_project_or_404(
        project_id, session, guild_context.guild_id
    )
    await _attach_task_summaries(session, [updated_project])
    await _broadcast_project(updated_project, "updated")
    return await _project_read_for_user(
        session,
        current_user,
        updated_project,
    )


@router.delete("/{project_id}/documents/{document_id}", response_model=ProjectRead)
async def detach_project_document(
    project_id: int,
    document_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
    )
    _ensure_not_archived(project)
    document = await documents_service.get_document(
        session,
        document_id=document_id,
        guild_id=guild_context.guild_id,
    )
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ProjectMessages.DOCUMENT_NOT_FOUND,
        )
    if document.initiative_id != project.initiative_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ProjectMessages.DOCUMENT_WRONG_INITIATIVE,
        )
    await documents_service.detach_document_from_project(
        session,
        document_id=document.id,
        project_id=project.id,
    )
    updated_project = await _get_project_or_404(
        project_id, session, guild_context.guild_id
    )
    await _attach_task_summaries(session, [updated_project])
    await _broadcast_project(updated_project, "updated")
    return await _project_read_for_user(
        session,
        current_user,
        updated_project,
    )


@router.post("/reorder", response_model=List[ProjectRead])
async def reorder_projects(
    reorder_in: ProjectReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[ProjectRead]:
    visible_projects = await _visible_projects(
        session,
        current_user,
        guild_id=guild_context.guild_id,
        archived=None,
        template=None,
    )
    if not visible_projects:
        return []

    current_payloads = await _project_reads_with_order(
        session, current_user, visible_projects
    )
    current_ids = [project.id for project in current_payloads if project.id is not None]
    if not current_ids:
        return current_payloads

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

    if final_order == current_ids or not final_order:
        return current_payloads

    order_stmt = select(ProjectOrder).where(
        ProjectOrder.user_id == current_user.id,
        ProjectOrder.project_id.in_(tuple(final_order)),
    )
    existing_orders_result = await session.exec(order_stmt)
    existing_orders = {
        order.project_id: order for order in existing_orders_result.all()
    }

    for index, project_id in enumerate(final_order):
        sort_value = float(index)
        order = existing_orders.get(project_id)
        if order:
            order.sort_order = sort_value
        else:
            order = ProjectOrder(
                user_id=current_user.id, project_id=project_id, sort_order=sort_value
            )
        session.add(order)

    await session.commit()
    return await _project_reads_with_order(
        session,
        current_user,
        visible_projects,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a project. Tasks are stamped with the same deleted_at so
    they're hidden behind the parent. Restoring the project resurfaces all
    descendants automatically."""
    from app.services.platform import guilds as guilds_service
    from app.services.tenant.soft_delete import soft_delete_entity

    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    await _require_project_membership(
        project,
        current_user,
        session,
        access="write",
        require_manager=True,
    )
    retention_days = await guilds_service.get_guild_retention_days(
        session, guild_context.guild_id
    )
    await soft_delete_entity(
        session,
        project,
        deleted_by_user_id=current_user.id,
        retention_days=retention_days,
    )
    await session.commit()
    await _broadcast_project(project, "deleted")


@router.put("/{project_id}/grants", response_model=ProjectRead)
async def set_project_grants(
    project_id: int,
    grants: list[ResourceGrantSchema],
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectRead:
    """Replace the project's entire sharing state in one call — the body is the
    full list of grants (all-initiative-members / per-user / per-role). Every
    non-owner grant is rebuilt from it; the owner is always preserved.

    Anyone the new grants drop below write access is unassigned from the project's
    tasks (you can't be assigned to tasks you can't edit).
    """
    # One shared flow (load + authorize manage-access + archived guard + rebuild
    # grants + unassign anyone dropped below write). Then reload the full graph for
    # the response.
    await resource_access.set_resource_grants(
        session, Tool.project, project_id, current_user, guild_context, grants
    )
    project = await _get_project_or_404(project_id, session, guild_context.guild_id)
    return await _project_read_for_user(session, current_user, project)


# ── Export / Import ──────────────────────────────────────────────


async def count_project_export_rows(
    session,
    current_user: User,
    guild_id: int,
    *,
    project_id: int,
    access: str = "write",
) -> int:
    """The project-export adapter's pre-render signal: enforce the export
    access rule (write on the project — read-only members can't take
    standalone backups; the initiative/guild aggregate export passes
    ``access="read"``, its deliberate relaxation), then return the task count
    as the size proxy for inline-vs-job selection."""
    project = await _get_project_or_404(project_id, session, guild_id)
    await _require_project_membership(project, current_user, session, access=access)
    return (
        await session.exec(
            select(func.count()).select_from(Task).where(Task.project_id == project.id)
        )
    ).one()


async def build_project_export_for_user(
    session,
    current_user: User,
    guild_id: int,
    *,
    project_id: int,
    access: str = "write",
) -> ProjectExportEnvelope:
    """The project-export adapter's build seam: the same access rule and
    envelope as the retired ``GET /{project_id}/export`` route. Cross-row
    references (tags, statuses, properties, assignees) are encoded by string
    keys (name / email) so the file imports cleanly on another instance.
    The initiative/guild aggregate export passes ``access="read"`` — its
    deliberate relaxation; standalone exports keep write."""
    project = await _get_project_or_404(project_id, session, guild_id)
    await _require_project_membership(project, current_user, session, access=access)
    return await project_export_service.build_project_export(
        session,
        project_id=project.id,
        exported_by_email=current_user.email,
        source_instance_url=app_settings.APP_URL,
    )


# POST /projects/import was replaced by the import engine's
# POST /imports/envelope (the envelope's `type` field selects the importer;
# projects still apply through services/tenant/project_import.py).
