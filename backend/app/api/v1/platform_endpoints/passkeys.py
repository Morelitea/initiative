"""Registering, naming and removing the account's passkeys.

Mounted under ``/auth`` beside the second factor. Signing in with one is not
here yet — this is the surface that gives an account something to sign in
*with*, and nothing in it can shut anybody out.

Every route runs on the system engine: ``user_passkeys`` is app_admin-only,
because a credential is presented while signing in, before there is anybody to
scope a policy to.
"""

import json
import logging
import uuid
from typing import Annotated, Any

import webauthn
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException

from app.api.deps import get_current_active_user, require_first_party_session
from app.api.v1.platform_endpoints.password_recheck import require_password
from app.core.audit_events import AuditEventType
from app.core.messages import AuthMessages
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.core.security import has_usable_password
from app.db.session import get_admin_session
from app.models.platform.user import User
from app.models.platform.user_passkey import UserPasskey
from app.schemas.platform.passkey import (
    PasskeyList,
    PasskeyRead,
    PasskeyRegisterFinish,
    PasskeyRegisterStart,
    PasskeyRegistrationOptions,
    PasskeyRemove,
    PasskeyRename,
)
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth import challenges as challenge_service
from app.services.auth import passkeys as passkey_service

logger = logging.getLogger(__name__)

router = APIRouter()

AdminSessionDep = Annotated[AsyncSession, Depends(get_admin_session)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]
#: Adding and removing a way in are done by the person in a session of their
#: own rather than through a standing credential.
FirstPartyOnly = Depends(require_first_party_session)

#: The purposes the finish route will answer for.
_REGISTER_PURPOSES = (challenge_service.ChallengePurpose.passkey_register,)


def _read(row: UserPasskey) -> PasskeyRead:
    return PasskeyRead.model_validate(row, from_attributes=True)


def _registration_invalid() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.PASSKEY_REGISTRATION_INVALID,
    )


def _site_unsupported() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.PASSKEY_SITE_UNSUPPORTED,
    )


def _limit_reached() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=AuthMessages.PASSKEY_LIMIT_REACHED,
    )


def _challenge_from_client_data(credential: dict[str, Any]) -> str:
    """The challenge the browser signed, read back out of its own client data.

    The ceremony's response carries the challenge inside the bytes the
    authenticator signed over, so that is where the server reads it from.
    """
    response = credential.get("response")
    if not isinstance(response, dict):
        raise _registration_invalid()
    encoded = response.get("clientDataJSON")
    if not isinstance(encoded, str) or not encoded:
        raise _registration_invalid()
    try:
        client_data = json.loads(webauthn.base64url_to_bytes(encoded))
    except Exception as exc:
        raise _registration_invalid() from exc
    challenge = client_data.get("challenge") if isinstance(client_data, dict) else None
    if not isinstance(challenge, str) or not challenge:
        raise _registration_invalid()
    return challenge


@router.get("/passkeys", response_model=PasskeyList)
async def list_passkeys(
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
) -> PasskeyList:
    """The account's passkeys, oldest first."""
    rows = await passkey_service.list_for_user(admin_session, user_id=current_user.id)
    return PasskeyList(
        passkeys=[_read(row) for row in rows],
        password_required=has_usable_password(current_user.hashed_password),
        limit=passkey_service.MAX_PASSKEYS_PER_USER,
        site_supported=passkey_service.site_refusal() is None,
    )


@router.post("/passkeys/register/begin", response_model=PasskeyRegistrationOptions)
@limiter.limit("10/15minutes", key_func=get_user_or_ip_key)
async def begin_passkey_registration(
    request: Request,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: PasskeyRegisterStart,
    _first_party: str = FirstPartyOnly,
) -> PasskeyRegistrationOptions:
    """Options for the browser to make a new credential with.

    The challenge inside them stands for a few minutes and is spent when the
    credential comes back. Beginning again issues another.

    The name arrives here as well as on the finish route, so a name this
    deployment will not keep is answered before the browser makes anything.
    The one stored is the one finish carries.
    """
    if passkey_service.site_refusal() is not None:
        raise _site_unsupported()
    require_password(current_user, payload.current_password)

    # What the credential manager lists the account under. The address the
    # person signs in with where there is one, so two entries for the same
    # deployment are told apart; the handle otherwise.
    account_name = (
        await addresses.primary_address(admin_session, user_id=current_user.id)
        or current_user.username
    )
    display_name = current_user.full_name or current_user.username

    try:
        ceremony = await passkey_service.begin_registration(
            admin_session,
            user_id=current_user.id,
            account_name=account_name,
            display_name=display_name,
        )
    except passkey_service.PasskeyLimitReached:
        raise _limit_reached() from None

    # The challenge is stored as the browser will write it back — the same
    # unpadded base64url the options carry — so the finish route can look the
    # row up by what it reads out of the signed client data.
    await challenge_service.create(
        admin_session,
        user_id=current_user.id,
        purpose=challenge_service.ChallengePurpose.passkey_register,
        value=bytes_to_base64url(ceremony.challenge),
    )
    await admin_session.commit()
    return PasskeyRegistrationOptions(options=ceremony.options)


