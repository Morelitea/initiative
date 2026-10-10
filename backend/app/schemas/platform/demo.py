from typing import Optional

from pydantic import Field

from app.schemas.base import SanitizedBaseModel
from app.schemas.platform.token import Token


class DemoRedeem(SanitizedBaseModel):
    """A demo link's token, read from the link's fragment."""

    token: str = Field(min_length=1, max_length=128)
    captcha_token: Optional[str] = None


class DemoRedemption(Token):
    """A visitor signed in to their own copy of the pitch.

    The copy is filled in the background by the import ``import_job_id``
    names; the account and its session end when the copy does.
    """

    community_id: int
    import_job_id: int
