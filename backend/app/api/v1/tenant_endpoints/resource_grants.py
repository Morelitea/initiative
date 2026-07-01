"""Unified resource-grants endpoint — set sharing on many resources at once.

Every DAC resource (project, document, queue, counter group, calendar event)
already replaces its sharing the same way through
``resource_access.set_resource_grants``. This router exposes that one flow in
bulk so the client can share/unshare a multi-selection in a single request
instead of one PUT per item.

Bulk is **best-effort per item** (the caller only ever selects things it can
manage, so a stray unmanageable/deleted item shouldn't fail the batch): each item
is authorized independently and reported as ``ok`` / ``forbidden`` / ``not_found``
in the response, while the others still apply.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api import resource_access
from app.api.deps import (
    GuildContext,
    RLSSessionDep,
    get_current_active_user,
    get_guild_membership,
)
from app.models.platform.user import User
from app.schemas.tenant.resource_grant import (
    ResourceGrantBulkItemResult,
    ResourceGrantBulkRequest,
    ResourceGrantBulkResponse,
)

router = APIRouter()

GuildContextDep = Annotated[GuildContext, Depends(get_guild_membership)]


def _outcome_for(status_code: int) -> str | None:
    """Map a per-item HTTPException to its result status. 404 → not_found; any
    other client error (403 no-access, 400 archived, feature-disabled, …) →
    forbidden (skipped, with the code in ``detail``). Server errors (5xx) return
    None so they propagate and fail the whole request — those are bugs, not
    "this item was skipped"."""
    if status_code == status.HTTP_404_NOT_FOUND:
        return "not_found"
    if 400 <= status_code < 500:
        return "forbidden"
    return None


@router.put("/bulk", response_model=ResourceGrantBulkResponse)
async def bulk_set_resource_grants(
    payload: ResourceGrantBulkRequest,
    session: RLSSessionDep,
    current_user: Annotated[User, Depends(get_current_active_user)],
    guild_context: GuildContextDep,
) -> ResourceGrantBulkResponse:
    """Replace sharing on each listed resource (owner always preserved). Items the
    caller can't manage or that don't exist are skipped and reported; the rest
    apply. Each successful item commits independently — a later skip never rolls
    back an earlier success (authorization is checked before any write, so a skip
    leaves the transaction clean)."""
    results: list[ResourceGrantBulkItemResult] = []
    for item in payload.items:
        try:
            await resource_access.set_resource_grants(
                session,
                item.resource_type,
                item.resource_id,
                current_user,
                guild_context,
                item.grants,
            )
            results.append(
                ResourceGrantBulkItemResult(
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    status="ok",
                )
            )
        except HTTPException as exc:
            outcome = _outcome_for(exc.status_code)
            if outcome is None:
                raise
            results.append(
                ResourceGrantBulkItemResult(
                    resource_type=item.resource_type,
                    resource_id=item.resource_id,
                    status=outcome,
                    detail=exc.detail if isinstance(exc.detail, str) else None,
                )
            )
    return ResourceGrantBulkResponse(results=results)
