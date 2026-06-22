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
