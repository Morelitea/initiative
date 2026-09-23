"""the settings keep their secrets apart

``app_settings`` is read by every request role. Its two stored credentials —
the SMTP password and the S3 secret access key, both Fernet ciphertext — move
to ``app_setting_secrets``, a companion row read and written only by the
system engine, as ``auth_provider_secrets`` already is for the provider client
secrets.

One row, keyed like the singleton it belongs to (``id`` = 1, an FK to
``app_settings.id``), with one column per credential. The ciphertext moves
verbatim: same salts, same key.

Order, per table: create it, copy the rows in, then enable and force row
security, take back the schema-default privileges from both floors and grant
the system engine its three verbs, and finally drop the two columns from
``app_settings``. No policy is written: the registry records the table as
``FORCED_NO_POLICY`` (``app.db.public_rls``).

``app_settings`` forces row security and the provisioning role that runs this
owns it, so it is policy-bound for the copy. Force is lifted for the length of
each copy and restored in the same transaction.

Revision ID: 20260923_0362
Revises: 20260923_0361
Create Date: 2026-09-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "20260923_0362"
down_revision = "20260923_0361"
branch_labels = None
depends_on = None


#: The columns that move off ``app_settings``, in the order they are copied.
_MOVED = ("smtp_password_encrypted", "s3_secret_access_key_encrypted")


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _copy_out_of_app_settings(sql: str) -> None:
    """Copy every ``app_settings`` row's credentials into the new table.

    Lifts FORCE on ``app_settings`` for the copy and restores it in the same
    transaction, then checks that one row landed for each settings row.
    """
    conn = op.get_bind()
    op.execute("ALTER TABLE public.app_settings NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(sql)
        expected = conn.execute(
            text("SELECT count(*) FROM public.app_settings")
        ).scalar_one()
    finally:
        op.execute("ALTER TABLE public.app_settings FORCE ROW LEVEL SECURITY")
    copied = conn.execute(
        text("SELECT count(*) FROM public.app_setting_secrets")
    ).scalar_one()
    if copied != expected:
        raise RuntimeError(
            f"app_setting_secrets backfill copied {copied} of {expected} rows; "
            "aborting so the migration is not applied with data missing"
        )


def upgrade() -> None:
    base = _platform_base()

    op.create_table(
        "app_setting_secrets",
        sa.Column(
            "id",
            sa.Integer(),
            sa.ForeignKey("app_settings.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("smtp_password_encrypted", sa.String(length=2000), nullable=True),
        sa.Column(
            "s3_secret_access_key_encrypted", sa.String(length=2000), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    _copy_out_of_app_settings(
        f"""
        INSERT INTO public.app_setting_secrets (id, {", ".join(_MOVED)})
        SELECT id, {", ".join(_MOVED)} FROM public.app_settings
        """
    )

    _run(
        [
            "ALTER TABLE public.app_setting_secrets ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.app_setting_secrets FORCE ROW LEVEL SECURITY",
            # The schema default grants both floors full DML on a new table;
            # this table is the system engine's alone.
            "REVOKE ALL ON TABLE public.app_setting_secrets "
            f'FROM app_user, app_guild_base, "{base}"',
            "GRANT SELECT, INSERT, UPDATE ON TABLE public.app_setting_secrets "
            "TO app_admin",
        ]
    )

    for column in _MOVED:
        op.drop_column("app_settings", column)


def downgrade() -> None:
    for column in _MOVED:
        op.add_column(
            "app_settings",
            sa.Column(column, sa.String(length=2000), nullable=True),
        )

    conn = op.get_bind()
    # Both tables force row security and neither admits the provisioning role
    # by policy, so force is lifted on both for the copy back.
    op.execute("ALTER TABLE public.app_settings NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.app_setting_secrets NO FORCE ROW LEVEL SECURITY")
    try:
        expected = conn.execute(
            text("SELECT count(*) FROM public.app_setting_secrets")
        ).scalar_one()
        copied = conn.execute(
            text(
                "UPDATE public.app_settings AS s SET "
                + ", ".join(f"{column} = x.{column}" for column in _MOVED)
                + " FROM public.app_setting_secrets AS x WHERE x.id = s.id"
            )
        ).rowcount
    finally:
        op.execute("ALTER TABLE public.app_settings FORCE ROW LEVEL SECURITY")
    if copied != expected:
        raise RuntimeError(
            f"app_settings restore copied {copied} of {expected} rows; "
            "aborting so the downgrade is not applied with data missing"
        )

    op.execute("DROP TABLE public.app_setting_secrets")
