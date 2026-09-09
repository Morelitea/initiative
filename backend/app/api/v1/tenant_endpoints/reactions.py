"""Emoji reactions, one route set for every reactable kind.

``/reactions/{target_type}/{target_id}`` is generic on purpose: the kind is a
path segment resolved through the service registry, so the next reactable thing
gets these endpoints for free instead of a parallel set of its own.
"""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.core.reactions import ReactionTarget
from app.models.platform.user import User
from app.schemas.tenant.reaction import (
    SUGGESTED_EMOJI,
    ReactionSummary,
    ReactionToggle,
)
from app.services.tenant import reactions as reactions_service

router = APIRouter()
GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _raise(exc: reactions_service.ReactionError) -> NoReturn:
    """Translate a service error into its HTTP shape. Declared ``NoReturn`` so
    a caller can treat everything after it as unreachable."""
    if isinstance(exc, reactions_service.ReactionNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, reactions_service.ReactionPermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, reactions_service.ReactionDisabledError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/suggested", response_model=list[str])
async def suggested_reactions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> list[str]:
    """The emoji every reaction picker offers first.

    Served rather than hard-coded in the client so the set is one decision for
    the whole product — the same row appears on every surface, for everyone,
    instead of whatever each browser happened to pick last. The list itself is
    the same for every guild; the dependencies are the auth and path gates
    every route under here carries.
    """
    return list(SUGGESTED_EMOJI)


@router.get(
    "/{target_type}/{target_id}",
    response_model=ReactionSummary,
)
async def read_reactions(
    target_type: ReactionTarget,
    target_id: int,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ReactionSummary:
    """Every reaction on one target. Reading takes read access on the target."""
    try:
        ctx = await reactions_service.resolve_target(
            session,
            target=target_type,
            target_id=target_id,
            user=current_user,
            guild_id=guild_context.guild_id,
            access="read",
        )
    except reactions_service.ReactionError as exc:
        _raise(exc)
    return await reactions_service.summary_for(
        session,
        target=target_type,
        target_id=ctx.target_id,
        viewer_id=current_user.id,
    )


@router.put(
    "/{target_type}/{target_id}",
    response_model=ReactionSummary,
)
async def toggle_reaction(
    target_type: ReactionTarget,
    target_id: int,
    payload: ReactionToggle,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ReactionSummary:
    """Add this emoji, or take it back if it is already yours.

    A toggle rather than separate add/remove routes: the client already knows
    whether the chip is pressed, and one idempotent-per-intent call removes the
    race where a double tap leaves a reaction it meant to clear.
    """
    try:
        summary, _added = await reactions_service.toggle_reaction(
            session,
            target=target_type,
            target_id=target_id,
            emoji=payload.emoji,
            user=current_user,
            guild_id=guild_context.guild_id,
        )
    except reactions_service.ReactionError as exc:
        _raise(exc)

    await session.commit()
    return summary
