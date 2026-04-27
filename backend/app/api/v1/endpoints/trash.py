"""Trash-can endpoints: list / restore / immediate-purge.

All routes operate on the active guild (from ``X-Guild-ID``). The list
endpoint uses 9 separate per-entity queries merged in Python rather than a
literal SQL UNION ALL — pragmatic and easier to filter; the spec calls out
moving to a polymorphic trash index later if it gets slow.

Cascade dedup: children whose parent was cascaded-trashed at the same
``deleted_at`` are filtered out so the trash table doesn't list 200 tasks
under a deleted project — just the project. Restoring the parent
resurfaces the children automatically (see ``soft_delete.py``).
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.messages import TrashMessages
from app.db.session import get_admin_session
from app.db.soft_delete_filter import select_including_deleted
from app.models.calendar_event import CalendarEvent
from app.models.comment import Comment
from app.models.document import Document
from app.models.guild import GuildRole
from app.models.initiative import Initiative
from app.models.project import Project
from app.models.queue import Queue, QueueItem
from app.models.tag import Tag
from app.models.task import Task
from app.models.user import User
from app.schemas.trash import (
    EntityType,
    RestoreNeedsReassignmentResponse,
    RestoreRequest,
    TrashItem,
    TrashListResponse,
)
from app.services import guilds as guilds_service
from app.services.soft_delete import (
    RestoreResult,
    hard_purge_entity,
    restore_entity,
)


router = APIRouter()


GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# Maps the EntityType literal we expose in the API to the SQLModel class
# and to the column whose value populates TrashItem.name.
ENTITY_REGISTRY: dict[EntityType, tuple[type[SQLModel], str]] = {
    "project": (Project, "name"),
    "task": (Task, "title"),
    "document": (Document, "title"),
    "comment": (Comment, "content"),
    "initiative": (Initiative, "name"),
    "tag": (Tag, "name"),
    "queue": (Queue, "name"),
    "queue_item": (QueueItem, "label"),
    "calendar_event": (CalendarEvent, "title"),
}


def _truncate(value: str, *, limit: int = 80) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


async def _resolve_display_name(
    session: AsyncSession,
    user_id: Optional[int],
    cache: dict[Optional[int], str],
) -> str:
    if user_id is None:
        return "Deleted user"
    if user_id in cache:
        return cache[user_id]
    user = await session.get(User, user_id)
    if user is None:
        display = f"Deleted user #{user_id}"
    else:
        # Mirror frontend getUserDisplayName: anonymized rows have wiped PII,
        # so we surface the id rather than the empty/synthetic name fields.
        if getattr(user.status, "value", str(user.status)) == "anonymized":
            display = f"Deleted user #{user_id}"
        else:
            display = user.full_name or user.email or f"User #{user_id}"
    cache[user_id] = display
    return display


# Per-child-entity dedup specs:  child_model -> [(parent_model, fk_col_on_child)]
# A child row is omitted from the trash listing if its (fk, deleted_at) matches
# any trashed (parent.id, parent.deleted_at) — i.e. it was cascaded with the
# parent and shouldn't appear independently.
_DEDUP_PARENTS: dict[type[SQLModel], list[tuple[type[SQLModel], str]]] = {
    Project: [(Initiative, "initiative_id")],
    Task: [(Project, "project_id")],
    Document: [(Initiative, "initiative_id")],
    Comment: [(Task, "task_id"), (Document, "document_id")],
    Queue: [(Initiative, "initiative_id")],
    QueueItem: [(Queue, "queue_id")],
    CalendarEvent: [(Initiative, "initiative_id")],
}


async def _list_trashed_for_model(
    session: AsyncSession,
    model: type[SQLModel],
    *,
    guild_id: int,
    only_deleted_by: Optional[int],
) -> list[SQLModel]:
    stmt = (
        select_including_deleted(model)
        .where(model.deleted_at.is_not(None))
        .where(model.guild_id == guild_id)
    )
    if only_deleted_by is not None:
        stmt = stmt.where(model.deleted_by == only_deleted_by)

    # Cascade dedup: exclude children whose parent (any of them) is also
    # trashed at the same deleted_at.
    for parent_model, fk_col in _DEDUP_PARENTS.get(model, []):
        fk = getattr(model, fk_col)
        sub = (
            select_including_deleted(parent_model.id)
            .where(parent_model.id == fk)
            .where(parent_model.deleted_at == model.deleted_at)
        )
        stmt = stmt.where(~sub.exists())

    result = await session.exec(stmt)
    return list(result.all())


@router.get("/", response_model=TrashListResponse)
async def list_trash(
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    scope: Literal["mine", "guild"] = "mine",
) -> TrashListResponse:
    """List trashed entities for the active guild.

    ``scope=mine`` returns only items deleted by the current user (the only
    scope a non-admin can request). ``scope=guild`` returns everything in
    the guild's trash and is admin-only.
    """
    if scope == "guild" and guild_context.role != GuildRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TrashMessages.PURGE_REQUIRES_ADMIN)

    only_deleted_by = current_user.id if scope == "mine" else None
    name_cache: dict[Optional[int], str] = {}

    items: list[TrashItem] = []
    for entity_type, (model, name_field) in ENTITY_REGISTRY.items():
        rows = await _list_trashed_for_model(
            session,
            model,
            guild_id=guild_context.guild_id,
            only_deleted_by=only_deleted_by,
        )
        for row in rows:
            raw_name = getattr(row, name_field) or ""
            name = _truncate(str(raw_name))
            display = await _resolve_display_name(session, row.deleted_by, name_cache)
            items.append(
                TrashItem(
                    entity_type=entity_type,
                    entity_id=row.id,
                    name=name,
                    deleted_at=row.deleted_at,
                    deleted_by_id=row.deleted_by,
                    deleted_by_display=display,
                    purge_at=row.purge_at,
                )
            )

    items.sort(key=lambda i: i.deleted_at, reverse=True)
    retention_days = await guilds_service.get_guild_retention_days(session, guild_context.guild_id)
    return TrashListResponse(items=items, total=len(items), retention_days=retention_days)


async def _load_trash_entity(
    session: AsyncSession,
    *,
    entity_type: EntityType,
    entity_id: int,
    guild_id: int,
) -> SQLModel:
    spec = ENTITY_REGISTRY.get(entity_type)
    if spec is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TrashMessages.UNKNOWN_ENTITY_TYPE)
    model, _ = spec
    stmt = (
        select_including_deleted(model)
        .where(model.id == entity_id)
        .where(model.guild_id == guild_id)
    )
    result = await session.exec(stmt)
    entity = result.one_or_none()
    if entity is None or entity.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TrashMessages.NOT_FOUND)
    return entity


@router.post(
    "/{entity_type}/{entity_id}/restore",
    status_code=status.HTTP_200_OK,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": RestoreNeedsReassignmentResponse,
            "description": "The entity's recorded owner is no longer an active member of the relevant initiative; client must resubmit with a new_owner_id from valid_owner_ids.",
        },
    },
)
async def restore_trash_entity(
    entity_type: EntityType,
    entity_id: int,
    payload: RestoreRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
):
    """Restore a trashed entity. Returns 409 with the valid_owner_ids list
    when the entity's recorded owner has since left the relevant initiative
    and the caller did not supply a new_owner_id."""
    entity = await _load_trash_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        guild_id=guild_context.guild_id,
    )

    # Permission: regular users can only restore their own deletions.
    if guild_context.role != GuildRole.admin and getattr(entity, "deleted_by", None) != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TrashMessages.PURGE_REQUIRES_ADMIN)

    try:
        result: RestoreResult = await restore_entity(
            session,
            entity,
            new_owner_id=payload.new_owner_id,
        )
    except ValueError as exc:
        if str(exc) == "TRASH_INVALID_OWNER":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TrashMessages.INVALID_OWNER)
        raise

    if result.needs_reassignment:
        # 409 — client opens picker seeded with valid_owner_ids and resubmits.
        # Returned as JSONResponse so the status code overrides the route's
        # default 200; the response_model on the route still describes the
        # body shape via the responses={} mapping above.
        payload_body = RestoreNeedsReassignmentResponse(
            valid_owner_ids=result.valid_owner_ids or []
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=payload_body.model_dump(),
        )

    await session.commit()
    return {"restored": True}


@router.delete("/{entity_type}/{entity_id}/purge", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def purge_trash_entity(
    entity_type: EntityType,
    entity_id: int,
    session: RLSSessionDep,
    admin_session: Annotated[AsyncSession, Depends(get_admin_session)],
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Hard-purge a trashed entity. Admin-only. Runs the actual DELETE on an
    AdminSessionDep so the RESTRICTIVE FOR DELETE policy passes (BYPASSRLS
    role) and so the upload-cleanup helper can DELETE Upload rows."""
    if guild_context.role != GuildRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=TrashMessages.PURGE_REQUIRES_ADMIN)

    # Look up the entity via the user's RLS session first so we get a 404 if
    # the entity isn't actually in this guild's trash. Then re-resolve it on
    # the admin session for the actual delete.
    entity = await _load_trash_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        guild_id=guild_context.guild_id,
    )
    spec = ENTITY_REGISTRY[entity_type]
    model, _ = spec
    admin_stmt = select_including_deleted(model).where(model.id == entity.id)
    admin_result = await admin_session.exec(admin_stmt)
    admin_entity = admin_result.one_or_none()
    if admin_entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=TrashMessages.NOT_FOUND)

    await hard_purge_entity(admin_session, admin_entity)
    await admin_session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
