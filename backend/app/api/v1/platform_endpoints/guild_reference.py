"""The same guild, named in another sector.

A reference is minted per sector, so two parties hold unrelated values for one
guild and neither can be worked out from the other — that is what a sector is
for. A service that has to reconcile two of them cannot do it alone, and this
deployment is the only party holding both.

So it asks, presenting a reference **of its own**. What it gets back is the
same guild in the sector it named. It records the pair and does not ask again.

Reached on the bundled-service channel: the caller is established by a secret
with one holder, which an operator names and wires. No member is involved
anywhere — this is a fact about a guild, asked for by a service, and a member's
credential is never a way to learn it.

Nothing is minted. A sector that has never named this guild has nothing to
report, which is a 404 and not a reason to create one.

See ``history/opaque-identity-design.md`` §15.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.core.config import settings
from app.core.messages import BundledChannelMessages
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.schemas.marketplace.guild_reference import (
    GuildReferenceRead,
    GuildReferenceRequest,
)
from app.services.marketplace import app_refs
from app.services.marketplace.bundled_channel import (
    BundledChannelError,
    verify_bundled_envelope,
)
from app.services.platform import identity_refs

#: Not part of the OpenAPI schema: service-to-service, and no browser calls it.
router = APIRouter(include_in_schema=False)


@router.post("/guild-reference", response_model=GuildReferenceRead)
async def read_guild_reference(request: Request) -> GuildReferenceRead:
    """Name the caller's guild in another sector."""
    body = await request.body()
    try:
        verify_bundled_envelope(
            method=request.method,
            path=request.url.path,
            headers=request.headers,
            body=body,
        )
    except BundledChannelError as exc:
        # Unconfigured is this deployment's own gap rather than the caller's
        # fault, and retryable; everything else is a refusal.
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.code == BundledChannelMessages.NOT_CONFIGURED
                else status.HTTP_403_FORBIDDEN
            ),
            detail=exc.code,
        ) from exc

    payload = GuildReferenceRequest.model_validate_json(body)
    if payload.purpose is IdentityPurpose.app:
        # An app sector belongs to one install. Translating between two of them
        # is the one question this must not answer.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BundledChannelMessages.NO_SUCH_NAME,
        )

    # The reference must be one of the CALLER's own. Resolving says which
    # install minted it; this says that install is the caller's.
    guild_id = await app_refs.guild_for_app_ref(
        ref=payload.guild_ref,
        public_id=(settings.BUNDLED_SERVICE_PUBLIC_ID or "").strip(),
    )
    if guild_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BundledChannelMessages.UNKNOWN_GUILD,
        )

    ref = await identity_refs.existing_ref(
        entity_type=IdentityEntity.guild, entity_id=guild_id, purpose=payload.purpose
    )
    if ref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=BundledChannelMessages.NO_SUCH_NAME,
        )
    return GuildReferenceRead(purpose=payload.purpose, guild_ref=ref)
