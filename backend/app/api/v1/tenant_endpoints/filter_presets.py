"""Project filter presets — the shared, named filter sets a project offers.

Reads are gated at project ``read`` (anyone who can see the tasks can see the
presets); every mutation additionally requires being able to *configure* the
project — a project manager, the project owner, or a guild admin.
"""

from datetime import datetime, timezone
from typing import Annotated, List, Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import delete, select

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    SessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.api.v1.tenant_endpoints.tasks import _get_project_with_access
from app.core.messages import FilterPresetMessages, ProjectMessages
from app.models.platform.user import User
from app.models.tenant.filter_preset import ProjectFilterPreset
from app.models.tenant.project import Project
from app.schemas.tenant.filter_preset import (
    FilterPresetCreate,
    FilterPresetListResponse,
    FilterPresetRead,
    FilterPresetReorderRequest,
    FilterPresetUpdate,
)
from app.services import permissions as permissions_service
from app.services.tenant import filter_presets as filter_presets_service

router = APIRouter(
    prefix="/projects/{project_id}/filter-presets", tags=["filter-presets"]
)

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


async def _require_manageable_project(
    session: SessionDep,
    project_id: int,
    user: User,
    *,
    guild_context: GuildContext,
) -> Project:
    """Load the project, then require the right to configure it.

    Deliberately loaded at ``read`` rather than ``write``: a project manager's
    authority comes from their initiative role, not from a per-project share,
    so checking the sharing level first would refuse a manager who happens to
    hold only read on this project. ``require_project_admin`` is the gate —
    manager, project owner, or guild admin — and an owner holds write anyway.
    """
    project = await _get_project_with_access(
        session,
        project_id,
        user,
        guild_id=guild_context.guild_id,
        access="read",
    )
    if project.is_archived:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ProjectMessages.IS_ARCHIVED,
        )
    await permissions_service.require_project_admin(
        session, project, user, guild_role=guild_context.role
    )
    return project


async def _load_preset_or_404(
    session: SessionDep, project_id: int, preset_id: int
) -> ProjectFilterPreset:
    stmt = select(ProjectFilterPreset).where(
        ProjectFilterPreset.project_id == project_id,
        ProjectFilterPreset.id == preset_id,
    )
    result = await session.exec(stmt)
    preset = result.one_or_none()
    if preset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=FilterPresetMessages.NOT_FOUND,
        )
    return preset


@router.get("/", response_model=FilterPresetListResponse)
async def list_filter_presets(
    project_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> FilterPresetListResponse:
    project = await _get_project_with_access(
        session,
        project_id,
        current_user,
        guild_id=guild_context.guild_id,
        access="read",
    )
    presets = await filter_presets_service.list_presets(session, project_id)
    can_manage = await permissions_service.can_administer_project(
        session, project, current_user, guild_role=guild_context.role
    )
    return FilterPresetListResponse(
        items=[FilterPresetRead.model_validate(preset) for preset in presets],
        can_manage=can_manage,
    )


@router.post("/", response_model=FilterPresetRead, status_code=status.HTTP_201_CREATED)
async def create_filter_preset(
    project_id: int,
    preset_in: FilterPresetCreate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFilterPreset:
    project = await _require_manageable_project(
        session, project_id, current_user, guild_context=guild_context
    )

    presets = list(await filter_presets_service.list_presets(session, project.id))
    if len(presets) >= filter_presets_service.MAX_PRESETS_PER_PROJECT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FilterPresetMessages.LIMIT_REACHED,
        )

    slug = await filter_presets_service.slugify_unique(
        session, project.id, preset_in.name
    )
    insert_at = preset_in.position if preset_in.position is not None else len(presets)
    insert_at = max(0, min(insert_at, len(presets)))

    preset = ProjectFilterPreset(
        project_id=project.id,
        slug=slug,
        name=preset_in.name,
        filters=preset_in.filters.model_dump(mode="json"),
    )
    presets.insert(insert_at, preset)
    filter_presets_service.resequence(presets)
    session.add(preset)
    await session.flush()
    await filter_presets_service.normalize_defaults(
        session,
        project.id,
        prefer_id=preset.id if preset_in.is_default else None,
    )
    await session.commit()
    await session.refresh(preset)
    return preset


@router.patch("/{preset_id}", response_model=FilterPresetRead)
async def update_filter_preset(
    project_id: int,
    preset_id: int,
    preset_in: FilterPresetUpdate,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ProjectFilterPreset:
    await _require_manageable_project(
        session, project_id, current_user, guild_context=guild_context
    )

    target = await _load_preset_or_404(session, project_id, preset_id)
    presets = list(await filter_presets_service.list_presets(session, project_id))
    update_data = preset_in.model_dump(exclude_unset=True)

    if update_data.get("name") is not None:
        target.name = update_data["name"]
    if preset_in.filters is not None:
        target.filters = preset_in.filters.model_dump(mode="json")

    if update_data.get("position") is not None:
        reordered = [preset for preset in presets if preset.id != target.id]
        insert_at = max(0, min(update_data["position"], len(reordered)))
        reordered.insert(insert_at, target)
        filter_presets_service.resequence(reordered)

    target.updated_at = datetime.now(timezone.utc)
    await session.flush()

    requested_default = update_data.get("is_default")
    await filter_presets_service.normalize_defaults(
        session,
        project_id,
        prefer_id=target.id if requested_default else None,
        demote_id=target.id if requested_default is False else None,
    )
    await session.commit()
    await session.refresh(target)
    return target


@router.post("/reorder", response_model=List[FilterPresetRead])
async def reorder_filter_presets(
    project_id: int,
    reorder_in: FilterPresetReorderRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> Sequence[ProjectFilterPreset]:
    project = await _require_manageable_project(
        session, project_id, current_user, guild_context=guild_context
    )

    presets = list(await filter_presets_service.list_presets(session, project.id))
    if not reorder_in.items:
        return presets

    preset_map = {preset.id: preset for preset in presets}
    seen: set[int] = set()
    ordered: list[ProjectFilterPreset] = []
    for item in sorted(reorder_in.items, key=lambda entry: entry.position):
        if item.id in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=FilterPresetMessages.DUPLICATE_ID,
            )
        preset = preset_map.get(item.id)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=FilterPresetMessages.NOT_FOUND,
            )
        ordered.append(preset)
        seen.add(item.id)

    combined = ordered + [preset for preset in presets if preset.id not in seen]
    filter_presets_service.resequence(combined)
    await session.flush()
    await filter_presets_service.normalize_defaults(session, project.id)
    await session.commit()
    return await filter_presets_service.list_presets(session, project.id)


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_filter_preset(
    project_id: int,
    preset_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> None:
    await _require_manageable_project(
        session, project_id, current_user, guild_context=guild_context
    )

    target = await _load_preset_or_404(session, project_id, preset_id)
    await session.exec(
        delete(ProjectFilterPreset).where(ProjectFilterPreset.id == target.id)
    )
    # Deleting the last preset is allowed — the project then simply has no
    # default and the client falls back to showing everything.
    remaining = list(await filter_presets_service.list_presets(session, project_id))
    filter_presets_service.resequence(remaining)
    await session.flush()
    await filter_presets_service.normalize_defaults(session, project_id)
    await session.commit()
