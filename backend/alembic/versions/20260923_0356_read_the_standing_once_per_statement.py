"""read the request's standing once per statement

Every gate a guild's policies call used to read the request's standing out of
settings on each call, and a policy calls its gates once per row: the system
engine's catalog lookup, and each set of initiatives, roles and switches parsed
out of a comma list again, for every row a statement touched. None of it
depends on the row.

``public.standing`` is that standing as one value. Each guild schema renders
``current_standing()``, which reads it, beside the gates that take it; a policy
passes ``(SELECT current_standing())`` — a sub-select naming no row, which the
planner evaluates once for the statement — and each gate reads its fields. The
functions and policies are rendered at boot, so this revision creates only the
type they share. ``authorization_test`` holds its attributes to
``app.db.authorization.STANDING_FIELDS``.

Revision ID: 20260923_0356
Revises: 20260923_0355
Create Date: 2026-09-23
"""

from alembic import op

revision = "20260923_0356"
down_revision = "20260923_0355"
branch_labels = None
depends_on = None

STANDING_TYPE = """CREATE TYPE public.standing AS (
    system_session boolean,
    this_guild boolean,
    guild_admin boolean,
    guild_auth_ok boolean,
    scope_initiative_id integer,
    pam_read boolean,
    pam_write boolean,
    member_initiatives integer[],
    manager_initiatives integer[],
    override_initiatives integer[],
    member_role_ids integer[],
    role_grants text[],
    role_denies text[],
    enabled_tools text[],
    via_dashboard_id integer
)
"""


def upgrade() -> None:
    op.execute(STANDING_TYPE)


def downgrade() -> None:
    # The guild gates take a standing as their last argument, so dropping the
    # type drops them and the policies that call them. The back-fill on the
    # next boot renders every guild's gates and policies from the code that is
    # then running.
    op.execute("DROP TYPE IF EXISTS public.standing CASCADE")
