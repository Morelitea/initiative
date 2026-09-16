from app.schemas.base import SanitizedBaseModel

from typing import Optional


class Token(SanitizedBaseModel):
    access_token: str
    token_type: str = "bearer"
    #: Returned only to a caller that presented its refresh token in the body
    #: rather than as a cookie — a native client, which keeps it in the
    #: platform's secure storage and so needs the rotated one back. A browser
    #: gets it as a cookie it never reads, and this stays absent.
    refresh_token: Optional[str] = None


class SessionAssurance(SanitizedBaseModel):
    """One provider's account of the authentication it performed, as carried
    in the access token's ``satd`` claim (see ``services.auth.assurance``)."""

    auth_time: Optional[int] = None
    amr: list[str] = []
    acr: Optional[str] = None


class TokenPayload(SanitizedBaseModel):
    sub: Optional[str] = None
    exp: Optional[int] = None
    iat: Optional[int] = None
    ver: Optional[int] = None
    # New-model session claims (absent on legacy tokens): the server-side
    # session id, satisfied auth methods, and satisfied provider ids — the
    # guild auth-policy gate reads ``sat``.
    sid: Optional[str] = None
    amr: Optional[list[str]] = None
    sat: Optional[list[int]] = None
    # Per-provider detail behind ``sat``, keyed by provider id as a string.
    # Absent when no provider contributed one (a password session).
    satd: Optional[dict[str, SessionAssurance]] = None
