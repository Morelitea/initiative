"""Re-checking the account's password before it changes how it is signed into.

Shared by the routes that add or take away a way in — the second factor and
the passkeys — so both ask the same question in the same words.
"""

from typing import Optional

from fastapi import HTTPException, status

from app.core.messages import UserMessages
from app.core.security import has_usable_password, verify_password
from app.models.platform.user import User


def require_password(
    user: User, supplied: Optional[str], *, detail: Optional[str] = None
) -> None:
    """Re-check the password, as a password change does.

    The exemption is for an account that holds no password to re-check — one
    provisioned through an identity provider, one that signs in with a passkey.
    Holding a federated identity is not the same question: an account can have
    both, and one that has a password is asked for it. Nor is "the column is
    NULL": a hash no scheme verifies is not a password either, and asking for
    one nobody can supply would shut the account out of its own settings.

    ``detail`` is the one code to answer with, for a form that reads a missing
    password and a wrong one as the same refusal. Left unset, the two are told
    apart — which is what a field asking for the current password wants.
    """
    if not has_usable_password(user.hashed_password):
        return
    if not supplied:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail or UserMessages.CURRENT_PASSWORD_REQUIRED,
        )
    if not verify_password(supplied, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail or UserMessages.CURRENT_PASSWORD_INCORRECT,
        )
