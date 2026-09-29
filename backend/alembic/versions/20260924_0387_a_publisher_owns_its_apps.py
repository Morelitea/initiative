"""a publisher owns its apps

An app's ``public_id`` is ``<prefix>.<slug>``, and the prefix names its
publisher. ``public.publishers`` gives each prefix a row: a name, whether the
deployment has confirmed who it is (``verified``), and a switch (``enabled``)
that makes every registration under it not live.

- The table is created and filled first: this project's own publisher
  (``morelitea``, verified), then one unverified, enabled row for every other
  prefix an existing registration carries.
- ``app_service_registrations.publisher_id`` is added and filled by prefix.
  That table already forces row security, so reading its prefixes and filling
  the column lift ``FORCE`` for their length and restore it in the same
  transaction. Then the column is made ``NOT NULL`` and references
  ``publishers``.
- Then ``publishers`` is locked: RLS enabled and forced; ``app_admin`` reads,
  inserts and updates; the login role and the guild and platform floors, which
  the schema default grants full DML on a new table, are revoked, as is the id
  sequence; the seat floor takes no default privileges and is granted nothing.
- The install floor, ``app_install_base``, reads ``id`` and ``enabled`` of
  ``publishers`` and ``publisher_id`` of ``app_service_registrations``: the
  install standing asks whether its registration's publisher is on. Column
  grants, so nothing else on either row is readable. The policy admitting the
  publisher row is rendered from ``app.db.public_rls`` at boot, like every
  shared table's.

Revision ID: 20260924_0387
Revises: 20260924_0386
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260924_0387"
down_revision = "20260924_0386"
branch_labels = None
depends_on = None

TABLE = "publishers"
REGISTRATIONS = "app_service_registrations"

#: This project's own publisher, as boot seeds it.
FIRST_PARTY_PREFIX = "morelitea"
FIRST_PARTY_NAME = "Morelitea"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def _fill() -> None:
    """This project's publisher, a row for every other prefix a registration
    already carries, and each registration pointed at its prefix's row."""
    op.execute(
        sa.text(
            f"INSERT INTO public.{TABLE} "
            "(prefix, display_name, verified, enabled, created_at) "
            "VALUES (:prefix, :name, true, true, now())"
        ).bindparams(prefix=FIRST_PARTY_PREFIX, name=FIRST_PARTY_NAME)
    )
    op.execute(f"ALTER TABLE public.{REGISTRATIONS} NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            f"INSERT INTO public.{TABLE} "
            "(prefix, display_name, verified, enabled, created_at) "
            "SELECT DISTINCT split_part(r.public_id, '.', 1), "
            "split_part(r.public_id, '.', 1), false, true, now() "
            f"FROM public.{REGISTRATIONS} r "
            "ON CONFLICT (prefix) DO NOTHING"
        )
        op.add_column(
            REGISTRATIONS, sa.Column("publisher_id", sa.Integer(), nullable=True)
        )
        op.execute(
            f"UPDATE public.{REGISTRATIONS} r SET publisher_id = p.id "
            f"FROM public.{TABLE} p "
            "WHERE p.prefix = split_part(r.public_id, '.', 1)"
        )
    finally:
        op.execute(f"ALTER TABLE public.{REGISTRATIONS} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prefix", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix"),
    )
    _fill()
    op.alter_column(REGISTRATIONS, "publisher_id", nullable=False)
    op.create_foreign_key(
        f"{REGISTRATIONS}_publisher_id_fkey",
        REGISTRATIONS,
        TABLE,
        ["publisher_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(f"ix_{REGISTRATIONS}_publisher_id", REGISTRATIONS, ["publisher_id"])

    base = _platform_base()
    _run(
        [
            f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY",
            f'REVOKE ALL ON TABLE public.{TABLE} FROM app_user, app_guild_base, "{base}"',
            f"GRANT SELECT, INSERT, UPDATE ON TABLE public.{TABLE} TO app_admin",
            f"REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq "
            f'FROM app_user, app_guild_base, "{base}"',
            f"GRANT USAGE, SELECT ON SEQUENCE public.{TABLE}_id_seq TO app_admin",
            f"GRANT SELECT (id, enabled) ON public.{TABLE} TO app_install_base",
            f"GRANT SELECT (publisher_id) ON public.{REGISTRATIONS} "
            "TO app_install_base",
        ]
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT (publisher_id) ON public.{REGISTRATIONS} FROM app_install_base"
    )
    op.drop_index(f"ix_{REGISTRATIONS}_publisher_id", table_name=REGISTRATIONS)
    op.drop_constraint(
        f"{REGISTRATIONS}_publisher_id_fkey", REGISTRATIONS, type_="foreignkey"
    )
    op.drop_column(REGISTRATIONS, "publisher_id")
    op.execute(f"DROP POLICY IF EXISTS install_reads_its_publisher ON public.{TABLE}")
    op.execute(f"ALTER TABLE public.{TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{TABLE} DISABLE ROW LEVEL SECURITY")
    op.drop_table(TABLE)
