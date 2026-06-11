"""Password policy enforcement for new and changed passwords.

Aligned with NIST SP 800-63B (rev. 3, 2017):

  - Minimum length 12. The schema layer enforces ``max_length=256``
    so an over-long payload is rejected before it ever reaches argon2
    or HIBP.
  - No character-class requirements (mandated complexity rules push
    users toward predictable patterns and reduce real entropy).
  - Reject passwords present in known breach corpora.

The login path is intentionally NOT routed through this module —
existing users with shorter or breached passwords keep working until
the next time they change one ("grandfathered"). All new password
material flows (register, password reset, self-update, admin-update)
must call ``validate_new_password`` immediately before hashing.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from app.core.messages import PasswordMessages
from app.services import hibp


# Mirrored by ``frontend/src/lib/passwordPolicy.ts`` — keep both in sync
# when you change the floor. The schemas hold no ``min_length`` of their
# own; short passwords reach the policy here and surface a flat
# ``PASSWORD_TOO_SHORT`` code rather than Pydantic's structured detail.
# The schema-level ``max_length=256`` does fire first for over-long
# input, by design — see ``hibp.is_password_breached`` and the
# argon2 cost of hashing huge payloads.
PASSWORD_MIN_LENGTH = 12


class PasswordPolicyError(Exception):
    """Raised when a candidate password fails the policy.

    ``code`` is one of the ``PasswordMessages`` constants and is the
    same string the endpoint uses as the ``HTTPException`` detail, so
    the frontend can map it via ``errors.json``.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


async def validate_new_password(password: str) -> None:
    """Validate a candidate password or raise ``PasswordPolicyError``.

    Order matters: cheap local check first, network check last, so
    obviously-short inputs never reach HIBP.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(PasswordMessages.TOO_SHORT)
    if await hibp.is_password_breached(password):
        raise PasswordPolicyError(PasswordMessages.BREACHED)


async def enforce_password_policy(password: str) -> None:
    """Endpoint-facing wrapper that converts ``PasswordPolicyError`` into
    an ``HTTPException`` with the policy code as ``detail``.

    Use this from API handlers; reserve ``validate_new_password`` for
    callers that want to handle the exception themselves (services,
    scripts, tests).
    """
    try:
        await validate_new_password(password)
    except PasswordPolicyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.code,
        ) from exc
