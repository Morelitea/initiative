"""Wire shapes of the app platform's token endpoint and install listing.

The token endpoint speaks OAuth 2.0 (RFC 6749): its success and error bodies
are the ones that specification defines, and an error's ``error`` is a
protocol value rather than text for a person to read.
"""

from typing import List

from pydantic import BaseModel


class AppAccessTokenResponse(BaseModel):
    """A successful token response (RFC 6749 §5.1)."""

    access_token: str
    token_type: str = "Bearer"
    #: Seconds until the token stops being accepted.
    expires_in: int
    #: The scopes the token carries, space-separated. Empty for an app token.
    scope: str


class AppOAuthErrorResponse(BaseModel):
    """An error response (RFC 6749 §5.2)."""

    error: str
    error_description: str


class AppInstallationRead(BaseModel):
    """One install of the calling app."""

    #: What the app calls the community it is installed in. Passed back as
    #: ``installation`` to ask for a token there.
    installation: str
    #: The scopes the community has granted it.
    scopes: List[str]
    #: The initiatives it is placed in.
    initiatives: List[int]
