"""Login posture and the permitted sign-in methods become settings.

Two columns on ``app_settings``, both shaped so that upgrading changes nothing
about how any existing deployment behaves.

* ``auth_scope`` — 'platform' or 'guild', **nullable**, no default. NULL means
  nobody has chosen in the settings UI and the deploy-time ``AUTH_SCOPE`` env
  value governs, which is what every deployment gets here. An install
  configured with ``AUTH_SCOPE=guild`` therefore keeps its posture with no
  backfill at all — there is no value to carry, because NULL already means
  "ask the environment". A ``CHECK`` rather than a Postgres enum: two stable
  values, no growth expected, and this is the shape migration 0149's own
  downgrade already writes.

* ``login_methods`` — which ways in the deployment permits, as an array of a
  real ``login_method`` Postgres enum. An enum because the database should
  validate the elements rather than a hand-kept ``IN (...)`` list that drifts
  from ``app.core.login_methods``; an array because a method added later
  should be a value on the type, not a column per method on this table and a
  branch on every surface. Defaults to every method that exists, so an upgrade
  permits exactly what the deployment permitted before it.

  The non-empty ``CHECK`` is the "at least one way in" rule, held in the
  database rather than only in a Pydantic validator.

Both are ``ADD COLUMN`` with a server default, which Postgres applies as
metadata — no row rewrite, and no policy-bound DML to route around
``FORCE ROW LEVEL SECURITY``. ``app_settings`` is granted table-wide to the
owner tier, so both columns arrive writable.

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
    op.add_column(
        "app_settings",
        sa.Column("auth_scope", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_app_settings_auth_scope",
        "app_settings",
        "auth_scope IS NULL OR auth_scope IN ('platform', 'guild')",
    )

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
    # cardinality, not array_length. `array_length('{}', 1)` is NULL, and a
    # CHECK accepts anything that is not false -- so the constraint named
    # "nonempty" admitted the empty array, and `methods_from_row` reads that
    # as both methods being enabled. Verified on PostgreSQL: the array_length
    # form accepts '{}', the cardinality form rejects it.
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

    op.drop_constraint("ck_app_settings_auth_scope", "app_settings", type_="check")
    op.drop_column("app_settings", "auth_scope")
