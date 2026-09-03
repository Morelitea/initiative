"""How a person chooses to appear

Adds ``users.presence`` — the standing preference behind the dot beside
someone's name. Whether they actually have Initiative open, and whether anyone
has touched it lately, is live state no column could hold; this is the half
that outlives every socket, so it is the half that is stored.

``idle`` is in the type like any other value: an account left on ``online`` is
shown it once its tabs go quiet, and one that picked it is shown it either way.

Existing accounts get ``online``, which is what they have effectively had all
along: shown while a tab is open, and not otherwise.

The column is not added to ``public.user_profiles``. That view is the public
projection of an account, and this is not read from a row — a reader is shown
the preference already narrowed by what the process can see.

The request path writes ``public.users`` through a **column-scoped** UPDATE
(0144), so a new column is unwritable until it is named in that grant. This is
one a person sets for themselves, so it is named. SELECT is table-wide and
needs nothing.

Revision ID: 20260903_0216
Revises: 20260902_0215
Create Date: 2026-09-03
"""

from alembic import op

from app.core.config import settings

revision = "20260903_0216"
down_revision = "20260902_0215"
branch_labels = None
depends_on = None


#: The request-path floors, which hold their UPDATE on ``users`` per column.
def _write_roles() -> tuple[str, ...]:
    return (
        "app_guild_base",
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "app_user",
    )


def upgrade() -> None:
    op.execute(
        "CREATE TYPE user_presence AS ENUM ('online', 'idle', 'busy', 'offline')"
    )
    op.execute(
        "ALTER TABLE public.users "
        "ADD COLUMN presence user_presence NOT NULL DEFAULT 'online'"
    )
    for role in _write_roles():
        op.execute(f"GRANT UPDATE (presence) ON TABLE public.users TO {role}")


def downgrade() -> None:
    # The grant goes with the column it names.
    op.execute("ALTER TABLE public.users DROP COLUMN IF EXISTS presence")
    op.execute("DROP TYPE IF EXISTS user_presence")
