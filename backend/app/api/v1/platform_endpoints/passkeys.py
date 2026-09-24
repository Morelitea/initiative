"""Registering, naming and removing the account's passkeys — and signing in.

Mounted under ``/auth`` beside the second factor. Two surfaces in one file
because they are two halves of one thing: the managing routes give an account
something to sign in *with*, and the two ``authenticate`` routes are where it
is presented.

The sign-in pair is unauthenticated and names nobody. The authenticator offers
what it holds for this deployment's domain, the assertion says which credential
answered, and the account is read off that credential — so the challenge the
ceremony begins with belongs to no account at all.

Every route runs on the system engine: ``user_passkeys`` is app_admin-only,
because a credential is presented while signing in, before there is anybody to
scope a policy to.
"""

import json
import logging
import uuid
from typing import Annotated, Any
from urllib.parse import urlencode

import webauthn
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn.helpers import bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException

from app.api.deps import (
    FactorExemptUser,
    get_current_active_user,
    require_first_party_session,
)
from app.api.v1.platform_endpoints.password_recheck import (
    require_password_or_recent_proof,
)
from app.api.v1.platform_endpoints.session_opening import (
    MOBILE_CALLBACK_URI,
    open_session,
    record_sign_in_failure,
    require_login_method,
    require_session_row,
    upgrade_session,
)
from app.core.audit_events import AuditEventType
from app.core.login_methods import LoginMethod
from app.core.messages import AuthMessages
from app.core.rate_limit import get_user_or_ip_key, limiter
from app.core.security import has_usable_password
from app.db.session import get_system_session, get_session
from app.models.platform.user import SIGN_IN_STATUSES, User
from app.models.platform.user_passkey import UserPasskey
from app.schemas.platform.passkey import (
    PasskeyAuthenticationOptions,
    PasskeyList,
    PasskeyRead,
    PasskeyRegisterFinish,
    PasskeyRegisterStart,
    PasskeyRegistrationOptions,
    PasskeyRemove,
    PasskeyRename,
    PasskeySignInFinish,
    PasskeySignInResult,
    PasskeySignInStart,
    PasskeyStepUpFinish,
)
from app.schemas.platform.token import Token
from app.services import audit as audit_service
from app.services import email as email_service
from app.services.auth import addresses
from app.services.auth import challenges as challenge_service
from app.services.auth import identity as identity_service
from app.services.auth import passkeys as passkey_service
from app.services.auth.assurance import passkey_amr
from app.services.platform import auth_posture
from app.services.platform import user_tokens

logger = logging.getLogger(__name__)

router = APIRouter()

SystemSessionDep = Annotated[AsyncSession, Depends(get_system_session)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]
#: Adding and removing a way in are done by the person in a session of their
#: own rather than through a standing credential.
FirstPartyOnly = Depends(require_first_party_session)

#: The purposes each finish route will answer for. Kept apart so a ceremony
#: begun for one cannot be finished as the other.
_REGISTER_PURPOSES = (challenge_service.ChallengePurpose.passkey_register,)
_SIGN_IN_PURPOSES = (challenge_service.ChallengePurpose.passkey_sign_in,)
_STEP_UP_PURPOSES = (challenge_service.ChallengePurpose.passkey_step_up,)

#: What a phone's device list shows when the relay page sent no name.
_DEFAULT_DEVICE_NAME = "Mobile Device"


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


def _sign_in_invalid() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=AuthMessages.PASSKEY_SIGN_IN_INVALID,
    )


def _limit_reached() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=AuthMessages.PASSKEY_LIMIT_REACHED,
    )


async def _require_passkeys_offered(session: AsyncSession) -> None:
    """Refuse a ceremony this deployment would not accept — registering a
    credential, or presenting one against a session already open.

    Server-side, so withdrawing the method closes the route rather than only
    hiding its button. The credentials an account already holds are left where
    they are; they simply stop being a way in.
    """
    if not await auth_posture.login_method_allowed(session, LoginMethod.passkey):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthMessages.PASSKEY_NOT_PERMITTED,
        )


