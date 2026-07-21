from app.schemas.base import SanitizedBaseModel

from typing import Optional


class Token(SanitizedBaseModel):
    access_token: str
    token_type: str = "bearer"


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
