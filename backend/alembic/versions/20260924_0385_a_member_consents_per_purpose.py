"""a member consents per purpose

An installed app that needs to act as a member asks that member, for one named
purpose, and the member answers. ``app_member_consents`` holds the request and
the answer: one row per (install, member, purpose), the app-wide consent being
the row with no purpose. ``guild_app_user_delegations`` stays for now; nothing
is carried over from it, because an app asks again.

A member token's standing reads, beside the consent row, the member's
membership row and whether their account is active. The install floor,
``app_install_base``, gains column grants on ``public.guild_memberships``
(guild_id, user_id) and ``public.users`` (id, status) for that. The policies
admitting the member's own two rows, and the table's own-row policies, are
rendered from the registries at boot like every other table's.

``public.fn_install_owns_what_it_creates`` is restated: for a member token it
writes the owner row on what the token creates naming the member, rather than
nothing. An installation token's row still names the install. Both bodies are
stated here in full.

Revision ID: 20260924_0385
Revises: 20260924_0384
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from alembic import op

from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260924_0385"
down_revision = "20260924_0384"
branch_labels = None
depends_on = None

TABLE = "app_member_consents"

#: What the install floor reads for a member token, column by column.
_INSTALL_BASE_READS = {
    "guild_memberships": ("guild_id", "user_id"),
    "users": ("id", "status"),
}

#: The policies ``app.db.public_rls`` renders for the install floor on those
#: tables, dropped with the grants on the way down.
_POLICIES = {
    "guild_memberships": "install_reads_its_member",
    "users": "install_reads_its_member",
}

_ACCESS_VALUES = "('read', 'read_write')"

#: ``public.fn_install_owns_what_it_creates`` as revision 20260924_0381 set it.
OWNS_FUNCTION_BEFORE = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(
        current_setting('app.current_install_id', true), ''
    )::integer;
BEGIN
    IF v_install IS NOT NULL
       AND NULLIF(current_setting('app.current_user_id', true), '') IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, app_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    END IF;
    RETURN NULL;
END;
$owns$;
"""

#: The same, writing a member token's owner row as the member.
OWNS_FUNCTION_AFTER = """
CREATE OR REPLACE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql AS $owns$
DECLARE
    v_install integer := NULLIF(
        current_setting('app.current_install_id', true), ''
    )::integer;
    v_member integer := NULLIF(
        current_setting('app.current_user_id', true), ''
    )::integer;
BEGIN
    IF v_install IS NULL THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, app_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$owns$;
"""


def upgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _create_table)
    op.execute(OWNS_FUNCTION_AFTER)
    for table, columns in _INSTALL_BASE_READS.items():
        op.execute(
            f"GRANT SELECT ({', '.join(columns)}) ON public.{table} TO app_install_base"
        )


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("install_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=128), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("initiative_id", sa.Integer(), nullable=True),
        sa.Column("requested_access", sa.String(length=16), nullable=False),
        sa.Column("granted_access", sa.String(length=16), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_factor", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["install_id"], ["guild_apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["initiative_id"], ["initiatives.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "install_id",
            "user_id",
            "purpose",
            name="app_member_consents_unique_purpose",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            f"requested_access IN {_ACCESS_VALUES}",
            name="app_member_consents_requested_access",
        ),
        sa.CheckConstraint(
            f"granted_access IS NULL OR granted_access IN {_ACCESS_VALUES}",
            name="app_member_consents_granted_access",
        ),
    )
    op.create_index(f"ix_{TABLE}_install_id", TABLE, ["install_id"])
    op.create_index(f"ix_{TABLE}_user_id", TABLE, ["user_id"])


def downgrade() -> None:
    op.execute(OWNS_FUNCTION_BEFORE)
    for table, name in _POLICIES.items():
        op.execute(f"DROP POLICY IF EXISTS {name} ON public.{table}")
    for table, columns in _INSTALL_BASE_READS.items():
        op.execute(
            f"REVOKE SELECT ({', '.join(columns)}) ON public.{table} "
            "FROM app_install_base"
        )
    run_for_each_guild_schema(op.get_bind(), _drop_table)


def _drop_table() -> None:
    op.drop_index(f"ix_{TABLE}_user_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_install_id", table_name=TABLE)
    op.drop_table(TABLE)
