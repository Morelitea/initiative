"""Trash-can endpoints: list / restore / immediate-purge.

Guild routes operate on the guild in the ``/c/{guild_id}`` path; the
cross-guild ``/me/trash`` view (see ``me_trash.py``) spans the user's guilds. The list
endpoint uses 9 separate per-entity queries merged in Python rather than a
literal SQL UNION ALL — pragmatic and easier to filter; the spec calls out
moving to a polymorphic trash index later if it gets slow.

Cascade dedup: children whose parent was cascaded-trashed at the same
``deleted_at`` (over the same edges the cascade walks) are filtered out so the trash table doesn't list 200 tasks
under a deleted project — just the project. Restoring the parent
resurfaces the children automatically (see ``soft_delete.py``).
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import aliased
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    require_guild_roles,
    GuildContextDep,
)
from app.core.audit_events import AuditEventType
from app.core.messages import TrashMessages
from app.core.tools import TRASH_TARGETS, plural_of
from app.db.soft_delete_filter import SOFT_DELETE_MODELS, select_including_deleted
from app.models.tenant.comment import Comment
from app.models.platform.guild import GuildRole
from app.models.platform.user import User
from app.models.platform.user_profile_view import MemberProfile
from app.schemas.tenant.trash import (
    EntityType,
    RestoreResponse,
    TrashItem,
    TrashListResponse,
)
from app.services import audit as audit_service
from app.services.platform import guilds as guilds_service
from app.services.tenant import ownership as ownership_service
from app.core.user_display import display_name
from app.services.tenant import attachments as attachments_service
from app.services.tenant import content_references
from app.services.tenant.lifecycle_tree import CASCADE_PARENTS
from app.services.tenant.soft_delete import (
    hard_purge_entity,
    restore_entity,
)


router = APIRouter()


#: Wire name -> (model, the column that labels its rows). A target's table is
#: its own plural and its label is the model's ``display_field``, so neither is
#: written down here; a target with no soft-deletable model behind it fails at
#: import rather than at request time.
_BY_TABLE = {model.__tablename__: model for model in SOFT_DELETE_MODELS}
ENTITY_REGISTRY: dict[str, tuple[type[SQLModel], str]] = {
    target: (
        _BY_TABLE[plural_of(target)],
        _BY_TABLE[plural_of(target)].display_field(),
    )
    for target in TRASH_TARGETS
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
    user = await session.get(MemberProfile, user_id)
    if user is None:
        display = f"Deleted user #{user_id}"
    else:
        # Mirror frontend getUserDisplayName: anonymized rows have wiped PII,
        # so we surface the id rather than the empty/synthetic name fields.
        if getattr(user.status, "value", str(user.status)) == "anonymized":
            display = f"Deleted user #{user_id}"
        else:
            display = display_name(user) or f"User #{user_id}"
    cache[user_id] = display
    return display


async def _list_trashed_for_model(
    session: AsyncSession,
    model: type[SQLModel],
    *,
    only_deleted_by: Optional[int],
) -> list[SQLModel]:
    stmt = select_including_deleted(model).where(model.deleted_at.is_not(None))
    if only_deleted_by is not None:
        stmt = stmt.where(model.deleted_by == only_deleted_by)

    # Cascade dedup: exclude children whose parent (any of them) is also
    # trashed at the same deleted_at — they come back with it, and one of them
    # restored alone would sit under a parent that is still in the bin. Alias the parent — required when the
    # parent is the same table as the child (Comment threaded replies via
    # parent_comment_id), otherwise unaliased ``Comment.id == Comment.parent_comment_id``
    # references the same row in both clauses.
    for parent_model, fk_col in CASCADE_PARENTS.get(model, []):
        fk = getattr(model, fk_col)
        parent_alias = aliased(parent_model)
        sub = (
            select_including_deleted(parent_alias)
            .where(parent_alias.id == fk)
            .where(parent_alias.deleted_at == model.deleted_at)
        )
        stmt = stmt.where(~sub.exists())

    result = await session.exec(stmt)
    return list(result.all())


async def _collect_trash_items(
    session: AsyncSession,
    guild_id: int,
    *,
    only_deleted_by: Optional[int],
    name_cache: Optional[dict[Optional[int], str]] = None,
) -> list[TrashItem]:
    """Gather one guild's trashed entities as TrashItems.

    ``only_deleted_by`` filters to a single user's deletions (the personal
    view); ``None`` returns everything in the guild (the admin view). The
    ``name_cache`` is shared by the cross-guild aggregate so a user who appears
    in several guilds is only resolved once.
    """
    if name_cache is None:
        name_cache = {}
    items: list[TrashItem] = []
    for entity_type, (model, name_field) in ENTITY_REGISTRY.items():
        rows = await _list_trashed_for_model(
            session,
            model,
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
                    guild_id=guild_id,
                    name=name,
                    deleted_at=row.deleted_at,
                    deleted_by_id=row.deleted_by,
                    deleted_by_display=display,
                    purge_at=row.purge_at,
                )
            )
    return items


@router.get("/", response_model=TrashListResponse)
async def list_guild_trash(
    session: RLSSessionDep,
    guild_context: Annotated[
        GuildContext, Depends(require_guild_roles(GuildRole.admin))
    ],
) -> TrashListResponse:
    """Everything in the active guild's trash (guild-admin only).

    This is the guild settings trash view. Members use the user-scoped
    ``GET /me/trash`` for their own deletions; they never reach this endpoint.
    """
    items = await _collect_trash_items(
        session, guild_context.guild_id, only_deleted_by=None
    )
    items.sort(key=lambda i: i.deleted_at, reverse=True)
    retention_days = await guilds_service.get_guild_retention_days(session)
    return TrashListResponse(
        items=items, total=len(items), retention_days=retention_days
    )


async def _load_trash_entity(
    session: AsyncSession,
    *,
    entity_type: EntityType,
    entity_id: int,
    for_update: bool = False,
) -> SQLModel:
    """Load a trashed entity (404 unless it's in this guild's trash and still
    soft-deleted).

    ``for_update`` takes a row lock so the ``deleted_at`` check and a follow-up
    hard delete are atomic against a concurrent restore: under READ COMMITTED a
    restore that commits between the SELECT and the DELETE would otherwise be
    visible, and the PK delete would permanently remove a now-live row. With the
    lock, a racing restore serializes — either it commits first and this returns
    404 (deleted_at is NULL), or it blocks on the lock until the purge commits and
    the row is gone.
    """
    spec = ENTITY_REGISTRY.get(entity_type)
    if spec is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=TrashMessages.UNKNOWN_ENTITY_TYPE,
        )
    model, _ = spec
    stmt = select_including_deleted(model).where(model.id == entity_id)
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.exec(stmt)
    entity = result.one_or_none()
    if entity is None or entity.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TrashMessages.NOT_FOUND
        )
    return entity


@router.post(
    "/{entity_type}/{entity_id}/restore",
    status_code=status.HTTP_200_OK,
    response_model=RestoreResponse,
)
async def restore_trash_entity(
    entity_type: EntityType,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
):
    """Restore a trashed entity."""
    entity = await _load_trash_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
    )

    # Permission: regular users can only restore their own deletions.
    if (
        not guild_context.is_admin
        and getattr(entity, "deleted_by", None) != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TrashMessages.PURGE_REQUIRES_ADMIN,
        )

    await restore_entity(session, entity)

    # A comment back in the conversation puts back what it alone pointed at.
    if isinstance(entity, Comment):
        await content_references.sync_for_comment(
            session, entity, author_id=current_user.id
        )

    # Quality-of-life: a tool trashed before its owner left comes back unowned.
    # If whoever wrote it is still in the guild, give it back to them. If not,
    # it stays unowned — there is nobody obvious to pick, so nothing is guessed.
    await ownership_service.restore_ownership_to_author(
        session, row=entity, guild_id=guild_context.guild_id
    )

    await session.commit()
    return RestoreResponse(restored=True)


@router.delete(
    "/{entity_type}/{entity_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def purge_trash_entity(
    entity_type: EntityType,
    entity_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Response:
    """Hard-purge a trashed entity. Guild-admin only, fully guild-scoped.

    Runs entirely on the routed guild-admin RLS session — no standing-BYPASSRLS
    ``app_admin`` connection. The guild-schema content tables carry PERMISSIVE
    ``initiative_member_delete`` policies that defer to ``initiative_access``,
    whose community-admin leg (``app.guild_admin = 'true'``) admits the routed
    admin for the hard delete, so the guild role itself does it.
    ``_load_trash_entity`` 404s unless the entity is in THIS guild's trash (and
    still soft-deleted) — that is the authorization boundary — and
    ``for_update=True`` locks the row so a concurrent restore can't slip in
    between the ``deleted_at`` check and the delete (which would otherwise
    permanently remove a just-restored live row).
    """
    if not guild_context.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=TrashMessages.PURGE_REQUIRES_ADMIN,
        )

    entity = await _load_trash_entity(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        for_update=True,
    )
    released = await hard_purge_entity(session, entity)
    await audit_service.record(
        session,
        event_type=AuditEventType.TRASH_PURGED,
        actor_user_id=current_user.id,
        guild_id=guild_context.guild_id,
        target_type=entity_type.value,
        target_id=entity_id,
        detail={"via": "admin"},
    )
    await session.commit()
    attachments_service.delete_blobs(guild_context.guild_id, released)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
