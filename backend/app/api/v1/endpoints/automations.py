"""Automations endpoints — CRUD for flows and read-only access to runs/steps.

Initiative-scoped automations. Access is gated at the infrastructure level
(ENABLE_AUTOMATIONS env var) and at the initiative level via
automations_enabled + create_automations permission keys.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.api.deps import RLSSessionDep, get_current_active_user, GuildContext, get_guild_membership
from app.core.config import settings
from app.core.messages import AutomationsMessages, InitiativeMessages
from app.db.session import reapply_rls_context
from app.models.automation import AutomationFlow, AutomationRun
from app.models.initiative import Initiative, PermissionKey
from app.models.user import User
from app.schemas.automation import (
    AutomationFlowCreate,
    AutomationFlowListItem,
    AutomationFlowListResponse,
    AutomationFlowRead,
    AutomationFlowUpdate,
    AutomationRunDetailRead,
    AutomationRunListResponse,
    AutomationRunRead,
    AutomationRunStepRead,
    validate_flow_graph,
)
from app.services import rls as rls_service

router = APIRouter()

CurrentUser = Annotated[User, Depends(get_current_active_user)]
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_infra_flag() -> None:
    """Raise 403 if automations are not enabled at the infrastructure level."""
    if not settings.ENABLE_AUTOMATIONS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.INFRA_FEATURE_DISABLED,
        )


async def _get_initiative_or_404(
    session: RLSSessionDep,
    initiative_id: int,
) -> Initiative:
    """Guild-scoped initiative lookup (RLS enforces guild tenancy)."""
    stmt = select(Initiative).where(Initiative.id == initiative_id)
    result = await session.exec(stmt)
    initiative = result.one_or_none()
    if not initiative:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=InitiativeMessages.NOT_FOUND,
        )
    return initiative


async def _check_initiative_permission(
    session: RLSSessionDep,
    initiative: Initiative,
    user: User,
    guild_context: GuildContext,
    permission_key: PermissionKey,
) -> None:
    """Check that user has the required permission on the initiative."""
    if rls_service.is_guild_admin(guild_context.role):
        return
    has_perm = await rls_service.check_initiative_permission(
        session,
        initiative_id=initiative.id,
        user=user,
        permission_key=permission_key,
    )
    if not has_perm:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.FEATURE_DISABLED,
        )


async def _get_flow_or_404(
    session: RLSSessionDep,
    flow_id: int,
) -> AutomationFlow:
    """Fetch an automation flow by ID or raise 404."""
    stmt = select(AutomationFlow).where(AutomationFlow.id == flow_id)
    result = await session.exec(stmt)
    flow = result.one_or_none()
    if not flow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AutomationsMessages.FLOW_NOT_FOUND,
        )
    return flow


def _validate_graph_or_400(flow_data: dict) -> None:
    """Run flow graph validation and raise 400 if there are errors."""
    warnings = validate_flow_graph(flow_data)
    if warnings:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AutomationsMessages.INVALID_FLOW_GRAPH,
        )


# ---------------------------------------------------------------------------
# Flow CRUD
# ---------------------------------------------------------------------------


@router.get("/automations", response_model=AutomationFlowListResponse)
async def list_automations(
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    initiative_id: int = Query(..., description="Initiative to list automations for"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> AutomationFlowListResponse:
    """List automation flows for an initiative (without full flow_data)."""
    _require_infra_flag()

    initiative = await _get_initiative_or_404(session, initiative_id)
    if not initiative.automations_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.FEATURE_DISABLED,
        )
    await _check_initiative_permission(
        session, initiative, current_user, guild_context,
        PermissionKey.automations_enabled,
    )

    conditions = [
        AutomationFlow.guild_id == guild_context.guild_id,
        AutomationFlow.initiative_id == initiative_id,
    ]

    # Count
    count_subq = select(AutomationFlow.id).where(*conditions).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    # Data
    stmt = (
        select(AutomationFlow)
        .where(*conditions)
        .order_by(AutomationFlow.updated_at.desc(), AutomationFlow.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    flows = result.all()

    items = [AutomationFlowListItem.model_validate(f) for f in flows]
    has_next = page * page_size < total_count
    return AutomationFlowListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )


@router.post("/automations", response_model=AutomationFlowRead, status_code=status.HTTP_201_CREATED)
async def create_automation(
    flow_in: AutomationFlowCreate,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> AutomationFlowRead:
    """Create a new automation flow.

    Validates the flow graph structure and requires create_automations
    permission on the initiative.
    """
    _require_infra_flag()

    initiative = await _get_initiative_or_404(session, flow_in.initiative_id)
    if not initiative.automations_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AutomationsMessages.FEATURE_DISABLED,
        )
    await _check_initiative_permission(
        session, initiative, current_user, guild_context,
        PermissionKey.create_automations,
    )

    _validate_graph_or_400(flow_in.flow_data)

    now = datetime.now(timezone.utc)
    flow = AutomationFlow(
        guild_id=guild_context.guild_id,
        initiative_id=initiative.id,
        created_by_id=current_user.id,
        name=flow_in.name.strip(),
        description=flow_in.description,
        flow_data=flow_in.flow_data,
        enabled=flow_in.enabled,
        created_at=now,
        updated_at=now,
    )
    session.add(flow)
    await session.commit()
    await reapply_rls_context(session)

    # Re-fetch to ensure we have the DB-generated id
    await session.refresh(flow)
    return AutomationFlowRead.model_validate(flow)


# ---------------------------------------------------------------------------
# Run detail — placed before /automations/{flow_id} so FastAPI resolves
# the literal "runs" segment before the {flow_id} path parameter.
# ---------------------------------------------------------------------------


@router.get("/automations/runs/{run_id}", response_model=AutomationRunDetailRead)
async def read_automation_run(
    run_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> AutomationRunDetailRead:
    """Get a single run with all step details."""
    _require_infra_flag()

    stmt = (
        select(AutomationRun)
        .where(AutomationRun.id == run_id)
        .options(selectinload(AutomationRun.steps))
    )
    result = await session.exec(stmt)
    run = result.one_or_none()
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AutomationsMessages.RUN_NOT_FOUND,
        )

    # Permission check via the run's initiative
    initiative = await _get_initiative_or_404(session, run.initiative_id)
    await _check_initiative_permission(
        session, initiative, current_user, guild_context,
        PermissionKey.automations_enabled,
    )

    steps = [
        AutomationRunStepRead.model_validate(s)
        for s in sorted(run.steps, key=lambda s: s.started_at)
    ]
    return AutomationRunDetailRead(
        id=run.id,
        flow_id=run.flow_id,
        flow_snapshot=run.flow_snapshot,
        trigger_event=run.trigger_event,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error=run.error,
        steps=steps,
    )


# ---------------------------------------------------------------------------
# Flow detail / update / delete
# ---------------------------------------------------------------------------


@router.get("/automations/{flow_id}", response_model=AutomationFlowRead)
async def read_automation(
    flow_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> AutomationFlowRead:
    """Get a single automation flow with the full graph payload."""
    _require_infra_flag()

    flow = await _get_flow_or_404(session, flow_id)

    initiative = await _get_initiative_or_404(session, flow.initiative_id)
    await _check_initiative_permission(
        session, initiative, current_user, guild_context,
        PermissionKey.automations_enabled,
    )

    return AutomationFlowRead.model_validate(flow)


@router.put("/automations/{flow_id}", response_model=AutomationFlowRead)
async def update_automation(
    flow_id: int,
    flow_in: AutomationFlowUpdate,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> AutomationFlowRead:
    """Update an automation flow. Validates the graph if flow_data is provided."""
    _require_infra_flag()

    flow = await _get_flow_or_404(session, flow_id)

    initiative = await _get_initiative_or_404(session, flow.initiative_id)
    await _check_initiative_permission(
        session, initiative, current_user, guild_context,
        PermissionKey.create_automations,
    )

    update_data = flow_in.model_dump(exclude_unset=True)
    updated = False

    if "name" in update_data and update_data["name"] is not None:
        flow.name = update_data["name"].strip()
        updated = True

    if "description" in update_data:
        flow.description = update_data["description"]
        updated = True

    if "flow_data" in update_data and update_data["flow_data"] is not None:
        _validate_graph_or_400(update_data["flow_data"])
        flow.flow_data = update_data["flow_data"]
        updated = True

    if "enabled" in update_data and update_data["enabled"] is not None:
        flow.enabled = update_data["enabled"]
        updated = True

    if updated:
        flow.updated_at = datetime.now(timezone.utc)
        session.add(flow)
        await session.commit()
        await reapply_rls_context(session)
        await session.refresh(flow)

    return AutomationFlowRead.model_validate(flow)


@router.delete("/automations/{flow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    flow_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
) -> None:
    """Delete an automation flow. Cascade deletes runs via FK."""
    _require_infra_flag()

    flow = await _get_flow_or_404(session, flow_id)

    initiative = await _get_initiative_or_404(session, flow.initiative_id)
    await _check_initiative_permission(
        session, initiative, current_user, guild_context,
        PermissionKey.create_automations,
    )

    await session.delete(flow)
    await session.commit()


# ---------------------------------------------------------------------------
# Run history (for a specific flow)
# ---------------------------------------------------------------------------


@router.get("/automations/{flow_id}/runs", response_model=AutomationRunListResponse)
async def list_automation_runs(
    flow_id: int,
    session: RLSSessionDep,
    current_user: CurrentUser,
    guild_context: GuildContextDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> AutomationRunListResponse:
    """List run history for an automation flow."""
    _require_infra_flag()

    flow = await _get_flow_or_404(session, flow_id)

    initiative = await _get_initiative_or_404(session, flow.initiative_id)
    await _check_initiative_permission(
        session, initiative, current_user, guild_context,
        PermissionKey.automations_enabled,
    )

    conditions = [AutomationRun.flow_id == flow_id]

    # Count
    count_subq = select(AutomationRun.id).where(*conditions).subquery()
    count_stmt = select(func.count()).select_from(count_subq)
    total_count = (await session.exec(count_stmt)).one()

    # Data
    stmt = (
        select(AutomationRun)
        .where(*conditions)
        .order_by(AutomationRun.started_at.desc(), AutomationRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.exec(stmt)
    runs = result.all()

    items = [AutomationRunRead.model_validate(r) for r in runs]
    has_next = page * page_size < total_count
    return AutomationRunListResponse(
        items=items,
        total_count=total_count,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )
