"""What a request's credential is, as far as can be told without the database.

The half of ``app.services.auth.credentials`` that needs no database: tells the
kinds apart and checks what can be checked locally — a session or upload
token's signature, audience and expiry, an installed app's seal. Personal API
keys are opaque here; only their lookup can say whom they name.

Read before any dependency runs, by the rate limiter and by the choice of
database pool, so both name the request the way authentication will. Naming
grants nothing: a credential admits a request only once
``credentials.authenticate`` has checked it against the database.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

import jwt
from starlette.requests import HTTPConnection

from app.core.app_access_token import (
    AccessTokenError,
    AppAccessToken,
    InstallAccessToken,
    is_access_token,
    unseal_access_token,
)
from app.core.messages import AuthMessages
from app.core.security import (
    SESSION_COOKIE_NAME,
    UploadTokenError,
    decode_session_token,
    verify_upload_token,
)
from app.schemas.platform.token import TokenPayload


class CredentialKind(str, Enum):
    """Which kind of credential authenticated a request."""

    #: An access token for a server-side session.
    session = "session"
    #: A personal API key.
    api_key = "api_key"
    #: A short-lived token that reaches ``/uploads`` and nothing else.
    upload_token = "upload_token"


#: What an ``Authorization: Bearer`` header or the session cookie may carry.
HEADER_CREDENTIALS = frozenset({CredentialKind.session, CredentialKind.api_key})
#: What may ride in a URL: only the narrow token minted to travel this way; a
#: session token or an API key never does.
URL_CREDENTIALS = frozenset({CredentialKind.upload_token})
#: What a realtime socket's first frame may carry.
SOCKET_CREDENTIALS = frozenset({CredentialKind.session})


class VerifiedUpload(NamedTuple):
    """What an upload token carries, copied from the session that minted it."""

    user_id: int
    satisfied: frozenset[int]
    claims: dict
    markers: frozenset[str]


@dataclass(frozen=True)
class Identified:
    """A credential, read locally.

    At most one of ``session``, ``upload`` and ``access`` is set, or
    ``refused``; with none of them the credential is opaque — an API key, for
    the database to name.
    """

    token: str
    allow: frozenset[CredentialKind]
    #: Whether it arrived in an ``Authorization: Bearer`` header, the only
    #: place an installed app's token is read from.
    bearer: bool = False
    session: TokenPayload | None = None
    upload: VerifiedUpload | None = None
    access: InstallAccessToken | AppAccessToken | None = None
    #: Why it was refused, when its local check failed.
    refused: str | None = None

    @property
    def app_token(self) -> InstallAccessToken | AppAccessToken | None:
        """The installed app's or app's token, when it came as a bearer."""
        return self.access if self.bearer else None

    @property
    def limit_key(self) -> str | None:
        """Whom the rate limiter counts this request against, or ``None`` when
        nobody can be named without the database."""
        if self.session is not None:
            return f"subject:{self.session.sub}"
        if self.upload is not None:
            return f"user:{self.upload.user_id}"
        token = self.app_token
        if isinstance(token, InstallAccessToken):
            return f"install:{token.client_id}:{token.guild_id}:{token.install_id}"
        if isinstance(token, AppAccessToken):
            return f"app:{token.client_id}"
        return None


def _is_a_jwt(token: str) -> bool:
    """Whether ``token`` is a JWT, whatever it says and whoever signed it."""
    try:
        jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        return False
    return True


def identify_token(
    token: str, allow: frozenset[CredentialKind], *, bearer: bool = False
) -> Identified:
    """Read ``token`` as one of the kinds in ``allow``, locally.

    The kinds tell themselves apart without being told: an installed app's
    token by its prefix, the two token kinds by being JWTs with their own
    audiences, and an API key by being neither.
    """
    if is_access_token(token):
        try:
            access = unseal_access_token(token)
        except AccessTokenError:
            return Identified(
                token,
                allow,
                bearer=bearer,
                refused=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            )
        return Identified(token, allow, bearer=bearer, access=access)
    if not _is_a_jwt(token):
        return Identified(token, allow, bearer=bearer)
    if CredentialKind.upload_token in allow:
        try:
            upload = VerifiedUpload(*verify_upload_token(token))
        except UploadTokenError:
            pass
        else:
            return Identified(token, allow, bearer=bearer, upload=upload)
    if CredentialKind.session in allow:
        try:
            payload = TokenPayload(**decode_session_token(token))
        except jwt.PyJWTError:
            return Identified(
                token,
                allow,
                bearer=bearer,
                refused=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS,
            )
        if not payload.sub:
            return Identified(
                token, allow, bearer=bearer, refused=AuthMessages.INVALID_TOKEN_PAYLOAD
            )
        return Identified(token, allow, bearer=bearer, session=payload)
    return Identified(
        token, allow, bearer=bearer, refused=AuthMessages.COULD_NOT_VALIDATE_CREDENTIALS
    )


def identify(connection: HTTPConnection) -> Identified | None:
    """The credential a request's bearer header or session cookie carries,
    read once: a session or a personal API key. ``None`` when there is none.
    """
    if hasattr(connection.state, "identified"):
        return connection.state.identified
    scheme, _, param = connection.headers.get("authorization", "").partition(" ")
    identified: Identified | None
    if scheme.lower() == "bearer" and param:
        identified = identify_token(param, HEADER_CREDENTIALS, bearer=True)
    else:
        cookie = connection.cookies.get(SESSION_COOKIE_NAME)
        identified = identify_token(cookie, HEADER_CREDENTIALS) if cookie else None
    connection.state.identified = identified
    return identified


def bearer_app_token(
    connection: HTTPConnection,
) -> InstallAccessToken | AppAccessToken | None:
    """The installed app's or app's token in the request's bearer header,
    unsealed. ``None`` when there is none or it does not unseal."""
    identified = identify(connection)
    return identified.app_token if identified is not None else None


def identify_url_token(connection: HTTPConnection) -> Identified | None:
    """The credential a request's ``?token=`` carries, as what a URL may
    carry, read once. ``None`` when there is none."""
    if hasattr(connection.state, "identified_url"):
        return connection.state.identified_url
    token = connection.query_params.get("token")
    identified = identify_token(token, URL_CREDENTIALS) if token else None
    connection.state.identified_url = identified
    return identified
