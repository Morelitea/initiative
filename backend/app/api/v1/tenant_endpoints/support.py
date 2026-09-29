"""Sending a help request from inside a community.

Two routes: one saying whether the form should be offered at all, and one
taking what is typed into it. Whether this community's members may ask is an
operator entitlement, read here rather than trusted from the client.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    RLSSessionDep,
    get_current_active_user,
    GuildContextDep,
)
from app.core.messages import SupportMessages
from app.models.platform.user import User
from app.schemas.tenant.support import (
    SupportAvailability,
    SupportRequestAccepted,
    SupportRequestCreate,
)
from app.services.tenant import support as support_service

router = APIRouter()


@router.get("", response_model=SupportAvailability)
async def support_availability(
    session: RLSSessionDep,
    context: GuildContextDep,
) -> SupportAvailability:
    """Whether to offer the help form here, or the FAQ.

    Asked by the sidebar, which draws the control either way — so this is the
    answer to "what does it do", never to "is it there".
    """
    return SupportAvailability(
        available=await support_service.can_ask_for_help(
            session, guild_id=context.guild_id
        )
    )


@router.post(
    "", response_model=SupportRequestAccepted, status_code=status.HTTP_202_ACCEPTED
)
async def ask_for_help(
    payload: SupportRequestCreate,
    session: RLSSessionDep,
    context: GuildContextDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> SupportRequestAccepted:
    """Send a help request to whoever runs this deployment.

    Open to every member of the community, which is the point of it: the
    person who needs help is rarely the person who administers anything.
    """
    try:
        await support_service.request_help(
            session,
            guild_id=context.guild_id,
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
