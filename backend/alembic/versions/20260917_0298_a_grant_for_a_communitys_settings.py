"""A grant can be for a community's settings, at a named rung.

Access to a community's *content* and authority over its *configuration* are
two grants now, asked for and recorded apart.

``purpose`` gains ``settings``. Such a grant carries its rung in the existing
``access_level`` column — ``admin`` or ``superadmin``, the guild's own ladder —
and the CHECK holds each vocabulary to its own purpose, so a settings grant can
never read as ``read_write`` content nor a content grant as ``superadmin``.

Nothing is backfilled: every existing row is ``content`` with a content level,
which the widened constraint still admits.

Revision ID: 20260917_0298
Revises: 20260917_0297
Create Date: 2026-09-17
"""

import sqlalchemy as sa
from alembic import op

revision = "20260917_0298"
down_revision = "20260917_0297"
branch_labels = None
depends_on = None

_PURPOSE_CK = "ck_access_grants_purpose"
_LEVEL_CK = "ck_access_grants_access_level"

# The vocabularies as of THIS revision, spelled out rather than read from the
# model: a migration states the shape of the database at its own revision, and
# a registry describes a later one.
_PURPOSES = ("content", "billing", "settings")
_CONTENT_LEVELS = ("read", "read_write")
_SETTINGS_LEVELS = ("admin", "superadmin")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


_LEVEL_RULE = (
    f"(purpose = 'settings' AND access_level IN ({_quoted(_SETTINGS_LEVELS)}))"
    f" OR (purpose <> 'settings' AND access_level IN ({_quoted(_CONTENT_LEVELS)}))"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.drop_constraint(_PURPOSE_CK, "access_grants", type_="check")
    op.create_check_constraint(
        _PURPOSE_CK, "access_grants", f"purpose IN ({_quoted(_PURPOSES)})"
    )

    op.drop_constraint(_LEVEL_CK, "access_grants", type_="check")
    op.create_check_constraint(_LEVEL_CK, "access_grants", _LEVEL_RULE)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Settings grants have no meaning at the revision below this one, and their
    # levels are not in its vocabulary, so they go rather than fail the CHECK.
    # ``access_grants`` carries FORCE ROW LEVEL SECURITY and is owned by the
    # role migrations run as, so the delete runs with FORCE lifted and the
    # count afterwards is what says it happened.
    op.execute("ALTER TABLE public.access_grants NO FORCE ROW LEVEL SECURITY")
    try:
        conn = op.get_bind()
        conn.execute(
            sa.text("DELETE FROM public.access_grants WHERE purpose = 'settings'")
        )
        left = conn.execute(
            sa.text(
                "SELECT count(*) FROM public.access_grants WHERE purpose = 'settings'"
            )
        ).scalar_one()
        assert left == 0, f"{left} settings grants are still there"
    finally:
        op.execute("ALTER TABLE public.access_grants FORCE ROW LEVEL SECURITY")

    op.drop_constraint(_LEVEL_CK, "access_grants", type_="check")
    op.create_check_constraint(
        _LEVEL_CK, "access_grants", f"access_level IN ({_quoted(_CONTENT_LEVELS)})"
    )

    op.drop_constraint(_PURPOSE_CK, "access_grants", type_="check")
    op.create_check_constraint(
        _PURPOSE_CK, "access_grants", "purpose IN ('content', 'billing')"
    )