def _challenge_from_client_data(
    credential: dict[str, Any], *, refusal: HTTPException
) -> str:
    """The challenge the browser signed, read back out of its own client data.

    The ceremony's response carries the challenge inside the bytes the
    authenticator signed over, so that is where the server reads it from.
    ``refusal`` is what the calling ceremony answers with, so a registration
    and a sign-in each say their own thing.
    """
    response = credential.get("response")
    if not isinstance(response, dict):
        raise refusal
    encoded = response.get("clientDataJSON")
    if not isinstance(encoded, str) or not encoded:
        raise refusal
    try:
        client_data = json.loads(webauthn.base64url_to_bytes(encoded))
    except Exception as exc:
        raise refusal from exc
    challenge = client_data.get("challenge") if isinstance(client_data, dict) else None
    if not isinstance(challenge, str) or not challenge:
        raise refusal
    return challenge


@router.get("/passkeys", response_model=PasskeyList)
async def list_passkeys(
    current_user: FactorExemptUser,
    session: SessionDep,
    system_session: SystemSessionDep,
) -> PasskeyList:
    """The account's passkeys, oldest first."""
    rows = await passkey_service.list_for_user(system_session, user_id=current_user.id)
    return PasskeyList(
        passkeys=[_read(row) for row in rows],
        password_required=has_usable_password(current_user.hashed_password),
        limit=passkey_service.MAX_PASSKEYS_PER_USER,
        site_supported=passkey_service.site_refusal() is None,
        offered=await auth_posture.login_method_allowed(session, LoginMethod.passkey),
    )


@router.post("/passkeys/register/begin", response_model=PasskeyRegistrationOptions)
@limiter.limit("10/15minutes", key_func=get_user_or_ip_key)
async def begin_passkey_registration(
    request: Request,
    current_user: FactorExemptUser,
    session: SessionDep,
    system_session: SystemSessionDep,
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
    await _require_passkeys_offered(session)
    if passkey_service.site_refusal() is not None:
        raise _site_unsupported()
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )

    # What the credential manager lists the account under. The address the
    # person signs in with where there is one, so two entries for the same
    # deployment are told apart; the handle otherwise.
    account_name = (
        await addresses.primary_address(system_session, user_id=current_user.id)
        or current_user.username
    )
    display_name = current_user.full_name or current_user.username

    try:
        ceremony = await passkey_service.begin_registration(
            system_session,
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
        system_session,
        user_id=current_user.id,
        purpose=challenge_service.ChallengePurpose.passkey_register,
        value=bytes_to_base64url(ceremony.challenge),
    )
    await system_session.commit()
    return PasskeyRegistrationOptions(options=ceremony.options)


@router.post(
    "/passkeys/register/finish",
    response_model=PasskeyRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/15minutes", key_func=get_user_or_ip_key)
async def finish_passkey_registration(
    request: Request,
    current_user: FactorExemptUser,
    session: SessionDep,
    system_session: SystemSessionDep,
    payload: PasskeyRegisterFinish,
    _first_party: str = FirstPartyOnly,
) -> PasskeyRead:
    """Keep the credential the browser made, under the name given."""
    await _require_passkeys_offered(session)
    value = _challenge_from_client_data(
        payload.credential, refusal=_registration_invalid()
    )

    challenge = await challenge_service.claim_attempt(
        system_session, value=value, purposes=_REGISTER_PURPOSES
    )
    if challenge is None or challenge.user_id != current_user.id:
        # The attempt is counted whether or not the answer was any good, so
        # the commit comes before the refusal.
        await system_session.commit()
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
        await system_session.commit()
        raise _registration_invalid() from exc

    try:
        row = await passkey_service.store(
            system_session,
            user_id=current_user.id,
            registered=registered,
            name=payload.name,
        )
    except passkey_service.PasskeyLimitReached:
        await system_session.rollback()
        raise _limit_reached() from None

    if not await challenge_service.consume(system_session, challenge):
        # The challenge went elsewhere between the claim and here, so the
        # credential staged against it goes with the transaction.
        await system_session.rollback()
        raise _registration_invalid()

    read = _read(row)
    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_PASSKEY_REGISTERED,
        actor_user_id=current_user.id,
        detail={
            "passkey_id": str(row.id),
            "backed_up": registered.backed_up,
            "user_verified": registered.user_verified,
        },
    )
    await system_session.commit()
    await email_service.announce_passkey_change(
        system_session, current_user, added=True, name=read.name
    )
    return read