@router.post(
    "/passkeys/register/finish",
    response_model=PasskeyRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/15minutes", key_func=get_user_or_ip_key)
async def finish_passkey_registration(
    request: Request,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: PasskeyRegisterFinish,
    _first_party: str = FirstPartyOnly,
) -> PasskeyRead:
    """Keep the credential the browser made, under the name given."""
    value = _challenge_from_client_data(payload.credential)

    challenge = await challenge_service.claim_attempt(
        admin_session, value=value, purposes=_REGISTER_PURPOSES
    )
    if challenge is None or challenge.user_id != current_user.id:
        # The attempt is counted whether or not the answer was any good, so
        # the commit comes before the refusal.
        await admin_session.commit()
        raise _registration_invalid()

    try:
        registered = passkey_service.finish_registration(
            credential=payload.credential,
            expected_challenge=webauthn.base64url_to_bytes(value),
        )
    except (WebAuthnException, ValueError) as exc:
        logger.warning(
            "passkey registration did not verify for user %s: %s: %s",
            current_user.id,
            type(exc).__name__,
            exc,
        )
        await admin_session.commit()
        raise _registration_invalid() from exc

    try:
        row = await passkey_service.store(
            admin_session,
            user_id=current_user.id,
            registered=registered,
            name=payload.name,
        )
    except passkey_service.PasskeyLimitReached:
        await admin_session.rollback()
        raise _limit_reached() from None

    if not await challenge_service.consume(admin_session, challenge):
        # The challenge went elsewhere between the claim and here, so the
        # credential staged against it goes with the transaction.
        await admin_session.rollback()
        raise _registration_invalid()

    read = _read(row)
    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_PASSKEY_REGISTERED,
        actor_user_id=current_user.id,
        detail={
            "passkey_id": str(row.id),
            "backed_up": registered.backed_up,
            "user_verified": registered.user_verified,
        },
    )
    await admin_session.commit()
    await email_service.announce_passkey_change(
        admin_session, current_user, added=True, name=read.name
    )
    return read


@router.patch("/passkeys/{passkey_id}", response_model=PasskeyRead)
@limiter.limit("30/15minutes", key_func=get_user_or_ip_key)
async def rename_passkey(
    request: Request,
    passkey_id: uuid.UUID,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: PasskeyRename,
    _first_party: str = FirstPartyOnly,
) -> PasskeyRead:
    """Give the credential another name. Nothing about signing in changes."""
    row = await passkey_service.rename(
        admin_session,
        user_id=current_user.id,
        passkey_id=passkey_id,
        name=payload.name,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.PASSKEY_NOT_FOUND,
        )
    read = _read(row)
    await admin_session.commit()
    return read


@router.post("/passkeys/{passkey_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/15minutes", key_func=get_user_or_ip_key)
async def remove_passkey(
    request: Request,
    passkey_id: uuid.UUID,
    current_user: CurrentUser,
    admin_session: AdminSessionDep,
    payload: PasskeyRemove,
    _first_party: str = FirstPartyOnly,
) -> None:
    """Forget the credential. The password is asked for again, as it is for a
    password change, because a way in is being taken away."""
    require_password(current_user, payload.current_password)

    # Read the name while the row is still there, so the letter can say which
    # credential went.
    existing = await admin_session.get(UserPasskey, passkey_id)
    name = existing.name if existing is not None else ""

    if not await passkey_service.remove(
        admin_session, user_id=current_user.id, passkey_id=passkey_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.PASSKEY_NOT_FOUND,
        )

    await audit_service.record(
        admin_session,
        event_type=AuditEventType.AUTH_PASSKEY_REMOVED,
        actor_user_id=current_user.id,
        detail={"passkey_id": str(passkey_id)},
    )
    # Sessions are left alone: the person is where they are and has just
    # proved it.
    await admin_session.commit()
    await email_service.announce_passkey_change(
        admin_session, current_user, added=False, name=name
    )
