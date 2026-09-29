"""Reading the credential a request presents.

One reader for every transport. The HTTP dependency, the ``/uploads`` route and
the realtime sockets each decide which kinds of credential they accept and how
a refusal reaches the client; what a credential *is*, which account it names,
and what it records about the sign-in behind it are decided here, once.

What it records goes to ``app.core.auth_context``: the providers a session
satisfied and what they asserted, the markers its ``amr`` carries, which device
token or session it was, and whether it was a personal API key and the guild
that key is limited to. Everything is cleared first, so a credential of another
kind never inherits what a previous one recorded.

Nothing here reads the account's status. Who may hold a session is the caller's
question, asked with the account in hand.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

import jwt
from fastapi import HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.app_access_token import is_access_token
from app.core.auth_context import (
    SessionCredential,
    claims_from_provider_auth,
    set_api_key_credential,
    set_api_key_guild_id,
    set_asked_of_account,
    set_device_token_id,
    set_satisfied_claims,
    set_satisfied_providers,
    set_session_amr,
    set_session_credential,
)
from app.core.login_methods import SecondFactorRequirement
from app.core.messages import AuthMessages
from app.core.security import (
    UploadTokenError,
    decode_session_token,
    verify_upload_token,
)
from app.models.platform.api_key import UserApiKey
from app.models.platform.app_setting import AppSetting
from app.models.platform.user import User
from app.schemas.platform.token import TokenPayload
from app.services.auth.assurance import policy_markers
from app.services.auth.subject import account_for_subject
from app.services.platform import api_keys as api_keys_service
from app.services.platform import auth_posture
from app.services.platform import user_tokens


class CredentialKind(str, Enum):
    """Which kind of credential authenticated a request."""

    #: An access token for a server-side session.
    session = "session"
    #: A personal API key.
    api_key = "api_key"
    #: The native app's long-lived device token.
    device_token = "device_token"
    #: A short-lived token that reaches ``/uploads`` and nothing else.
    upload_token = "upload_token"


#: What an ``Authorization: Bearer`` header or the session cookie may carry.
HEADER_CREDENTIALS = frozenset({CredentialKind.session, CredentialKind.api_key})
#: What the ``DeviceToken`` scheme carries.
DEVICE_TOKEN_SCHEME = frozenset({CredentialKind.device_token})
#: What may ride in a URL. Only credentials that are narrow or already meant to
#: travel this way; a session token or an API key never does.
URL_CREDENTIALS = frozenset({CredentialKind.upload_token, CredentialKind.device_token})
#: What a realtime socket's first frame may carry.
SOCKET_CREDENTIALS = frozenset({CredentialKind.session, CredentialKind.device_token})


@dataclass(frozen=True)
class Authenticated:
    """The account a credential names, and what the credential was."""

    user: User
    kind: CredentialKind
    #: The ``auth_sessions`` row a session token names, where it names one.
    session_id: uuid.UUID | None = None
    #: The key, for a personal API key; its scope is the caller's to apply.
    api_key: UserApiKey | None = None


class CredentialRefused(Exception):
    """The credential names nobody, or nobody who may use it here."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int = status.HTTP_401_UNAUTHORIZED,
        scheme: str = "Bearer",
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.scheme = scheme

    def as_http(self) -> HTTPException:
        headers = (
            {"WWW-Authenticate": self.scheme}
            if self.status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        return HTTPException(
            status_code=self.status_code, detail=self.detail, headers=headers
        )


def clear_recorded_credential() -> None:
    """Forget whatever a previous credential recorded for this request."""
    set_satisfied_providers(None)
    set_satisfied_claims(None)
    set_session_amr(None)
    set_session_credential(None)
    set_device_token_id(None)
    set_api_key_credential(False)
    set_api_key_guild_id(None)
    set_asked_of_account(None)


def asked_of_an_account(settings_row: AppSetting | None) -> SecondFactorRequirement:
    """What the deployment asks of an account, from the settings row.

    A database with no singleton yet asks nothing — the same conclusion
    ``public.platform_factor_satisfied()`` reaches from the same absence, so
    the two layers agree on a deployment that has not finished starting.
    """
    if settings_row is None:
        return SecondFactorRequirement.nobody
    return auth_posture.requirement_from_row(settings_row)


def _is_a_jwt(token: str) -> bool:
    """Whether ``token`` is a JWT, whatever it says and whoever signed it."""
    try:
        jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return False
    return True


def _session_row_id(sid: str | None) -> uuid.UUID | None:
    if not sid:
        return None
    try:
        return uuid.UUID(sid)
    except ValueError:
        return None


_UNREADABLE = AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS


async def _session(session: AsyncSession, token: str) -> Authenticated:
    try:
        token_data = TokenPayload(**decode_session_token(token))
    except jwt.PyJWTError as exc:
        raise CredentialRefused(_UNREADABLE) from exc
    if not token_data.sub:
        raise CredentialRefused(AuthMessages.INVALID_TOKEN_PAYLOAD)
    account = await account_for_subject(session, subject=token_data.sub)
    if account is None:
        raise CredentialRefused(
            AuthMessages.USER_NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND
        )
    user, settings_row = account
    # ``ver`` is what signing out everywhere moves.
    if token_data.ver is None or token_data.ver != user.token_version:
        raise CredentialRefused(AuthMessages.INVALID_TOKEN)
    session_id = _session_row_id(token_data.sid)
    set_satisfied_providers(frozenset(token_data.sat or ()))
    set_satisfied_claims(claims_from_provider_auth(token_data.satd))
    # What the sign-in wrote about how it was made — the second-factor marker
    # where a code was presented, the passkey markers where a key answered.
    set_session_amr(policy_markers(token_data.amr))
    set_asked_of_account(asked_of_an_account(settings_row))
    if session_id is not None:
        set_session_credential(
            SessionCredential(session_id=session_id, token_version=token_data.ver)
        )
    return Authenticated(user=user, kind=CredentialKind.session, session_id=session_id)


async def _upload_token(session: AsyncSession, token: str) -> Authenticated | None:
    try:
        user_id, satisfied, claims, markers = verify_upload_token(token)
    except UploadTokenError:
        return None
    user = (await session.exec(select(User).where(User.id == user_id))).one_or_none()
    if user is None:
        raise CredentialRefused(
            AuthMessages.USER_NOT_FOUND, status_code=status.HTTP_404_NOT_FOUND
        )
    # The scoped token copied its minting session's satisfied set and markers,
    # so a policy-gated guild treats this request as that session.
    set_satisfied_providers(satisfied)
    set_satisfied_claims(claims)
    set_session_amr(policy_markers(markers))
    return Authenticated(user=user, kind=CredentialKind.upload_token)


async def _device_token(session: AsyncSession, token: str) -> Authenticated | None:
    # Resolved on the system engine, as a personal API key is; the account it
    # names is loaded on the request's own session.
    device_token = await user_tokens.authenticate_device_token(token)
    if device_token is None:
        return None
    user = (
        await session.exec(select(User).where(User.id == device_token.user_id))
    ).one_or_none()
    if user is None:
        return None
    # The server's only durable name for one installed client.
    set_device_token_id(device_token.id)
    return Authenticated(user=user, kind=CredentialKind.device_token)


async def _api_key(session: AsyncSession, token: str) -> Authenticated | None:
    found = await api_keys_service.authenticate_api_key(session, token)
    if found is None:
        return None
    user, api_key = found
    set_api_key_credential(True)
    set_api_key_guild_id(api_key.guild_id)
    return Authenticated(user=user, kind=CredentialKind.api_key, api_key=api_key)


async def authenticate(
    session: AsyncSession,
    token: str,
    *,
    allow: frozenset[CredentialKind],
) -> Authenticated:
    """The account ``token`` names, as one of the kinds in ``allow``.

    Raises :class:`CredentialRefused` for anything else. An installed app's
    access token is never a person and is refused whatever ``allow`` says; a
    route that admits one reads it elsewhere.

    The kinds tell themselves apart without being told: an API key by its
    prefix, the two token kinds by being JWTs with their own audiences, and a
    device token by being none of those. A string that is a JWT is only ever
    read as one, so a session token that fails is never offered to the device
    token lookup.
    """
    clear_recorded_credential()
    if allow == DEVICE_TOKEN_SCHEME:
        # Named by its scheme, so it is looked up as nothing else.
        found = await _device_token(session, token)
        if found is None:
            raise CredentialRefused(
                AuthMessages.INVALID_DEVICE_TOKEN, scheme="DeviceToken"
            )
        return found
    if is_access_token(token):
        raise CredentialRefused(_UNREADABLE)

    if token.startswith(api_keys_service.API_KEY_PREFIX):
        found = (
            await _api_key(session, token) if CredentialKind.api_key in allow else None
        )
        if found is None:
            raise CredentialRefused(_UNREADABLE)
        return found

    if _is_a_jwt(token):
        if CredentialKind.upload_token in allow:
            found = await _upload_token(session, token)
            if found is not None:
                return found
        if CredentialKind.session in allow:
            return await _session(session, token)
        raise CredentialRefused(_UNREADABLE)

    if CredentialKind.device_token in allow:
        found = await _device_token(session, token)
        if found is not None:
            return found
    raise CredentialRefused(_UNREADABLE)
