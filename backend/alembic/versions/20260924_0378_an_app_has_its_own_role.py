"""give an installed app its own grant floor

``app_install_base`` is the shared floor the per-guild ``guild_<id>_app`` role
inherits: an installed app's reach into ``public``. It is modelled on
``app_superadmin``: ``NOLOGIN``, ``USAGE`` on ``public``, no default
privileges, and no table grant. ``SHARED_TABLE_APP_INSTALL_BASE_GRANTS``
records a decision for every shared table, each of them ``None`` today, and a
later migration grants what an entry there comes to name.

The per-guild ``guild_<id>_app`` roles are created by guild provisioning,
which also grants this floor to them. Their grants are part of the provisioning
stamp, so the boot back-fill reaches every existing guild once this revision
has run.

Nothing routes a request into either role yet.

Revision ID: 20260924_0378
Revises: 20260924_0377
Create Date: 2026-09-24
"""

from alembic import op

revision = "20260924_0378"
down_revision = "20260924_0377"
branch_labels = None
depends_on = None

ROLE = "app_install_base"


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
    # The install floor takes no default privileges (app.db.bootstrap grants
    # those to the guild and platform floors alone), so a shared table reaches
    # it only through an entry in SHARED_TABLE_APP_INSTALL_BASE_GRANTS and a
    # migration that grants it.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")


def downgrade() -> None:
    """Take the floor's schema access back and leave the role.

    Roles are cluster-global while a migration runs in one database, so a role
    holding privileges in a sibling database cannot be dropped from here.
    Revoking is the part that is this database's to do. The per-guild
    ``guild_<id>_app`` roles belong to provisioning and stay with their guilds.
    """
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}")
