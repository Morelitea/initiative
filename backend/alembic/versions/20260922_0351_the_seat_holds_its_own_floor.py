"""give the community's seat its own grant floor

``app_guild_base`` is the floor every routed ``guild_<id>`` role inherits, and
it carried full DML on ``guild_auth_policies`` — the table that records how a
community signs its members in. Reading it stays where it was: the gate
function ``public.guild_auth_satisfied()`` runs under whatever role the request
assumed, so every floor keeps ``SELECT``.

Writing it moves to ``app_superadmin``, a floor of its own, which only the
per-guild ``guild_<id>_superadmin`` role inherits (guild provisioning grants
it). A request reaches that role by asking for the seat and holding it.

``platform_base`` is named here too. It takes the same schema default as the
guild floor and has never been recorded table by table; the revoke below is
what makes its reach on this table a decision rather than a default, and
``SHARED_TABLE_PLATFORM_BASE_GRANTS`` records the rest of it.

Revision ID: 20260922_0351
Revises: 20260922_0350
Create Date: 2026-09-22
"""

from alembic import op

from app.core.config import settings

revision = "20260922_0351"
down_revision = "20260922_0350"
branch_labels = None
depends_on = None

ROLE = "app_superadmin"
SEAT_TABLE = "public.guild_auth_policies"
FLOORS = ("app_guild_base", f"{settings.PLATFORM_ROLE_PREFIX}platform_base")


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    # The seat floor takes no default privileges (app.db.bootstrap grants those
    # to the guild and platform floors alone), so a shared table added later
    # reaches it only through an entry in SHARED_TABLE_APP_SUPERADMIN_GRANTS and
    # a migration that grants it.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SEAT_TABLE} TO {ROLE}")
    for floor in FLOORS:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{floor}') THEN
                    EXECUTE 'REVOKE INSERT, UPDATE, DELETE ON {SEAT_TABLE}'
                            ' FROM {floor}';
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    """Put the writes back on the guild floor and leave the role.

    Roles are cluster-global while a migration runs in one database, so a role
    holding privileges in a sibling database cannot be dropped from here.
    Revoking is the part that is this database's to do.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_guild_base') THEN
                EXECUTE 'GRANT INSERT, UPDATE, DELETE ON'
                        ' public.guild_auth_policies TO app_guild_base';
            END IF;
        END
        $$;
        """
    )
    op.execute(f"REVOKE ALL ON {SEAT_TABLE} FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
