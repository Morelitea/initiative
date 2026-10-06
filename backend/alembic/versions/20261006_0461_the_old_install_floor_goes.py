"""the old install floor goes

``20261005_0457`` moved the install floor to ``plugin_install_base`` and drops
``app_install_base`` once nothing holds it. On an install that has started,
the row-security policies the app renders at boot still name the old floor
when that migration runs, so the drop was skipped and the role stayed behind
after the next start rendered them anew. This points any policy still naming
``app_install_base`` at ``plugin_install_base``, then drops the old role if no
other database in the cluster holds anything through it.

Nothing to undo: the policies are rendered again at the next start, and the
old role carried nothing ``plugin_install_base`` does not.

Revision ID: 20261006_0461
Revises: 20261006_0460
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_0461"
down_revision = "20261006_0460"
branch_labels = None
depends_on = None

OLD_FLOOR = "app_install_base"
NEW_FLOOR = "plugin_install_base"


def _role(name: str) -> str:
    """A role as a policy's ``TO`` list spells it; ``public`` is the keyword."""
    return "PUBLIC" if name == "public" else f'"{name}"'


def upgrade() -> None:
    bind = op.get_bind()
    held = bind.execute(
        sa.text(
            "SELECT schemaname, tablename, policyname, roles FROM pg_policies "
            "WHERE :old = ANY(roles)"
        ),
        {"old": OLD_FLOOR},
    ).all()
    for schema, table, policy, roles in held:
        to = ", ".join(
            _role(NEW_FLOOR if role == OLD_FLOOR else role) for role in roles
        )
        op.execute(f'ALTER POLICY "{policy}" ON "{schema}"."{table}" TO {to}')
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{OLD_FLOOR}') THEN
                BEGIN
                    DROP ROLE "{OLD_FLOOR}";
                EXCEPTION WHEN dependent_objects_still_exist THEN
                    NULL;
                END;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    pass
