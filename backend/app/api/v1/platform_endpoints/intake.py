"""The owner's intake settings: which community, and who to contact.

Every route is ``config.manage`` and runs on the request's own
``platform_<tier>`` session. Naming the community that receives operations
work is deployment configuration of the same class as OIDC, SMTP and branding.

Where each stream lands inside that community is the community's own setting,
made by its superadmin on its own routes (``/g/{guild_id}/intake``). Nothing
here reads inside it: the page names the community, and links there.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import UserSessionDep
from app.api.v1.platform_endpoints.admin import ConfigManageDep
from app.core.intake import IntakeStream
from app.core.messages import IntakeMessages
from app.schemas.platform.intake import (
    IntakeContactUpdate,
    IntakeSettingsRead,
    OperationsGuildUpdate,
)
from app.services.platform import intake as intake_service
from app.services.platform import intake_setup

router = APIRouter()


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
    guild_id = await intake_service.operations_guild_id(session)
    general, per_stream = await intake_setup.contacts(session)
    # Whether each stream has somewhere to land is the question the runtime
    # path answers before it opens a case; asked the same way here.
    receiving = (
        [
            stream
            for stream in IntakeStream
            if await intake_service.stream_is_bound(stream)
        ]
        if guild_id is not None
        else []
    )
    return IntakeSettingsRead(
        operations_guild_id=guild_id,
        operations_guild_name=await intake_setup.operations_guild_name(
            session, guild_id
        ),
        receiving=receiving,
        general_contact_email=general,
        contact_emails={IntakeStream(key): email for key, email in per_stream.items()},
    )


@router.get("/intake", response_model=IntakeSettingsRead)
async def read_intake_settings(
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> IntakeSettingsRead:
    """Which community receives operations work, which streams it currently
    receives, and who somebody is told to contact."""
    return await _settings(session)


@router.put("/intake/guild", response_model=IntakeSettingsRead)
async def update_operations_guild(
    payload: OperationsGuildUpdate,
    session: UserSessionDep,
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
    session: UserSessionDep,
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
    session: UserSessionDep,
    _admin: ConfigManageDep,
) -> IntakeSettingsRead:
    """Set one stream's contact address, or clear it back to the general one."""
    await intake_setup.set_stream_contact(
        session, _stream_or_404(stream), _address(payload)
    )
    return await _settings(session)
