from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, update as sa_update
from sqlmodel import select

from app.api import resource_access
from app.api.actor_route import ActorRoute
from app.api.deps import (
    ActorContext,
    ActorSessionDep,
    ActorUserDep,
    IncludeDeletedDep,
    GuildContext,
    RLSSessionDep,
    SessionDep,
    app_scope,
    get_current_active_user,
    get_guild_membership,
)
from app.core.app_scopes import tool_resource
from app.core.messages import AppMessages, TagMessages
from app.core.tools import Tool
from app.db.guild_standing import InstallContext
from app.db.initiative_rls import governing_path
from app.models.tenant.tag import Tag
from app.models.platform.user import User
from app.services import permissions as permissions_service
from app.services.tenant import tags as tags_service
from app.services.tenant.soft_delete import trash
from app.schemas.tenant.search import SearchHit
from app.schemas.tenant.tag import (
    TagBulkEditRequest,
    TagBulkEditResponse,
    TagCreate,
    TagRead,
    serialize_tag,
    TagUpdate,
    TaggedEntitiesResponse,
)

# The tag dictionary is a guild-wide folksonomy BY DESIGN: every guild member
# (initiative membership not required) may list, create, rename, recolor, and
# trash tags, so the only gate here is guild membership. Hard purge alone is
# admin-gated (the RESTRICTIVE RLS policy on ``tags``). Pinned by
# ``test_any_guild_member_can_manage_the_tag_dictionary``.
router = APIRouter(route_class=ActorRoute)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]
#: The routes an installed app may call, under the tags scopes.
TagsRead = Annotated[ActorContext, Depends(app_scope("tags:read"))]
TagsWrite = Annotated[ActorContext, Depends(app_scope("tags:write"))]


def _governing(
    spec: tags_service.TagLinkSpec,
) -> tuple[Tool, tuple[tuple[str, str], ...]]:
    """The tool whose sharing governs a taggable kind, and the join chain from
    the kind's table to it — ``()`` where the row is the tool itself. Read from
    the registry the kind's RLS policy is rendered from."""
    governed = governing_path(str(spec.entity.__tablename__))
    if governed is None:  # pragma: no cover - every tag target has a tool
        raise RuntimeError(f"no single tool governs {spec.entity.__tablename__!r}")
    return governed


def _require_install_tagging_scopes(actor: ActorContext, target: str) -> None:
    """Raise 403 unless an installed app's standing also holds what tagging
    ``target`` writes beside the tag: the write scope of the tool that governs
    the tagged thing, and ``relationships:write`` for the assignment itself,
    which is stored as a relationship. A person passes."""
    if not isinstance(actor, InstallContext):
        return
    tool, _chain = _governing(tags_service.TAG_LINKS[target])
    needed = ["relationships:write", f"{tool_resource(tool).value}:write"]
    if not all(actor.holds(scope) for scope in needed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AppMessages.SCOPE_REQUIRED,
        )


async def _get_tag_or_404(session: SessionDep, tag_id: int, guild_id: int) -> Tag:
    """Fetch a tag by ID, ensuring it belongs to the specified guild."""
    stmt = select(Tag).where(Tag.id == tag_id)
    result = await session.exec(stmt)
    tag = result.one_or_none()
    if tag is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=TagMessages.NOT_FOUND
        )
    return tag


async def _check_duplicate_name(
    session: SessionDep,
    guild_id: int,
    name: str,
    exclude_tag_id: int | None = None,
) -> None:
    """Check for case-insensitive duplicate tag name within guild."""
    stmt = select(Tag).where(
        func.lower(Tag.name) == name.lower().strip(),
    )
    if exclude_tag_id is not None:
        stmt = stmt.where(Tag.id != exclude_tag_id)
    result = await session.exec(stmt)
    if result.one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=TagMessages.NAME_ALREADY_EXISTS,
        )


@router.get("/", response_model=List[TagRead])
async def list_tags(
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: TagsRead,
) -> list[TagRead]:
    """List all tags in the current guild."""
    stmt = select(Tag).order_by(Tag.name.asc())
    result = await session.exec(stmt)
    return [serialize_tag(tag, guild_id=guild_context.guild_id) for tag in result.all()]


