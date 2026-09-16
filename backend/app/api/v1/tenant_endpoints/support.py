"""Sending a help request from inside a community.

One endpoint. Whether this community takes them at all is the guild's own
setting, read here rather than trusted from the client — the same control the
sidebar reads to decide whether to offer the form or the FAQ.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import GuildContext, get_current_active_user, get_guild_membership
from app.core.messages import SupportMessages
from app.models.platform.user import User
from app.schemas.tenant.support import SupportRequestAccepted, SupportRequestCreate
from app.services.tenant import support as support_service

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


@router.post(
    "", response_model=SupportRequestAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def ask_for_help(
    payload: SupportRequestCreate,
    context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> SupportRequestAccepted:
    """Send a help request to whoever runs this deployment.

    Open to every member of the community, which is the point of it: the
    person who needs help is rarely the person who administers anything.
    """
    try:
        await support_service.request_help(
            guild=context.guild,
            requester=current_user,
            subject=payload.subject,
            body=payload.body,
        )
    except support_service.SupportUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=SupportMessages.NOT_AVAILABLE,
        ) from exc
    except support_service.NowhereToSend as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SupportMessages.NOWHERE_TO_SEND,
        ) from exc
    return SupportRequestAccepted()
