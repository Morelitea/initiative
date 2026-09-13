"""Payloads for the delegation exchange (``history/opaque-identity-design.md`` §12)."""

from __future__ import annotations

from pydantic import Field

from app.schemas.base import SanitizedBaseModel
from app.services.marketplace.app_channel_auth import MAX_APP_ID_LENGTH


class DelegationExchangeRequest(SanitizedBaseModel):
    """Which app the caller is about to act at.

    Named by its public id — the same one its registration carries and its
    audience is built from. Nothing else is sent: the guild and the member come
    from the token the request was made with, so a caller cannot ask for a
    token about somebody it was not already carrying.
    """

    audience: str = Field(min_length=1, max_length=MAX_APP_ID_LENGTH)


class DelegationExchangeResponse(SanitizedBaseModel):
    """The re-addressed token, and how long it is good for."""

    token: str
    expires_in_seconds: int
