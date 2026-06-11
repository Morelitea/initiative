"""`GET /api/v1/recents` — mixed-type recent items for the header tabs bar.

Returns the most recently viewed entities (projects, documents, queues,
counter groups) across all four types, ordered by ``last_viewed_at``
descending, capped at ``MAX_RECENT_VIEWS``. Each row is enriched with the
underlying entity's name and icon-relevant fields so the frontend can
render a tab without an additional fetch.

RLS scopes ``recent_views`` to the active guild already. Per-entity
permission filters drop rows the user has since lost access to.
"""

from __future__ import annotations

from typing import Annotated, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.models.counter import CounterGroup
from app.models.document import Document
from app.models.initiative import Initiative
from app.models.queue import Queue
from app.models.project import Project
from app.models.user import User
from app.schemas.recent_view import RecentItemRead
from app.services import counters as counters_service
from app.services import permissions as permissions_service
from app.services import queues as queues_service
from app.services import recent_views as recent_views_service
from app.services import rls as rls_service


router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


@router.get("/", response_model=List[RecentItemRead])
async def list_recents(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> List[RecentItemRead]:
    rows = await recent_views_service.list_recent_views(
        session,
        user_id=current_user.id,
    )
    if not rows:
        return []

    # Guild admins bypass DAC on detail pages — mirror that here so a row the
    # admin successfully recorded a view for isn't silently dropped during
    # enrichment.
    is_guild_admin = rls_service.is_guild_admin(guild_context.role)

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

    items: List[RecentItemRead] = []
    for row in rows:
        if row.entity_type == "project":
            project = project_map.get(row.entity_id)
            if project is None or project.guild_id is None:
                continue
            try:
                permissions_service.require_project_access(
                    project, current_user, access="read"
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
                    document, current_user, access="read"
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
