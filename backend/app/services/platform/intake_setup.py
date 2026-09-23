"""The platform's half of intake: which community, and who to contact.

The platform holds one pointer — ``app_settings.operations_guild_id`` — and the
contact addresses a notice gives. Everything else is ordinary per-guild config
inside the community the pointer names, set by that community's superadmin
(``app.services.tenant.intake_bindings``).

Every write here is the platform owner's (``config.manage``), on the request's
own ``platform_<tier>`` session: ``app_settings`` is written under the tier
that manages deployment configuration.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status as http_status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.intake import IntakeStream
from app.core.messages import GuildMessages, IntakeMessages
from app.models.platform.app_setting import AppSetting
from app.models.platform.guild import Guild, GuildStatus


async def _settings_row(session: AsyncSession) -> AppSetting:
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    return row if row is not None else AppSetting(id=1)


async def operations_guild_name(
    session: AsyncSession, guild_id: Optional[int]
) -> Optional[str]:
    """The name of the community the pointer names, for the settings page.

    Read on the owner's platform session: the tier holding ``config.manage``
    also holds ``guilds.manage``, which reads every community's row.
    """
    if guild_id is None:
        return None
    return (
        await session.exec(select(Guild.name).where(Guild.id == guild_id))
    ).one_or_none()


async def set_operations_guild(
    session: AsyncSession, guild_id: Optional[int]
) -> Optional[int]:
    """Point this deployment's operations work at ``guild_id``, or at nothing.

    ``None`` unsets it, which stops every stream at once without touching the
    bindings inside the guild — so pointing back restores exactly what was
    there. An ordinary guild is required: a suspended one could not be worked
    in, so it is refused rather than silently accepted.
    """
    if guild_id is not None:
        guild = (
            await session.exec(select(Guild).where(Guild.id == guild_id))
        ).one_or_none()
        if guild is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail=GuildMessages.GUILD_NOT_FOUND,
            )
        if guild.status != GuildStatus.active.value:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=IntakeMessages.GUILD_NOT_ACTIVE,
            )

    row = await _settings_row(session)
    row.operations_guild_id = guild_id
    session.add(row)
    await session.commit()
    return guild_id


async def set_general_contact(session: AsyncSession, email: Optional[str]) -> None:
    """Set the deployment's catch-all contact address, or clear it."""
    row = await _settings_row(session)
    row.intake_general_contact = email
    session.add(row)
    await session.commit()


async def set_stream_contact(
    session: AsyncSession, stream: IntakeStream, email: Optional[str]
) -> None:
    """Set one stream's contact address, or clear it back to the general one."""
    row = await _settings_row(session)
    contacts = dict(row.intake_contacts or {})
    if email is None:
        contacts.pop(stream.value, None)
    else:
        contacts[stream.value] = email
    # A fresh dict, so the JSONB column is seen as changed.
    row.intake_contacts = contacts
    session.add(row)
    await session.commit()


async def contacts(session: AsyncSession) -> tuple[Optional[str], dict[str, str]]:
    """The general address and every stream's own, as set."""
    row = (await session.exec(select(AppSetting).where(AppSetting.id == 1))).first()
    if row is None:
        return None, {}
    return row.intake_general_contact, dict(row.intake_contacts or {})
