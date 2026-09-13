"""What an access token's ``sub`` names, and how it resolves back.

An access token names the account by a reference rather than by the row id —
the ``client`` sector of ``services.platform.identity_refs``. Audit rows,
joins and our own logs keep the integer, which is what they are for.

Two forms are accepted while tokens minted by an earlier build are still in
hand: a reference, and the decimal row id every legacy token carries. The
legacy form goes when the legacy token does.

Resolution runs on the request-path session — the same single indexed query
that read ``users`` before. ``identity_refs`` is otherwise system-engine-only;
the grant and the policy that admit this lookup are scoped to this sector
alone (migration ``20260913_0267``).
"""

from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.platform.identity_ref import (
    REF_MAX_LENGTH,
    IdentityEntity,
    IdentityPurpose,
    IdentityRef,
)
from app.models.platform.user import User
from app.services.platform.identity_refs import ensure_ref

__all__ = ["MAX_ROW_ID", "subject_for_user", "user_for_subject"]

#: The widest value ``users.id`` holds. A legacy subject above it is not an
#: account, and comparing it would be handed to Postgres as an out-of-range
#: integer rather than as a query that finds nothing.
MAX_ROW_ID = 2**31 - 1


async def subject_for_user(session: AsyncSession, *, user_id: int) -> str:
    """The reference this account's tokens name it by, minting on first use.

    Takes the caller's session — every mint site already holds a system-engine
    one for the session write — so the reference lands in the same transaction
    as the sign-in that needed it.
    """
    return await ensure_ref(
        session,
        entity_type=IdentityEntity.user,
        entity_id=user_id,
        purpose=IdentityPurpose.client,
    )


async def user_for_subject(session: AsyncSession, *, subject: str) -> User | None:
    """Which account a token's ``sub`` names, or None.

    Live references only, and nothing re-issues one in this sector. A token
    holding a replaced reference resolves to nobody until it lapses: the
    caller turns that into 404, and the SPA renews on 401 alone. Wiring
    re-issue up means settling that first.
    """
    if not subject or len(subject) > REF_MAX_LENGTH:
        return None

    if subject.isascii() and subject.isdigit():
        row_id = int(subject)
        if row_id > MAX_ROW_ID:
            return None
        statement = select(User).where(User.id == row_id)
    else:
        statement = (
            select(User)
            .join(IdentityRef, IdentityRef.entity_id == User.id)
            .where(
                IdentityRef.ref == subject,
                IdentityRef.entity_type == IdentityEntity.user,
                IdentityRef.purpose == IdentityPurpose.client,
                IdentityRef.retired_at.is_(None),
            )
        )
    return (await session.exec(statement)).one_or_none()
