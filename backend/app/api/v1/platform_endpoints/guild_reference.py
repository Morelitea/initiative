"""The same guild, named in another sector.

A reference is minted per sector, so two parties hold unrelated values for one
guild and neither can be worked out from the other — that is what a sector is
for. A service that has to reconcile two of them cannot do it alone, and this
deployment is the only party holding both.

So it asks, presenting a reference **of its own**. What it gets back is the
same guild in the sector it named. It records the pair and does not ask again.

Reached two ways, and no member is involved in either — this is a fact about
a guild, asked for by a service, and a member's credential is never a way to
learn it:

* **An installation token** of an app whose registration came from the
  registry verified under the root shipped in the image, and names the sector
  in its ``reference_sectors``. The guild is the token's install's; a
  ``guild_ref`` is optional and, when given, has to be the caller's own name
  for that same guild.
* **The bundled-service channel**, which an operator names and wires, with a
  reference of the caller's own.

Nothing is minted. A sector that has never named this guild has nothing to
report, which is a 404 and not a reason to create one.

See ``history/opaque-identity-design.md`` §15.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import SessionDep, oauth2_scheme
from app.api.v1.platform_endpoints.app_installation import installation_caller
from app.core.app_access_token import is_access_token
from app.core.config import settings
from app.core.messages import BundledChannelMessages
from app.db.session import get_system_session
from app.models.platform.app_service_registration import (
    AppServiceRegistration,
    RegistrationSource,
)
from app.models.platform.identity_ref import IdentityEntity, IdentityPurpose
from app.schemas.marketplace.guild_reference import (
    GuildReferenceRead,
    GuildReferenceRequest,
    InstallationReferenceRequest,
)
from app.services.marketplace import app_refs
from app.services.marketplace.bundled_channel import (
    BundledChannelError,
    verify_bundled_envelope,
)
from app.services.marketplace.tuf_registry import configured_root_is_builtin
from app.services.platform import identity_refs

#: Sectors this can be asked for.
#:
#: A sector that names something inside a guild — an install, a subscription —
#: takes that thing's id as well, and a caller holding one reference has no way
#: to say which of the others it means. Those are asked for where the thing
#: itself is known, not here. Everything not listed is refused, so a sector
#: added later is answerable only once somebody decides it should be.
ANSWERABLE_PURPOSES: frozenset[IdentityPurpose] = frozenset({IdentityPurpose.billing})

#: Not part of the OpenAPI schema: service-to-service, and no browser calls it.
router = APIRouter(include_in_schema=False)

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]


def _sector_refused() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=BundledChannelMessages.SECTOR_NOT_ANSWERABLE,
    )


async def _answer_installation(
    request: Request,
    session: AsyncSession,
    system_session: AsyncSession,
    bearer: str,
    body: bytes,
) -> GuildReferenceRead:
    """Name the token's community in a sector its registration carries."""
    installation = await installation_caller(request, session, bearer)

    try:
        payload = InstallationReferenceRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=BundledChannelMessages.INVALID_PAYLOAD,
        ) from exc
    if payload.purpose not in ANSWERABLE_PURPOSES:
        raise _sector_refused()

    # Read fresh on the system engine: the sector is a registry statement, and
    # it holds only while the registration came from the shipped root.
    public_id = installation.registration.public_id
    row = (
        await system_session.exec(
            select(AppServiceRegistration).where(
                AppServiceRegistration.public_id == public_id
            )
        )
    ).first()
    if (
        row is None
        or row.source != RegistrationSource.REGISTRY
        or not row.root_is_builtin
        or payload.purpose.value not in (row.reference_sectors or [])
        or not configured_root_is_builtin()
    ):
        raise _sector_refused()

    guild_id = installation.guild_id
    if payload.guild_ref is not None:
        named = await app_refs.guild_for_app_ref(
            ref=payload.guild_ref, public_id=public_id
        )
        if named != guild_id:
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


@router.post("/community-reference", response_model=GuildReferenceRead)
async def read_guild_reference(
    request: Request,
    session: SessionDep,
    system_session: SystemSessionDep,
    bearer: Annotated[Optional[str], Depends(oauth2_scheme)] = None,
) -> GuildReferenceRead:
    """Name the caller's guild in another sector."""
    body = await request.body()
    if bearer and is_access_token(bearer):
        return await _answer_installation(
            request, session, system_session, bearer, body
        )
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

    try:
        payload = GuildReferenceRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=BundledChannelMessages.INVALID_PAYLOAD,
        ) from exc

    if payload.purpose not in ANSWERABLE_PURPOSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=BundledChannelMessages.SECTOR_NOT_ANSWERABLE,
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