@router.post("/", response_model=TagRead, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag_in: TagCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TagRead:
    """Create a new tag in the current guild."""
    await _check_duplicate_name(session, guild_context.guild_id, tag_in.name)

    tag = Tag(
        name=tag_in.name.strip(),
        color=tag_in.color,
    )
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return serialize_tag(tag, guild_id=guild_context.guild_id)


@router.post("/bulk", response_model=TagBulkEditResponse)
async def bulk_edit_tags(
    payload: TagBulkEditRequest,
    session: ActorSessionDep,
    current_user: ActorUserDep,
    guild_context: TagsWrite,
) -> TagBulkEditResponse:
    """Add and/or remove tags across many entities of one type, atomically.

    Every target is authorized with write on the tool that governs it, read
    from the registry its RLS policy is rendered from: a tool row asks itself,
    a sub-resource (a task, a queue item, a wiki page, …) asks its parent tool.
    Nothing is applied unless every target passes — one transaction, and a
    parent tool's ``updated_at`` moves once for all of its sub-resources rather
    than once per row.
    """
    target = payload.target_type.value
    _require_install_tagging_scopes(guild_context, target)
    spec = tags_service.TAG_LINKS[target]
    add_ids = await tags_service.validate_guild_tag_ids(
        session, guild_context.guild_id, payload.add_tag_ids
    )
    remove_ids = list(dict.fromkeys(payload.remove_tag_ids))
    target_ids = list(dict.fromkeys(payload.target_ids))

    tool, chain = _governing(spec)
    parent_ids = target_ids
    if chain:
        ((parent_fk, _parent_table),) = chain
        rows = (
            await session.exec(
                select(spec.entity.id, getattr(spec.entity, parent_fk)).where(
                    spec.entity.id.in_(target_ids)
                )
            )
        ).all()
        if len(rows) != len(target_ids):
            # Every tag target's code follows the one spelling:
            # TASK_NOT_FOUND, QUEUE_ITEM_NOT_FOUND, WIKI_PAGE_NOT_FOUND, …
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{target.upper()}_NOT_FOUND",
            )
        parent_ids = list(dict.fromkeys(parent_id for _, parent_id in rows))
    for parent_id in parent_ids:
        await resource_access.load_authorized(
            session, tool, parent_id, current_user, guild_context, access="write"
        )

    await tags_service.bulk_edit_tags(
        session,
        spec,
        entity_ids=target_ids,
        add_tag_ids=add_ids,
        remove_tag_ids=remove_ids,
    )
    if chain:
        parent = tags_service.TOOL_TAG_LINKS[tool].entity
        await session.exec(
            sa_update(parent)
            .where(parent.id.in_(parent_ids))
            .values(updated_at=datetime.now(timezone.utc))
        )
    await session.commit()

    return TagBulkEditResponse(updated_count=len(target_ids))


@router.get("/{tag_id}", response_model=TagRead)
async def get_tag(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
    include_deleted: IncludeDeletedDep = False,
) -> TagRead:
    """Get a specific tag by ID."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    return serialize_tag(tag, guild_id=guild_context.guild_id)


@router.patch("/{tag_id}", response_model=TagRead)
async def update_tag(
    tag_id: int,
    tag_in: TagUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TagRead:
    """Update a tag's name or color."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)

    update_data = tag_in.model_dump(exclude_unset=True)
    if "name" in update_data and update_data["name"] is not None:
        await _check_duplicate_name(
            session,
            guild_context.guild_id,
            update_data["name"],
            exclude_tag_id=tag.id,
        )
        tag.name = update_data["name"].strip()

    if "color" in update_data and update_data["color"] is not None:
        tag.color = update_data["color"]

    tag.updated_at = datetime.now(timezone.utc)
    session.add(tag)
    await session.commit()
    await session.refresh(tag)
    return serialize_tag(tag, guild_id=guild_context.guild_id)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    """Soft-delete a tag. The tag moves to the guild's trash; junction rows
    stay in place (reads hide them via the soft-delete filter) and fall with
    the tag's ORM relationship cascade on hard purge."""
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)
    await trash(
        session,
        tag,
        deleted_by_user_id=current_user.id,
    )
    await session.commit()


@router.get("/{tag_id}/entities", response_model=TaggedEntitiesResponse)
async def get_tag_entities(
    tag_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> TaggedEntitiesResponse:
    """Everything carrying this tag, of every taggable kind.

    A tag reaches across every initiative in the community, so this listing
    answers what has been shared with the reader — the same rule the community
    front page's table and the ``/me/*`` views follow. A guild admin's authority
    over any one initiative is unchanged; it is asked about by opening that
    initiative, not by opening a tag.

    Each row names itself and the tool it lives in, the way a search hit does,
    which is everything a client needs to address it.
    """
    tag = await _get_tag_or_404(session, tag_id, guild_context.guild_id)

    items: list[SearchHit] = []
    for spec in tags_service.TAG_LINKS.values():
        model = spec.entity
        tool, chain = _governing(spec)
        # A sub-resource is shared as part of its tool, so the sharing leg and
        # the initiative are both read off the parent row.
        parent = tags_service.TOOL_TAG_LINKS[tool].entity
        tool_id = getattr(model, chain[0][0]) if chain else model.id
        label = getattr(model, model.display_field())
        statement = (
            select(model.id, label, parent.initiative_id, tool_id)
            .where(
                model.id.in_(tags_service.tagged_entity_ids(spec, [tag.id])),
                permissions_service.granted_scope_clause(
                    tool, tool_id, current_user.id, context=guild_context
                ),
            )
            .order_by(label)
        )
        if chain:
            statement = statement.join_from(model, parent, parent.id == tool_id)
        items.extend(
            SearchHit(
                entity_type=spec.kind,
                entity_id=entity_id,
                title=title or "",
                initiative_id=initiative_id,
                tool=tool,
                tool_id=parent_id,
            )
            for entity_id, title, initiative_id, parent_id in (
                await session.exec(statement)
            ).all()
        )
    return TaggedEntitiesResponse(items=items)
