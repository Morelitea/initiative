"""captcha and push credentials move into settings

The last two operator credentials that could only ever be environment
variables: the captcha provider's verification secret, and the FCM
service-account JSON. Every other credential a deployment holds already lives
on the settings singleton -- SMTP's password, S3's secret key, the OIDC client
secret -- encrypted at rest under its own salt and re-keyed with SECRET_KEY.
These two were read straight off ``settings`` on every call, which meant they
could not be changed without a redeploy, were not encrypted anywhere, and had
to be carried by whatever deployed the app as free-form secret configuration.

The split follows the one the other areas use: what reaches a browser or a
device goes on ``app_settings`` (the captcha provider and site key; FCM's
project, application, API key and sender id -- Firebase's API key is public by
design and ships in the client), and only the two values that must not leave
the server go on ``app_setting_secrets``.

BACKFILL, and why it is not optional. Once a settings row exists the database
is authoritative and the env seed is never read again -- that is what makes the
settings pages mean anything. A deployment upgrading into these columns
therefore has them NULL, and without a backfill its captcha would stop being
enforced at the moment this migration ran: registration would quietly reopen to
whatever the captcha was keeping out, with nothing in any log to say so. So the
env values are read here and written into the new columns, encrypting the two
secrets exactly as the application does. Only where the column is NULL, so
re-running cannot overwrite a value somebody has since set.

Nothing is backfilled when no settings row exists yet: that deployment has not
booted, and its first boot seeds every one of these from the same env values.

Revision ID: 20260923_0368
Revises: 20260923_0367
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.core.config import settings
from app.core.encryption import (
    SALT_CAPTCHA_SECRET_KEY,
    SALT_FCM_SERVICE_ACCOUNT,
    encrypt_field,
)

revision = "20260923_0368"
down_revision = "20260923_0367"
branch_labels = None
depends_on = None


#: (column, type) added to ``app_settings``. All nullable but ``fcm_enabled``,
#: which is a switch and so has an answer even before anyone sets one.
SETTINGS_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("captcha_provider", sa.String(length=50)),
    ("captcha_site_key", sa.String(length=500)),
    ("fcm_project_id", sa.String(length=200)),
    ("fcm_application_id", sa.String(length=200)),
    ("fcm_api_key", sa.String(length=500)),
    ("fcm_sender_id", sa.String(length=50)),
)

#: (column, length) added to ``app_setting_secrets``. The FCM column is wider
#: than every other credential column because its plaintext is a whole JSON
#: document: a Google service account runs about 2.4 kB, which Fernet takes to
#: roughly 3.3 kB of base64. At 2000 it would be truncated on write and fail at
#: ``json.loads`` on the next push, a long way from the page that accepted it.
SECRET_COLUMNS: tuple[tuple[str, int], ...] = (
    ("captcha_secret_key_encrypted", 2000),
    ("fcm_service_account_json_encrypted", 8000),
)


def _clean(value: str | None) -> str | None:
    """The normalisation the settings service applies: blank is unset."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def upgrade() -> None:
    for name, type_ in SETTINGS_COLUMNS:
        op.add_column("app_settings", sa.Column(name, type_, nullable=True))
    op.add_column(
        "app_settings",
        sa.Column(
            "fcm_enabled", sa.Boolean(), nullable=False, server_default=text("false")
        ),
    )
    for name, length in SECRET_COLUMNS:
        op.add_column(
            "app_setting_secrets",
            sa.Column(name, sa.String(length=length), nullable=True),
        )

    _backfill(op.get_bind())


#: Both tables are FORCE ROW LEVEL SECURITY, which binds their owner -- the
#: role this migration runs as. ``app_setting_secrets`` has no policies at all,
#: and ``app_settings`` admits writes only from ``platform_owner``, so without
#: lifting FORCE the INSERT is refused and every UPDATE matches no row.
_TABLES = ("app_settings", "app_setting_secrets")


def _backfill(conn) -> None:
    """Copy the env values into the new columns, with FORCE lifted from both
    tables for the writes and restored in the same transaction.

    No try/finally: a failure aborts the transaction, which undoes the lift
    with everything else, and DDL issued in an aborted transaction would only
    replace the real error with "current transaction is aborted".
    """
    for table in _TABLES:
        conn.execute(text(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY"))
    if conn.execute(text("SELECT 1 FROM app_settings WHERE id = 1")).first():
        _write_env_values(conn)
    for table in reversed(_TABLES):
        conn.execute(text(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY"))


def _write_env_values(conn) -> None:
    plain = {
        "captcha_provider": _clean(settings.CAPTCHA_PROVIDER),
        "captcha_site_key": _clean(settings.CAPTCHA_SITE_KEY),
        "fcm_project_id": _clean(settings.FCM_PROJECT_ID),
        "fcm_application_id": _clean(settings.FCM_APPLICATION_ID),
        "fcm_api_key": _clean(settings.FCM_API_KEY),
        "fcm_sender_id": _clean(settings.FCM_SENDER_ID),
    }
    for column, value in plain.items():
        if value is None:
            continue
        conn.execute(
            text(
                f"UPDATE app_settings SET {column} = :value "  # noqa: S608 - key of a literal dict
                f"WHERE id = 1 AND {column} IS NULL"
            ),
            {"value": value},
        )

    if settings.FCM_ENABLED:
        # The switch has a server_default rather than a NULL, so "has anyone set
        # this" cannot be asked of it. Env is the only opinion that exists at
        # this point, so it is the one applied.
        conn.execute(text("UPDATE app_settings SET fcm_enabled = true WHERE id = 1"))

    secrets = {
        "captcha_secret_key_encrypted": (
            _clean(settings.CAPTCHA_SECRET_KEY),
            SALT_CAPTCHA_SECRET_KEY,
        ),
        "fcm_service_account_json_encrypted": (
            _clean(settings.FCM_SERVICE_ACCOUNT_JSON),
            SALT_FCM_SERVICE_ACCOUNT,
        ),
    }
    if not any(value for value, _ in secrets.values()):
        return
    # The companion row is created on demand by the application; a deployment
    # that has never stored a credential has none, and the two INSERTs below
    # would be its first.
    conn.execute(
        text(
            "INSERT INTO app_setting_secrets (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )
    )
    for column, (value, salt) in secrets.items():
        if not value:
            continue
        conn.execute(
            text(
                f"UPDATE app_setting_secrets SET {column} = :value "  # noqa: S608 - key of a literal dict
                f"WHERE id = 1 AND {column} IS NULL"
            ),
            {"value": encrypt_field(value, salt)},
        )


def downgrade() -> None:
    for name, _ in SECRET_COLUMNS:
        op.drop_column("app_setting_secrets", name)
    op.drop_column("app_settings", "fcm_enabled")
    for name, _ in SETTINGS_COLUMNS:
        op.drop_column("app_settings", name)
