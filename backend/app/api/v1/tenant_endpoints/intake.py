"""The operations community's intake: which project each stream lands in.

The platform names the community that receives the deployment's operations
work (``/settings/intake``); these routes are that community's own half, and
exist only there — every other community answers 404.

Every route is the seat's. Reading runs on the seat's session; changing runs
on the seat's write session and is the membership seat's alone, in a community
whose content is not read-only: setting a stream up authors a project.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import (
    GuildContext,
    SeatContextDep,
    SeatSessionDep,
    SeatWriteContextDep,
    SeatWriteSessionDep,
    get_current_active_user,
)
from app.core.intake import IntakeStream
from app.core.messages import IntakeMessages
from app.models.platform.guild import GuildStatus
from app.models.platform.user import User
from app.schemas.tenant.intake import (
    IntakeBindingRead,
    IntakeBindingsRead,
    IntakeBindingUpsert,
    IntakeBlueprintImport,
    IntakeOptionsRead,
)
from app.services.tenant import intake_bindings
from app.services.tenant.intake_bindings import BindingView

router = APIRouter()


def _read(view: BindingView) -> IntakeBindingRead:
    return IntakeBindingRead(
        stream=view.stream,
        binding_id=view.binding_id,
        project_id=view.project_id,
        project_name=view.project_name,
        project_archived=view.project_archived,
        initiative_id=view.initiative_id,
        initiative_name=view.initiative_name,
        default_status_id=view.default_status_id,
        default_status_name=view.default_status_name,
        enabled=view.enabled,
        last_case_at=view.last_case_at,
    )


def _stream_or_404(raw: str) -> IntakeStream:
    try:
        return IntakeStream(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=IntakeMessages.UNKNOWN_STREAM,
        ) from None


async def _writable(session: AsyncSession, context: GuildContext) -> None:
    """The operations community, changed by its membership seat while its
    content takes writes."""
    await intake_bindings.require_operations_guild(session, context.guild_id)
    # The seat's session is routed for the community's configuration, which
    # stays open while its content is read-only; the status is asked here.
    frozen = context.guild.status == GuildStatus.read_only.value
    if context.is_pam or frozen:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=IntakeMessages.WRITE_REQUIRED,
        )


@router.get("", response_model=IntakeBindingsRead)
async def read_intake_bindings(
    session: SeatSessionDep,
    context: SeatContextDep,
) -> IntakeBindingsRead:
    """Where each stream lands, and when it last opened a case.

    Every stream is listed whether bound or not, so the page shows the full set
    rather than only what somebody already configured. 404 in any community
    other than the operations community, which is how the settings page knows
    whether to offer the tab.
    """
    await intake_bindings.require_operations_guild(session, context.guild_id)
    views = await intake_bindings.list_bindings(session)
    return IntakeBindingsRead(bindings=[_read(view) for view in views])


@router.get("/options", response_model=IntakeOptionsRead)
async def read_intake_options(
    session: SeatSessionDep,
    context: SeatContextDep,
) -> IntakeOptionsRead:
    """What a stream can be bound to: this community's initiatives, their
    projects and each project's statuses — names and ids, enough to fill the
    pickers."""
    await intake_bindings.require_operations_guild(session, context.guild_id)
    return IntakeOptionsRead.model_validate(
        {"initiatives": await intake_bindings.list_options(session)}
    )


@router.put("/{stream}", response_model=IntakeBindingRead)
async def upsert_intake_binding(
    stream: str,
    payload: IntakeBindingUpsert,
    session: SeatWriteSessionDep,
    context: SeatWriteContextDep,
) -> IntakeBindingRead:
    """Route one stream into a project of this community."""
    await _writable(session, context)
    view = await intake_bindings.bind(
        session,
        stream=_stream_or_404(stream),
        project_id=payload.project_id,
        default_status_id=payload.default_status_id,
        enabled=payload.enabled,
    )
    return _read(view)


@router.post("/{stream}/blueprint", response_model=IntakeBindingRead)
async def import_intake_blueprint(
    stream: str,
    payload: IntakeBlueprintImport,
    session: SeatWriteSessionDep,
    context: SeatWriteContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> IntakeBindingRead:
    """Set a stream up from its blueprint, and bind it to what that produced.

    An ordinary project import. The result is a project the team can rename and
    restructure; the binding only names it.
    """
    await _writable(session, context)
    view = await intake_bindings.provision_from_blueprint(
        session,
        stream=_stream_or_404(stream),
        initiative_id=payload.initiative_id,
        importer=current_user,
    )
    return _read(view)


@router.delete("/{stream}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_intake_binding(
    stream: str,
    session: SeatWriteSessionDep,
    context: SeatWriteContextDep,
) -> None:
    """Stop routing a stream. The project and every case in it stay."""
    await _writable(session, context)
    await intake_bindings.unbind(session, _stream_or_404(stream))
