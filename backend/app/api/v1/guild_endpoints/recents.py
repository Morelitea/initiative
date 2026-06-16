"""`/api/v1/recents` — mixed-type recent items for the header tabs bar.

The tabs bar is special-cased by design (guild-context design doc §3.5a): it
renders entities from ANY of the user's guilds regardless of the current
context, but only their render metadata (name/icon/type) — never their
content. So the list runs under USER context and gathers each member guild's
``recent_views`` from its own schema, enriches + permission-filters inside
that guild's routed context, and merges by ``last_viewed_at``. Opening a tab
navigates into the entity's guild (which sets the server-held context) before
any content is fetched.

Closing a tab is the one cross-guild write: a guild-ADDRESSED delete
(``?guild_id=``, validated like any context) of the caller's own row.
"""

from __future__ import annotations

from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    UserSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.models.counter import CounterGroup
from app.models.document import Document
from app.models.guild import GuildMembership, GuildRole
from app.models.initiative import Initiative
from app.models.queue import Queue
from app.models.project import Project
from app.models.recent_view import RecentView
from app.models.user import User
from app.schemas.recent_view import RecentItemRead
from app.services import counters as counters_service
from app.services import permissions as permissions_service
from app.services import queues as queues_service
from app.services import recent_views as recent_views_service
from app.services import rls as rls_service
from app.services.cross_guild import gather_across_guilds
from app.services.recent_views import RecentEntityType


router = APIRouter()
# Guild-scoped sub-router: closing a tab (the delete) is the one guild-scoped
# recents operation and mounts under /g/{guild_id}/recents. The cross-guild
# tabs-bar list stays on the top-level router above — fully separate endpoints.
guild_router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _enrich_recent_rows(
    session,
    current_user: User,
    rows: List[RecentView],
    *,
    is_guild_admin: bool,
) -> List[RecentItemRead]:
    """Resolve one guild's recent_views rows into render-only tab items.

    Must run inside that guild's routed context (relationships and ids are
    per-schema). Per-entity permission filters drop rows the user has since
    lost access to; ``is_guild_admin`` mirrors the detail pages' DAC bypass so
    an admin's recorded views aren't silently dropped.
    """
    ids_by_type = recent_views_service.group_ids_by_type(rows)

    project_map: Dict[int, Project] = {}
    if project_ids := ids_by_type.get("project"):
        stmt = (
            select(Project)
            .where(Project.id.in_(project_ids))
            .options(
                selectinload(Project.permissions),
                selectinload(Project.role_permissions),
                selectinload(Project.initiative).selectinload(Initiative.memberships),
            )
        )
        result = await session.exec(stmt)
        project_map = {p.id: p for p in result.all()}

    document_map: Dict[int, Document] = {}
    if document_ids := ids_by_type.get("document"):
        stmt = (
            select(Document)
            .where(Document.id.in_(document_ids))
            .options(
                selectinload(Document.permissions),
                selectinload(Document.role_permissions),
                selectinload(Document.initiative).selectinload(Initiative.memberships),
            )
        )
        result = await session.exec(stmt)
        document_map = {d.id: d for d in result.all()}

    queue_map: Dict[int, Queue] = {}
    if queue_ids := ids_by_type.get("queue"):
        stmt = (
            select(Queue)
            .where(Queue.id.in_(queue_ids))
            .options(
                selectinload(Queue.permissions),
                selectinload(Queue.role_permissions),
                selectinload(Queue.initiative).selectinload(Initiative.memberships),
            )
        )
        result = await session.exec(stmt)
        queue_map = {q.id: q for q in result.all()}

    counter_group_map: Dict[int, CounterGroup] = {}
    if cg_ids := ids_by_type.get("counter_group"):
        stmt = (
            select(CounterGroup)
            .where(CounterGroup.id.in_(cg_ids))
            .options(
                selectinload(CounterGroup.permissions),
                selectinload(CounterGroup.role_permissions),
                selectinload(CounterGroup.initiative).selectinload(
                    Initiative.memberships
                ),
            )
        )
        result = await session.exec(stmt)
        counter_group_map = {g.id: g for g in result.all()}

    guild_role = GuildRole.admin if is_guild_admin else None

    items: List[RecentItemRead] = []
    for row in rows:
        if row.entity_type == "project":
            project = project_map.get(row.entity_id)
            if project is None or project.guild_id is None:
                continue
            try:
                permissions_service.require_project_access(
                    project, current_user, access="read", guild_role=guild_role
                )
            except HTTPException:
                # Permission denied / not found — drop the row from the bar
                # but let any other error bubble up so latent bugs are visible.
                continue
            items.append(
                # ``model_construct`` skips the SanitizedBaseModel validator
                # so trusted DB columns (already sanitized on input) aren't
                # double-escaped on the way out — e.g. ``Foo & Bar`` would
                # otherwise round-trip as ``Foo &amp; Bar``.
                RecentItemRead.model_construct(
                    entity_type="project",
                    entity_id=project.id,
                    guild_id=project.guild_id,
                    name=project.name,
                    last_viewed_at=row.last_viewed_at,
                    icon=project.icon,
                )
            )
        elif row.entity_type == "document":
            document = document_map.get(row.entity_id)
            if document is None or document.guild_id is None:
                continue
            try:
                permissions_service.require_document_access(
                    document, current_user, access="read", guild_role=guild_role
                )
            except HTTPException:
                # Permission denied / not found — drop the row from the bar
                # but let any other error bubble up so latent bugs are visible.
                continue
            items.append(
                RecentItemRead.model_construct(
                    entity_type="document",
                    entity_id=document.id,
                    guild_id=document.guild_id,
                    name=document.title,
                    last_viewed_at=row.last_viewed_at,
                    document_type=(
                        document.document_type.value
                        if document.document_type is not None
                        else None
                    ),
                    mime_type=document.file_content_type,
                    original_filename=document.original_filename,
                )
            )
        elif row.entity_type == "queue":
            queue = queue_map.get(row.entity_id)
            if queue is None:
                continue
            if not is_guild_admin:
                try:
                    queues_service.require_queue_access(
                        queue, current_user, access="read"
                    )
                except HTTPException:
                    # Permission denied — drop the row but let unexpected
                    # errors bubble up.
                    continue
            items.append(
                RecentItemRead.model_construct(
                    entity_type="queue",
                    entity_id=queue.id,
                    guild_id=queue.guild_id,
                    name=queue.name,
                    last_viewed_at=row.last_viewed_at,
                )
            )
        elif row.entity_type == "counter_group":
            group = counter_group_map.get(row.entity_id)
            if group is None:
                continue
            if not is_guild_admin:
                try:
                    counters_service.require_counter_group_access(
                        group, current_user, access="read"
                    )
                except HTTPException:
                    # Permission denied — drop the row but let unexpected
                    # errors bubble up.
                    continue
            items.append(
                RecentItemRead.model_construct(
                    entity_type="counter_group",
                    entity_id=group.id,
                    guild_id=group.guild_id,
                    name=group.name,
                    last_viewed_at=row.last_viewed_at,
                )
            )

    return items


@router.get("/", response_model=List[RecentItemRead])
async def list_recents(
    session: UserSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> List[RecentItemRead]:
    """Recent tabs across every guild the user belongs to (names only).

    Works identically with a guild context or in personal mode: the result
    depends only on who is asking, never on what they're currently viewing.
    """
    # Guild roles from the shared memberships table (user context shows the
    # caller's own rows) so each guild's enrichment can apply the admin DAC
    # bypass its detail pages would.
    memberships = (
        await session.exec(
            select(GuildMembership).where(GuildMembership.user_id == current_user.id)
        )
    ).all()
    role_by_guild = {m.guild_id: m.role for m in memberships}

    async def _fetch(guild_session, guild_id: int) -> List[RecentItemRead]:  # type: ignore[no-untyped-def]
        rows = await recent_views_service.list_recent_views(
            guild_session, user_id=current_user.id
        )
        if not rows:
            return []
        role = role_by_guild.get(guild_id)
        return await _enrich_recent_rows(
            guild_session,
            current_user,
            list(rows),
            is_guild_admin=role is not None and rls_service.is_guild_admin(role),
        )

    items = await gather_across_guilds(
        session, current_user.id, list(role_by_guild.keys()), _fetch
    )
    items.sort(key=lambda item: item.last_viewed_at, reverse=True)
    return items[: recent_views_service.MAX_RECENT_VIEWS]


@guild_router.delete(
    "/{entity_type}/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_recent(
    entity_type: RecentEntityType,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Close a tab: delete the caller's own recent-view row.

    Guild-scoped — mounted under /g/{guild_id}/recents because a tab can belong
    to any of the user's guilds and per-schema ids are only unique within a
    guild. Idempotent.
    """
    del guild_context  # validation + routing happen in the dependency
    await recent_views_service.clear_view(
        session,
        user_id=current_user.id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