@router.patch("/passkeys/{passkey_id}", response_model=PasskeyRead)
@limiter.limit("30/15minutes", key_func=get_user_or_ip_key)
async def rename_passkey(
    request: Request,
    passkey_id: uuid.UUID,
    current_user: CurrentUser,
    system_session: SystemSessionDep,
    payload: PasskeyRename,
    _first_party: str = FirstPartyOnly,
) -> PasskeyRead:
    """Give the credential another name. Nothing about signing in changes."""
    row = await passkey_service.rename(
        system_session,
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
    await system_session.commit()
    return read


@router.post("/passkeys/{passkey_id}/remove", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/15minutes", key_func=get_user_or_ip_key)
async def remove_passkey(
    request: Request,
    passkey_id: uuid.UUID,
    current_user: CurrentUser,
    system_session: SystemSessionDep,
    payload: PasskeyRemove,
    _first_party: str = FirstPartyOnly,
) -> None:
    """Forget the credential. The password is asked for again, as it is for a
    password change, because a way in is being taken away."""
    await require_password_or_recent_proof(
        request, system_session, current_user, payload.current_password
    )

    # A credential is allowed to go while something else still opens a session
    # — another passkey, a password, a provider the deployment answers for.
    # Where it is the whole of that, it stays. A deployment that has withdrawn
    # passkeys leaves such an account with nothing at all, which is the same
    # answer.
    ways = await identity_service.ways_in(system_session, user_id=current_user.id)
    if not (ways - {LoginMethod.passkey}) and (
        await passkey_service.count_for_user(system_session, user_id=current_user.id)
        == 1
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthMessages.PASSKEY_IS_LAST_METHOD,
        )

    # Read the name while the row is still there, so the letter can say which
    # credential went.
    existing = await system_session.get(UserPasskey, passkey_id)
    name = existing.name if existing is not None else ""

    if not await passkey_service.remove(
        system_session, user_id=current_user.id, passkey_id=passkey_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=AuthMessages.PASSKEY_NOT_FOUND,
        )

    await audit_service.record(
        system_session,
        event_type=AuditEventType.AUTH_PASSKEY_REMOVED,
        actor_user_id=current_user.id,
        detail={"passkey_id": str(passkey_id)},
    )
    # Sessions are left alone: the person is where they are and has just
    # proved it.
    await system_session.commit()
    await email_service.announce_passkey_change(
        system_session, current_user, added=False, name=name
    )


@router.post(
    "/passkeys/authenticate/begin", response_model=PasskeyAuthenticationOptions
)
# Every load of a sign-in page on a browser that offers a passkey in its
# autofill spends one of these, so the ceiling is well above the button's.
@limiter.limit("60/15minutes")
async def begin_passkey_sign_in(
    request: Request,
    session: SessionDep,
    system_session: SystemSessionDep,
    payload: PasskeySignInStart,
) -> PasskeyAuthenticationOptions:
    """Options for signing in with a passkey. Nobody is named yet: the
    authenticator offers what it holds for this site, and the assertion that
    comes back says which credential answered."""
    await require_login_method(session, LoginMethod.passkey)

    ceremony = passkey_service.begin_authentication()
    # No account on the row, because none is known: the challenge stands for
    # the ceremony rather than for a person, and the assertion that answers it
    # is what names one. Stored as the browser will write it back — the same
    # unpadded base64url the options carry — so the finish route can look the
    # row up by what it reads out of the signed client data.
    await challenge_service.create(
        system_session,
        user_id=None,
        purpose=challenge_service.ChallengePurpose.passkey_sign_in,
        value=bytes_to_base64url(ceremony.challenge),
    )
    await system_session.commit()
    return PasskeyAuthenticationOptions(options=ceremony.options)


@router.post("/passkeys/authenticate/finish", response_model=PasskeySignInResult)
@limiter.limit("10/15minutes")
async def finish_passkey_sign_in(
    request: Request,
    response: Response,
    session: SessionDep,
    system_session: SystemSessionDep,
    payload: PasskeySignInFinish,
) -> PasskeySignInResult:
    """Open the session a passkey earned — or, for a phone signing in through
    its browser, hand back the address the app is waiting at.

    Every ceremony verifies the person as well as the device, so an assertion
    is a multi-factor authentication on its own and no code is asked for after
    it. What answered is recorded in the session's ``amr``.
    """
    await require_login_method(session, LoginMethod.passkey)

    value = _challenge_from_client_data(payload.credential, refusal=_sign_in_invalid())

    challenge = await challenge_service.claim_attempt(
        system_session, value=value, purposes=_SIGN_IN_PURPOSES
    )
    if challenge is None:
        # The attempt is counted whether or not the answer was any good, so
        # the commit comes before the refusal.
        await system_session.commit()
        raise _sign_in_invalid()

    outcome = await passkey_service.finish_authentication(
        system_session,
        credential=payload.credential,
        expected_challenge=webauthn.base64url_to_bytes(value),
    )
    if isinstance(outcome, passkey_service.AssertionRefusal):
        # Recorded against the account the credential belongs to where the id
        # named a row, and against nobody where it named none — the credential
        # is the only thing that would have said who. The client is answered
        # the same either way. The record commits on its own.
        refused_for = (
            await system_session.get(User, outcome.passkey.user_id)
            if outcome.passkey is not None
            else None
        )
        if outcome.reason == "wrong_rp" and outcome.passkey is not None:
            # Said in the log because it is an operator's answer, not the
            # account's: the deployment moved domain and the credentials made
            # under the old one cannot answer here.
            logger.warning(
                "passkey refused: the credential belongs to %s, "
                "this deployment answers to %s",
                outcome.passkey.rp_id,
                passkey_service.relying_party_id(),
            )
        # A credential this deployment holds no row for, and one made under
        # another domain, say nothing about the account the record names, so
        # neither counts toward the repeated-refusal rule.
        await record_sign_in_failure(
            system_session,
            refused_for,
            method="passkey",
            reason=outcome.reason,
        )
        raise _sign_in_invalid()

    # Read off the credential while the row is attached: the helpers below may
    # roll the transaction back, which expires its attributes.
    passkey_id = str(outcome.passkey.id)
    backed_up = outcome.passkey.backed_up
    account_id = outcome.passkey.user_id

    user = await system_session.get(User, account_id)
    # See SIGN_IN_STATUSES: a deletion is called off by its holder signing in.
    if user is None or user.status not in SIGN_IN_STATUSES:
        # No session to open, so the counter the assertion moved goes back with
        # the transaction and the refusal is recorded on its own. The account
        # is read again because the rollback expired the row. The attempt
        # ``claim_attempt`` counted goes back with it, and the route's own rate
        # limit is what bounds this path.
        await system_session.rollback()
        await record_sign_in_failure(
            system_session,
            await system_session.get(User, account_id),
            method="passkey",
            reason="inactive",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=AuthMessages.INACTIVE_USER
        )
    user_id, token_version = user.id, user.token_version

    if not await challenge_service.consume(system_session, challenge):
        # Spent between the claim and here, so the session it bought is not
        # this request's to open a second time. The counter the assertion moved
        # goes back with the transaction.
        await system_session.rollback()
        raise _sign_in_invalid()

    if payload.mobile:
        # The relay page in the phone's system browser: it hands the app a
        # device token to come back with rather than opening a session of its
        # own, which is the road the SSO mobile login already takes.
        device_name = payload.device_name.strip() or _DEFAULT_DEVICE_NAME
        device_token = await user_tokens.create_device_token(
            system_session,
            user_id=user_id,
            device_name=device_name,
            # What this ceremony proved, kept for the exchange the app makes
            # next: the relay is a sign-in that hands back a token instead of
            # a session, and the session is opened a moment later.
            amr=passkey_amr(backed_up=backed_up),
            commit=False,
        )
        await audit_service.record(
            system_session,
            event_type=AuditEventType.AUTH_DEVICE_TOKEN_ISSUED,
            actor_user_id=user_id,
            detail={"method": "passkey", "device_name": device_name},
        )
        # One commit for the token, the record, the spent challenge and the
        # credential's counter.
        await system_session.commit()
        redirect = urlencode({"token": device_token, "token_type": "device_token"})
        return PasskeySignInResult(redirect_to=f"{MOBILE_CALLBACK_URI}?{redirect}")

    # The spent challenge and the credential's counter commit with the session.
    token = await open_session(
        request,
        response,
        system_session,
        user_id=user_id,
        token_version=token_version,
        amr=passkey_amr(backed_up=backed_up),
        audit_detail={"method": "passkey", "passkey_id": passkey_id},
    )
    return PasskeySignInResult(access_token=token.access_token)


@router.post("/step-up/passkey/begin", response_model=PasskeyAuthenticationOptions)
@limiter.limit("10/15minutes")
async def begin_passkey_step_up(
    request: Request,
    session: SessionDep,
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
    _first_party: str = FirstPartyOnly,
) -> PasskeyAuthenticationOptions:
    """Options for presenting one of this account's passkeys against the
    session already open — the allow-list names the account's own."""
    await _require_passkeys_offered(session)
    # What the ceremony would be added to, asked for before it is begun: the
    # finish route ends in an upgrade, which has nothing to upgrade unless this
    # request is on a session of its own.
    require_session_row(request)

    # Unlike a sign-in, which names nobody, there is already an account here:
    # the browser is asked for one of its credentials rather than for whatever
    # the authenticator holds for this domain. Read once and handed on, so the
    # allow-list and the answer below come from the same read.
    credentials = await passkey_service.list_for_user(
        system_session, user_id=current_user.id
    )
    if not credentials:
        # Nothing to present. The dialog sends the person to the security page
        # to add one rather than opening a prompt that can only fail.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthMessages.PASSKEY_NOT_FOUND,
        )

    ceremony = passkey_service.begin_authentication(credentials=credentials)
    # Bound to the account, the way a registration's challenge is: this
    # ceremony is about a session that already names somebody. Stored as the
    # browser will write it back, so the finish route can look the row up by
    # what it reads out of the signed client data.
    await challenge_service.create(
        system_session,
        user_id=current_user.id,
        purpose=challenge_service.ChallengePurpose.passkey_step_up,
        value=bytes_to_base64url(ceremony.challenge),
    )
    await system_session.commit()
    return PasskeyAuthenticationOptions(options=ceremony.options)


@router.post("/step-up/passkey/finish", response_model=Token)
@limiter.limit("10/15minutes")
async def finish_passkey_step_up(
    request: Request,
    response: Response,
    session: SessionDep,
    current_user: FactorExemptUser,
    system_session: SystemSessionDep,
    payload: PasskeyStepUpFinish,
    _first_party: str = FirstPartyOnly,
) -> Token:
    """Add the passkey to the session already signed in.

    A community that asks for one refuses a session that was not opened with
    one, and signing out to sign back in would be a strange way to answer that.
    The session is upgraded rather than replaced from nothing: what it had
    proved carries forward and the old row is retired, the shape the other
    step-ups take.
    """
    await _require_passkeys_offered(session)

    presented = await passkey_service.present_against_challenge(
        system_session,
        user_id=current_user.id,
        credential=payload.credential,
        purposes=_STEP_UP_PURPOSES,
    )
    if isinstance(presented, passkey_service.PresentationRefused):
        if presented.reason is not None:
            await audit_service.record(
                system_session,
                event_type=AuditEventType.AUTH_SECOND_FACTOR_FAILED,
                actor_user_id=current_user.id,
                detail={
                    "method": "passkey",
                    "during": "step_up",
                    "reason": presented.reason,
                },
            )
        if presented.keep:
            await system_session.commit()
        else:
            await system_session.rollback()
        raise _sign_in_invalid()

    # The spent challenge and the credential's counter commit with the session.
    return await upgrade_session(
        request,
        response,
        system_session,
        user=current_user,
        add_amr=passkey_amr(backed_up=presented.backed_up),
    )
