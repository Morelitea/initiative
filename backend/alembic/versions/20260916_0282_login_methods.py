"""Which ways in a deployment permits becomes a setting.

One column on ``app_settings``: ``login_methods``, an array of a real
``login_method`` Postgres enum. An enum because the database should validate
the elements rather than a hand-kept ``IN (...)`` list that drifts from
``app.core.login_methods``; an array because a method added later should be a
value on the type, not a column per method on this table and a branch on every
surface. It defaults to every method that exists, so an upgrade permits exactly
what the deployment permitted before it.

The ``cardinality`` check is the "at least one way in" rule, held in the
database rather than only in a Pydantic validator. ``cardinality`` and not
``array_length``: the latter returns NULL for an empty array, and a CHECK
admits any result that is not false.

``ADD COLUMN`` with a server default, which Postgres applies as metadata — no
row rewrite, and no policy-bound DML to route around ``FORCE ROW LEVEL
SECURITY``. ``app_settings`` is granted table-wide to the owner tier, so the
column arrives writable.

Revision ID: 20260916_0282
Revises: 20260916_0281
Create Date: 2026-09-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260916_0282"
down_revision = "20260916_0281"
branch_labels = None
depends_on = None


def upgrade() -> None:
    login_method = postgresql.ENUM("password", "sso", name="login_method")
    login_method.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "app_settings",
        sa.Column(
            "login_methods",
            postgresql.ARRAY(
                postgresql.ENUM(
                    "password", "sso", name="login_method", create_type=False
                )
            ),
            nullable=False,
            server_default="{password,sso}",
        ),
    )
    op.create_check_constraint(
        "ck_app_settings_login_methods_nonempty",
        "app_settings",
        "cardinality(login_methods) >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_app_settings_login_methods_nonempty", "app_settings", type_="check"
    )
    op.drop_column("app_settings", "login_methods")
    postgresql.ENUM(name="login_method").drop(op.get_bind(), checkfirst=True)
