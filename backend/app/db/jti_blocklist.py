"""Shared purge for one-shot ``jti`` replay-guard tables.

Every jti blocklist in the app — the billing service JWT blocklist
(``billing_jti_blocklist``) and the initiative-auto delegation blocklist
(``auto_delegation_jti_blocklist``) — is the same shape: a ``jti`` primary
key plus an ``expires_at`` mirroring the token's own ``exp``. Each row is a
spent one-shot token, and it is **inert once expired** — the token's ``exp``
is checked at verification, before the blocklist is ever consulted, so a
replay of an expired token is refused whether or not its row still exists.
Purging expired rows therefore never re-opens a replay window; it only
bounds table growth.

Both janitors delegate here rather than re-implementing the DELETE, so the
"purge is safe because exp already refuses replay" invariant lives in one
place. Runs on the system engine (``app_admin`` holds DELETE per
``app/db/system_grants.py``); the scoped request roles never delete.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import SQLModel, delete
from sqlmodel.ext.asyncio.session import AsyncSession


async def purge_expired_jtis(session: AsyncSession, model: type[SQLModel]) -> int:
    """Delete blocklist rows whose ``expires_at`` has passed; return the count.

    ``model`` must expose an ``expires_at`` column (both jti models do). Owns
    its transaction — commits — since a janitor runs on its own session.
    """
    result = await session.exec(
        delete(model).where(model.expires_at < datetime.now(timezone.utc))
    )
    await session.commit()
    return result.rowcount or 0
