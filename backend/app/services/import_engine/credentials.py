"""The whole life of an import credential: store it, read it once, drop it.

A fetch from a foreign site needs a secret that was typed into the connect
step of a wizard, minutes before the worker gets to the job. This module is
the only thing that holds it in between.

**Its own session, always.** Every function here opens an *unrouted* system
session of its own rather than accepting the caller's. The worker's session is
routed into a guild schema, and ``SET ROLE`` drops the system engine's
bypass — under a ``guild_<id>`` role this table has neither a grant nor a
policy, so a read there would find nothing at all. The unrouted system engine
is the only actor that can see a row, which is exactly the boundary the table
was given.

**One-shot.** ``store`` is the only way a row appears, ``load`` is the only way
one is read, and both ``discard`` and ``sweep_expired`` end it. Nothing
updates a row: a credential that needs to change is a new connect request.
Callers are expected to ``discard`` at every terminal transition; the sweep is
the backstop for the ones that never got there.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken
from sqlalchemy import delete
from sqlmodel import select

from app.core.config import settings
from app.core.encryption import SALT_IMPORT_CREDENTIAL, decrypt_field, encrypt_field
from app.db import session as db_session
from app.db.session import set_rls_context
from app.models.platform.import_credential import ImportCredential

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedCredential:
    """A credential read back, with its secret in the clear.

    Held only for the length of the call that asked for it. Nothing here is
    ever written to a job row, a log line, or a report — an import job records
    codes and counts, never content, and a credential is the most content-like
    thing in the whole flow.
    """

    id: int
    guild_id: int
    created_by: int
    provider: str
    site_url: str
    principal: str
    secret: str


def _expiry(now: datetime) -> datetime:
    """When a stored credential stops being usable.

    The staged-payload TTL, deliberately: the credential and the job it
    belongs to should go stale at the same moment, so there is never a window
    where one of the two is still good.
    """
    return now + timedelta(hours=settings.IMPORT_STAGED_TTL_HOURS)


async def store(
    *,
    guild_id: int,
    user_id: int,
    provider: str,
    site_url: str,
    principal: str,
    secret: str,
) -> int:
    """Hold a credential for one import and return the id that names it.

    The id is what a job row carries in its params. The secret itself never
    leaves this module's return values.
    """
    now = datetime.now(timezone.utc)
    row = ImportCredential(
        guild_id=guild_id,
        created_by=user_id,
        provider=provider,
        site_url=site_url,
        principal=principal,
        secret_encrypted=encrypt_field(secret, SALT_IMPORT_CREDENTIAL),
        expires_at=_expiry(now),
        created_at=now,
    )
    async with db_session.AdminSessionLocal() as session:
        await set_rls_context(session)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def load(credential_id: int, *, guild_id: int) -> LoadedCredential | None:
    """The credential this job was given, or ``None``.

    ``None`` covers every way a row can fail to be usable, and the caller
    treats them alike — there is one honest answer for "the credential is
    gone", and asking why would only tell an operator something the audit
    trail already says:

    * it was already discarded, or swept;
    * it belongs to another guild (an id from a job row is data, so the guild
      is checked rather than assumed);
    * its own deadline has passed;
    * it no longer decrypts, which is what a ``SECRET_KEY`` rotation
      mid-import looks like.
    """
    async with db_session.AdminSessionLocal() as session:
        await set_rls_context(session)
        row = (
            await session.exec(
                select(ImportCredential).where(
                    ImportCredential.id == credential_id,
                    ImportCredential.guild_id == guild_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        if row.expires_at <= datetime.now(timezone.utc):
            return None
        try:
            secret = decrypt_field(row.secret_encrypted, SALT_IMPORT_CREDENTIAL)
        except InvalidToken:
            logger.warning(
                "import credential id=%s guild=%s no longer decrypts",
                credential_id,
                guild_id,
            )
            return None
        return LoadedCredential(
            id=row.id,
            guild_id=row.guild_id,
            created_by=row.created_by,
            provider=row.provider,
            site_url=row.site_url,
            principal=row.principal,
            secret=secret,
        )


async def discard(credential_id: int | None) -> None:
    """Drop a credential the moment its job is over.

    Best-effort and idempotent, like the staged-payload delete it sits beside:
    a failing delete must not be what fails a job transition, because the row
    has a deadline of its own and the sweep will take it.
    """
    if credential_id is None:
        return
    try:
        async with db_session.AdminSessionLocal() as session:
            await set_rls_context(session)
            await session.exec(
                delete(ImportCredential).where(ImportCredential.id == credential_id)
            )
            await session.commit()
    except Exception:  # pragma: no cover - backend-specific failures
        logger.exception(
            "import credential id=%s could not be discarded", credential_id
        )


async def sweep_expired() -> int:
    """Remove every credential past its deadline; returns how many went.

    The backstop under the lifecycle above, for the jobs that never reached a
    transition to be cleaned up by — a crashed connect, a wizard somebody
    closed, a worker that died between claiming and finishing.
    """
    async with db_session.AdminSessionLocal() as session:
        await set_rls_context(session)
        result = await session.exec(
            delete(ImportCredential).where(
                ImportCredential.expires_at <= datetime.now(timezone.utc)
            )
        )
        await session.commit()
    removed = result.rowcount or 0
    if removed:
        logger.info("swept %s expired import credential(s)", removed)
    return removed
