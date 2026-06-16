"""One-shot, re-runnable SECRET_KEY rotation.

``SECRET_KEY`` roots every Fernet-encrypted field (emails, OIDC client secret +
refresh tokens, SMTP password, AI API keys) and the ``users.email_hash`` HMAC. It
is NOT a JWT signing key (that's the separately-rotatable ``JWT_SIGNING_KEY``), so
rotating it means re-encrypting at-rest data — it cannot be swapped in place.

This module re-encrypts every such value from the OLD key (``PREVIOUS_SECRET_KEY``)
to the NEW key (``SECRET_KEY``), and recomputes each ``email_hash`` from the new key.

Idempotent + resumable: each value is tried under the NEW key first (already rotated
→ skipped), so a second run is a no-op and an interrupted run resumes cleanly. A
value that decrypts under NEITHER key was already unreadable before rotation, so it
is counted and skipped (loud WARNING) rather than aborting — one corrupt legacy row
can't block the sweep (or, at startup, the whole deploy).

Runs two ways:
  * **Automatically at startup** when ``PREVIOUS_SECRET_KEY`` is set (see
    ``app.main.on_startup``), after guild schemas are provisioned and before traffic
    is served — so a packaged deploy rotates itself: set the two env vars, redeploy,
    then UNSET ``PREVIOUS_SECRET_KEY`` once the logs report 0 failures.
  * **Manually** for an explicit/preview run::

        # 1. stop the app
        # 2. set PREVIOUS_SECRET_KEY=<old>, SECRET_KEY=<new>  (new: openssl rand -hex 32)
        python -m app.db.secret_key_rotation --dry-run   # preview counts, no writes
        python -m app.db.secret_key_rotation             # rotate
        # 3. restart, confirm login / SMTP / AI keys work, then UNSET PREVIOUS_SECRET_KEY

Schema-per-guild: ``guild_settings`` is guild-scoped, so its live rows live in every
``guild_<id>`` schema (plus a retained ``public`` backup copy from the conversion);
the sweep visits both. Runs on the provisioning (superuser) engine so it reaches
every guild schema and bypasses RLS.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import settings
from app.core.encryption import (
    SALT_AI_API_KEY,
    SALT_EMAIL,
    SALT_OIDC_CLIENT_SECRET,
    SALT_OIDC_REFRESH_TOKEN,
    SALT_SMTP_PASSWORD,
    decrypt_field,
    encrypt_field,
    hash_email,
)
from app.db import session as db_session
from app.db.schema_provisioning import guild_schema_name

logger = logging.getLogger(__name__)

# Every Fernet column EXCEPT users.email_encrypted, which is handled specially
# because its plaintext also feeds the email_hash HMAC (the two must move together).
# (table, column, salt). All live in ``public``; guild_settings additionally lives in
# each guild schema (see _GUILD_SCHEMA_COLUMNS).
_PUBLIC_FERNET_COLUMNS: list[tuple[str, str, bytes]] = [
    ("users", "ai_api_key_encrypted", SALT_AI_API_KEY),
    ("users", "oidc_refresh_token_encrypted", SALT_OIDC_REFRESH_TOKEN),
    ("app_settings", "oidc_client_secret_encrypted", SALT_OIDC_CLIENT_SECRET),
    ("app_settings", "smtp_password_encrypted", SALT_SMTP_PASSWORD),
    ("app_settings", "ai_api_key_encrypted", SALT_AI_API_KEY),
    ("guild_invites", "invitee_email_encrypted", SALT_EMAIL),
    # Retained public backup copy of the (now guild-scoped) guild_settings rows.
    ("guild_settings", "ai_api_key_encrypted", SALT_AI_API_KEY),
]

# Columns rotated once per ``guild_<id>`` schema (the live copies).
_GUILD_SCHEMA_COLUMNS: list[tuple[str, str, bytes]] = [
    ("guild_settings", "ai_api_key_encrypted", SALT_AI_API_KEY),
]


@dataclass
class ColumnResult:
    schema: str
    table: str
    column: str
    rotated: int = 0
    skipped: int = 0  # already under the new key (idempotent re-run)
    failed: int = 0  # decryptable under neither key — already unreadable


@dataclass
class RotationSummary:
    columns: list[ColumnResult] = field(default_factory=list)
    dry_run: bool = False

    @property
    def rotated(self) -> int:
        return sum(c.rotated for c in self.columns)

    @property
    def skipped(self) -> int:
        return sum(c.skipped for c in self.columns)

    @property
    def failed(self) -> int:
        return sum(c.failed for c in self.columns)

    def render(self) -> str:
        head = (
            f"secret-key rotation {'(dry run) ' if self.dry_run else ''}"
            f"— {self.rotated} rotated, {self.skipped} already-current, "
            f"{self.failed} unreadable"
        )
        lines = [
            f"  {c.schema}.{c.table}.{c.column}: "
            f"{c.rotated} rotated, {c.skipped} skipped, {c.failed} failed"
            for c in self.columns
            if c.rotated or c.failed  # keep the report focused on what moved/broke
        ]
        return "\n".join([head, *lines])


def _rotate_value(
    value: str, salt: bytes, old_key: str, new_key: str
) -> tuple[str, str | None]:
    """Classify one ciphertext: ('skipped', value) if it already decrypts under the
    new key, ('rotated', new_ciphertext) after re-encrypting from the old key, or
    ('failed', None) if neither key decrypts it (already-corrupt data)."""
    try:
        decrypt_field(value, salt, secret_key=new_key)
        return ("skipped", value)
    except InvalidToken:
        pass
    try:
        plaintext = decrypt_field(value, salt, secret_key=old_key)
    except InvalidToken:
        return ("failed", None)
    return ("rotated", encrypt_field(plaintext, salt, secret_key=new_key))


async def _rotate_fernet_column(
    read_conn: AsyncConnection,
    write_conn: AsyncConnection,
    schema: str,
    table: str,
    column: str,
    salt: bytes,
    old_key: str,
    new_key: str,
    dry_run: bool,
) -> ColumnResult:
    """Re-encrypt every non-null value of one Fernet column. Reads are streamed (a
    server-side cursor on ``read_conn``) so a large table isn't pulled into memory at
    once; writes go to a separate ``write_conn`` because asyncpg can't interleave an
    UPDATE on the same connection as an open cursor. The ciphertext itself is the
    UPDATE key (Fernet's random IV makes each value unique), so this needs no
    knowledge of the table's primary key."""
    result = ColumnResult(schema, table, column)
    stream = await read_conn.stream(
        text(
            f'SELECT "{column}" FROM "{schema}"."{table}" WHERE "{column}" IS NOT NULL'
        )
    )
    async for (value,) in stream:
        status, new_value = _rotate_value(value, salt, old_key, new_key)
        if status == "skipped":
            result.skipped += 1
        elif status == "failed":
            result.failed += 1
            logger.warning(
                "secret-key rotation: %s.%s.%s holds a value decryptable under "
                "neither key — skipping (already unreadable)",
                schema,
                table,
                column,
            )
        elif dry_run:
            result.rotated += 1
        else:
            # Count actual writes: a concurrent rotation may have already re-keyed
            # this value (WHERE no longer matches → rowcount 0), so don't overcount.
            res = await write_conn.execute(
                text(
                    f'UPDATE "{schema}"."{table}" SET "{column}" = :new '
                    f'WHERE "{column}" = :old'
                ),
                {"new": new_value, "old": value},
            )
            result.rotated += res.rowcount or 0
    return result


async def _rotate_user_emails(
    read_conn: AsyncConnection,
    write_conn: AsyncConnection,
    old_key: str,
    new_key: str,
    dry_run: bool,
) -> ColumnResult:
    """Re-encrypt users.email_encrypted AND recompute users.email_hash from the same
    plaintext, in one UPDATE so the two never disagree. email_hash is a deterministic
    HMAC, so the new hashes stay unique (one per unique email) and disjoint from the
    old ones — no unique-constraint conflict. Streamed read / separate write like
    ``_rotate_fernet_column``."""
    result = ColumnResult("public", "users", "email_encrypted+email_hash")
    stream = await read_conn.stream(
        text(
            "SELECT email_encrypted FROM public.users WHERE email_encrypted IS NOT NULL"
        )
    )
    async for (enc,) in stream:
        try:
            decrypt_field(enc, SALT_EMAIL, secret_key=new_key)
            result.skipped += 1
            continue
        except InvalidToken:
            pass
        try:
            email = decrypt_field(enc, SALT_EMAIL, secret_key=old_key)
        except InvalidToken:
            result.failed += 1
            logger.warning(
                "secret-key rotation: a users.email_encrypted value decrypts under "
                "neither key — skipping (already unreadable)"
            )
            continue
        if dry_run:
            result.rotated += 1
            continue
        res = await write_conn.execute(
            text(
                "UPDATE public.users "
                "SET email_encrypted = :new_enc, email_hash = :new_hash "
                "WHERE email_encrypted = :old_enc"
            ),
            {
                "new_enc": encrypt_field(email, SALT_EMAIL, secret_key=new_key),
                "new_hash": hash_email(email, secret_key=new_key),
                "old_enc": enc,
            },
        )
        result.rotated += res.rowcount or 0
    return result


async def rotate_secret_key(*, dry_run: bool = False) -> RotationSummary:
    """Re-encrypt all SECRET_KEY-derived data from PREVIOUS_SECRET_KEY to SECRET_KEY.

    Raises RuntimeError if there is nothing to rotate from (PREVIOUS_SECRET_KEY unset
    or equal to SECRET_KEY) — callers that may hit those states benignly (startup)
    should guard before calling.
    """
    old_key = settings.PREVIOUS_SECRET_KEY
    new_key = settings.SECRET_KEY
    if not old_key:
        raise RuntimeError(
            "PREVIOUS_SECRET_KEY is not set — set it to the old key to rotate from."
        )
    if old_key == new_key:
        raise RuntimeError(
            "PREVIOUS_SECRET_KEY equals SECRET_KEY — nothing to rotate; unset it."
        )

    summary = RotationSummary(dry_run=dry_run)
    engine = db_session.provisioning_engine  # superuser: all schemas, bypasses RLS

    # Platform tables (public). Reads stream on one connection; writes commit on a
    # second (engine.begin()) — separate connections so an open read cursor and the
    # UPDATEs don't collide on asyncpg. The write txn commits together, resumable.
    async with engine.connect() as read_conn, engine.begin() as write_conn:
        summary.columns.append(
            await _rotate_user_emails(read_conn, write_conn, old_key, new_key, dry_run)
        )
        for table, column, salt in _PUBLIC_FERNET_COLUMNS:
            summary.columns.append(
                await _rotate_fernet_column(
                    read_conn,
                    write_conn,
                    "public",
                    table,
                    column,
                    salt,
                    old_key,
                    new_key,
                    dry_run,
                )
            )

    # Guild-scoped live copies — one write transaction per guild schema (independently
    # resumable). A guild whose schema is missing/broken is logged and skipped.
    async with engine.connect() as conn:
        guild_ids = (
            (await conn.execute(text("SELECT id FROM public.guilds ORDER BY id")))
            .scalars()
            .all()
        )
    for gid in guild_ids:
        schema = guild_schema_name(gid)
        try:
            async with (
                engine.connect() as read_conn,
                engine.begin() as write_conn,
            ):
                for table, column, salt in _GUILD_SCHEMA_COLUMNS:
                    summary.columns.append(
                        await _rotate_fernet_column(
                            read_conn,
                            write_conn,
                            schema,
                            table,
                            column,
                            salt,
                            old_key,
                            new_key,
                            dry_run,
                        )
                    )
        except Exception:
            logger.exception(
                "secret-key rotation: failed to rotate schema %s — skipping", schema
            )

    log = logger.warning if summary.failed else logger.info
    log("%s", summary.render())
    return summary


async def maybe_rotate_at_startup() -> None:
    """Startup hook: rotate when PREVIOUS_SECRET_KEY names a different key, else no-op.
    Runs the real (non-dry) sweep before the app serves traffic. Never raises for the
    benign 'nothing to rotate' states — those are expected when PREVIOUS_SECRET_KEY is
    unset or left equal to SECRET_KEY."""
    old_key = settings.PREVIOUS_SECRET_KEY
    if not old_key or old_key == settings.SECRET_KEY:
        return
    summary = await rotate_secret_key(dry_run=False)
    # Post-run nudge (WARNING so it survives INFO-filtered logs). Phrased for the
    # auto-rotation that JUST ran — never "go run the CLI", which would have an
    # operator kick off a redundant concurrent sweep.
    if summary.failed:
        logger.warning(
            "secret-key rotation left %d value(s) decryptable under neither key — "
            "they were already unreadable; review the warnings above and keep "
            "PREVIOUS_SECRET_KEY set until resolved.",
            summary.failed,
        )
    else:
        logger.warning(
            "secret-key rotation complete (%d re-encrypted this boot). UNSET "
            "PREVIOUS_SECRET_KEY to finish retiring the old key.",
            summary.rotated,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rotate SECRET_KEY-derived data from PREVIOUS_SECRET_KEY to SECRET_KEY."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would rotate without writing anything.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = asyncio.run(rotate_secret_key(dry_run=args.dry_run))
    print(summary.render())
    if summary.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
