"""The owner's intake settings: which guild, and which project per stream.

Every route is ``config.manage``. Binding a stream is deployment configuration
of the same class as OIDC, SMTP and branding, and sits at the same capability.

The session is the system engine, which is what reaches both the shared
singleton and — routed, as a guild admin — the guild's own schema. That is the
pattern the OIDC-mapping routes beside this already use.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.platform_endpoints.operator import ConfigManageDep
from app.core.intake import IntakeStream
from app.core.messages import IntakeMessages
from app.db.session import get_admin_session, set_rls_context
from app.models.platform.guild import Guild
from app.models.platform.user import User
from app.schemas.platform.intake import (
    IntakeBindingRead,
    IntakeBindingUpsert,
    IntakeBlueprintImport,
    IntakeContactUpdate,
    IntakeOptionsRead,
    IntakeSettingsRead,
    OperationsGuildUpdate,
)
from app.services.platform import intake_setup
from app.services.platform.intake_setup import BindingView
from app.api.deps import get_current_active_user

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]


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


def _address(payload: IntakeContactUpdate) -> str | None:
    return None if payload.email is None else str(payload.email)


async def _settings(session: AsyncSession) -> IntakeSettingsRead:
    guild_id, views = await intake_setup.list_bindings(session)
    guild_name = None
    if guild_id is not None:
        await set_rls_context(session)
        guild_name = (
            await session.exec(select(Guild.name).where(Guild.id == guild_id))
        ).one_or_none()
    general, per_stream = await intake_setup.contacts(session)
    return IntakeSettingsRead(
        operations_guild_id=guild_id,
        operations_guild_name=guild_name,
        bindings=[_read(view) for view in views],
        general_contact_email=general,
        contact_emails={IntakeStream(key): email for key, email in per_stream.items()},
    )


@router.get("/intake", response_model=IntakeSettingsRead)
async def read_intake_settings(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> IntakeSettingsRead:
    """Where each stream lands, and when it last opened a case.

    Every stream is listed whether bound or not, so the page shows the full set
    rather than only what somebody already configured.
    """
    return await _settings(session)


@router.get("/intake/options", response_model=IntakeOptionsRead)
async def read_intake_options(
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> IntakeOptionsRead:
    """What the settings page can bind a stream to.

    The operations guild's initiatives, their projects and each project's
    statuses — names and ids, enough to fill the pickers. Empty before a guild
    has been named.
    """
    return IntakeOptionsRead.model_validate(
        {"initiatives": await intake_setup.list_options(session)}
    )


@router.put("/intake/guild", response_model=IntakeSettingsRead)
async def update_operations_guild(
    payload: OperationsGuildUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> IntakeSettingsRead:
    """Name the guild that receives this deployment's operations work.

    Clearing it stops every stream at once and touches no binding inside the
    guild, so pointing back restores exactly what was there.
    """
    await intake_setup.set_operations_guild(session, payload.guild_id)
    return await _settings(session)


@router.put("/intake/contact", response_model=IntakeSettingsRead)
async def update_general_contact(
    payload: IntakeContactUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> IntakeSettingsRead:
    """Set the deployment's catch-all contact address, or clear it.

    Named wherever somebody is told who to contact and the stream in question
    has no address of its own.
    """
    await intake_setup.set_general_contact(session, _address(payload))
    return await _settings(session)


@router.put("/intake/{stream}/contact", response_model=IntakeSettingsRead)
async def update_stream_contact(
    stream: str,
    payload: IntakeContactUpdate,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> IntakeSettingsRead:
    """Set one stream's contact address, or clear it back to the general one."""
    await intake_setup.set_stream_contact(
        session, _stream_or_404(stream), _address(payload)
    )
    return await _settings(session)


@router.put("/intake/{stream}", response_model=IntakeBindingRead)
async def upsert_binding(
    stream: str,
    payload: IntakeBindingUpsert,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> IntakeBindingRead:
    """Route one stream into a project of the operations guild."""
    view = await intake_setup.bind(
        session,
        stream=_stream_or_404(stream),
        project_id=payload.project_id,
        default_status_id=payload.default_status_id,
        enabled=payload.enabled,
    )
    return _read(view)


@router.post("/intake/{stream}/blueprint", response_model=IntakeBindingRead)
async def import_blueprint(
    stream: str,
    payload: IntakeBlueprintImport,
    session: AdminSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    _admin: ConfigManageDep,
) -> IntakeBindingRead:
    """Set a stream up from its blueprint, and bind it to what that produced.

    An ordinary project import. The result is a project the team can rename and
    restructure; the binding only names it.
    """
    view = await intake_setup.provision_from_blueprint(
        session,
        stream=_stream_or_404(stream),
        initiative_id=payload.initiative_id,
        importer=current_user,
    )
    return _read(view)


@router.delete("/intake/{stream}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_binding(
    stream: str,
    session: AdminSessionDep,
    _admin: ConfigManageDep,
) -> None:
    """Stop routing a stream. The project and every case in it stay."""
    await intake_setup.unbind(session, _stream_or_404(stream))
