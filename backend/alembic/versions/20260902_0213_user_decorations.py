"""A person's decoration library.

``public.user_decorations`` is what an account has **acquired** — one row per
decoration, written when a marketplace pack is installed and removed when that
pack goes. ``source`` names the pack so a set can be granted and revoked
together while the account mixes decorations across packs freely.

What ships with the app is deliberately NOT in here. Those are universal, so a
row per account per decoration would be a fan-out over every user for something
nobody chose — and another one every time the app ships a new default. They
live in ``app.core.profile_decorations.SHIPPED_DECORATIONS`` and are unioned
with this table by ``app.services.platform.profile_decorations``, which is the
one place that answers "what may this person wear".

Access shape:

* **Your library is yours.** SELECT is scoped to the calling account's own
  rows; nobody reads anyone else's. What another person may see of it is
  already answered by the profile they are looking at, which carries only the
  ids being worn.
* **Grants are issued, not self-served.** The request path holds SELECT and no
  write verb at all — INSERT/DELETE are the system engine's, which is what runs
  a pack install. The grant layer says so as well as the policies do.

The schema's default grants make every new ``public`` table writable by the
routed base roles, so they are wound back explicitly before anything else.

The table starts empty and nothing is carried into it, so the
create-then-backfill-then-lock-down ordering a populated table needs does not
apply here.

Revision ID: 20260902_0213
Revises: 20260902_0212
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260902_0213"
down_revision = "20260902_0212"
branch_labels = None
depends_on = None


# NULLIF-guarded: an unset context leaves the setting empty, and a bare
# ''::int would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"


def _request_roles() -> str:
    base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    return f'app_guild_base, "{base}", app_user'


def upgrade() -> None:
    op.create_table(
        "user_decorations",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("decoration_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "decoration_id"),
    )
    # Granting and revoking happen a pack at a time.
    op.create_index(
        "ix_user_decorations_source", "user_decorations", ["user_id", "source"]
    )

    request_roles = _request_roles()
    statements = [
        "ALTER TABLE public.user_decorations ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.user_decorations FORCE ROW LEVEL SECURITY",
        f"REVOKE ALL ON TABLE public.user_decorations FROM {request_roles}",
        "GRANT SELECT, INSERT, DELETE ON TABLE public.user_decorations TO app_admin",
        # Read-only for the request path, and only your own rows. The bare
        # login role is left out entirely: a library belongs to a signed-in
        # account, and nothing is served before routing.
        f"GRANT SELECT ON TABLE public.user_decorations TO app_guild_base, "
        f'"{settings.PLATFORM_ROLE_PREFIX}platform_base"',
        "DROP POLICY IF EXISTS user_decoration_self_read ON public.user_decorations",
        "CREATE POLICY user_decoration_self_read ON public.user_decorations "
        "AS PERMISSIVE FOR SELECT TO "
        f'app_guild_base, "{settings.PLATFORM_ROLE_PREFIX}platform_base" '
        f"USING (user_id = {_USER_ID})",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS user_decoration_self_read ON public.user_decorations"
    )
    op.execute("ALTER TABLE public.user_decorations DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_user_decorations_source", table_name="user_decorations")
    op.drop_table("user_decorations")
