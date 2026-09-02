"""Deployment-wide announcements: the notices, their pictures, and who read them.

Three tables in ``public``, because an announcement is a property of the
deployment rather than of a guild: the same notice reaches every guild, and
what is remembered about it is remembered per *account*, which spans guilds.

The access shape, and why:

* **``announcements``** — readable by any routed request role, but only while
  it is live. The policy is the whole confidentiality story here: the audience
  filters (platform rung, guild-admin) are relevance and live in the service,
  whereas a notice that is a draft, not published yet, or past its end date is
  not this reader's to have at all — so "published, not scheduled, not
  expired" is enforced in the database. An end date therefore takes a notice
  out of the archive as well as out of the queue. Authoring runs on the system
  engine, which is what can see a draft at all.
* **``announcement_reads``** — a person's own receipts (each carrying how many
  times they have dismissed the notice, for the notices that ask for more than
  one), and nobody else's:
  own-row policies for SELECT/INSERT/UPDATE on the platform floor, which is
  the only path that records one. The system engine reads and deletes (a
  deleted announcement takes its receipts with it) and never writes one.
* **``announcement_images``** — bytes, held and served entirely on the system
  engine like guild images. No request-path role holds anything at all.

The schema's default privileges hand every new ``public`` table to the routed
base roles, so they are wound back explicitly before anything is granted.

All three tables start empty and nothing is carried into them, so the
create-then-backfill-then-lock-down ordering a populated table needs does not
apply.

Revision ID: 20260904_0218
Revises: 20260904_0217
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260904_0218"
down_revision = "20260904_0217"
branch_labels = None
depends_on = None


# NULLIF-guarded: an unset context leaves the setting empty, and a bare
# ''::int would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"


def _platform_base() -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "category", sa.String(length=16), nullable=False, server_default="info"
        ),
        sa.Column("sections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "min_platform_role",
            sa.String(length=16),
            nullable=False,
            server_default="member",
        ),
        sa.Column(
            "guild_admins_only", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # How many acknowledgements the notice asks for before it stops
        # coming back, and the route pattern it waits for (NULL = queue it on
        # sight). The pattern is matched by the SPA, which is the only thing
        # that knows what a route is.
        sa.Column(
            "dismissals_required", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("trigger_route", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_announcements_published_at", "announcements", ["published_at"])

    op.create_table(
        "announcement_reads",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("announcement_key", sa.String(length=120), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismiss_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "announcement_key"),
    )

    op.create_table(
        "announcement_images",
        sa.Column("sha256", sa.String(length=64), primary_key=True),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )

    base = _platform_base()
    request_roles = f'app_guild_base, "{base}", app_user'
    statements = [
        # --- announcements -------------------------------------------------
        f"REVOKE ALL ON TABLE public.announcements FROM {request_roles}",
        f"REVOKE ALL ON SEQUENCE public.announcements_id_seq FROM {request_roles}",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.announcements "
        "TO app_admin",
        "GRANT USAGE ON SEQUENCE public.announcements_id_seq TO app_admin",
        # Read-only for the request path, and only what is live. A guild-routed
        # request reads them too: the notices follow the account, and the
        # frontend fetches them from whichever page the person is on.
        f'GRANT SELECT ON TABLE public.announcements TO app_guild_base, "{base}"',
        "ALTER TABLE public.announcements ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.announcements FORCE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS announcement_live_read ON public.announcements",
        "CREATE POLICY announcement_live_read ON public.announcements "
        f'AS PERMISSIVE FOR SELECT TO app_guild_base, "{base}" '
        "USING ("
        "published_at IS NOT NULL AND published_at <= now() "
        "AND (expires_at IS NULL OR expires_at > now())"
        ")",
        # --- announcement_reads ---------------------------------------------
        f"REVOKE ALL ON TABLE public.announcement_reads FROM {request_roles}",
        "GRANT SELECT, DELETE ON TABLE public.announcement_reads TO app_admin",
        # A receipt is written by the person it belongs to, on the platform
        # path — the only path that serves the announcement list.
        f'GRANT SELECT, INSERT, UPDATE ON TABLE public.announcement_reads TO "{base}"',
        "ALTER TABLE public.announcement_reads ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.announcement_reads FORCE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS announcement_read_self ON public.announcement_reads",
        "CREATE POLICY announcement_read_self ON public.announcement_reads "
        f'AS PERMISSIVE FOR SELECT TO "{base}" USING (user_id = {_USER_ID})',
        "DROP POLICY IF EXISTS announcement_read_self_insert "
        "ON public.announcement_reads",
        "CREATE POLICY announcement_read_self_insert ON public.announcement_reads "
        f'AS PERMISSIVE FOR INSERT TO "{base}" WITH CHECK (user_id = {_USER_ID})',
        "DROP POLICY IF EXISTS announcement_read_self_update "
        "ON public.announcement_reads",
        "CREATE POLICY announcement_read_self_update ON public.announcement_reads "
        f'AS PERMISSIVE FOR UPDATE TO "{base}" '
        f"USING (user_id = {_USER_ID}) WITH CHECK (user_id = {_USER_ID})",
        # --- announcement_images ---------------------------------------------
        f"REVOKE ALL ON TABLE public.announcement_images FROM {request_roles}",
        "GRANT SELECT, INSERT, DELETE ON TABLE public.announcement_images TO app_admin",
        "ALTER TABLE public.announcement_images ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE public.announcement_images FORCE ROW LEVEL SECURITY",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS announcement_read_self_update "
        "ON public.announcement_reads"
    )
    op.execute(
        "DROP POLICY IF EXISTS announcement_read_self_insert "
        "ON public.announcement_reads"
    )
    op.execute(
        "DROP POLICY IF EXISTS announcement_read_self ON public.announcement_reads"
    )
    op.execute("DROP POLICY IF EXISTS announcement_live_read ON public.announcements")
    op.execute("ALTER TABLE public.announcement_images DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.announcement_reads DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.announcements DISABLE ROW LEVEL SECURITY")
    op.drop_table("announcement_images")
    op.drop_table("announcement_reads")
    op.drop_index("ix_announcements_published_at", table_name="announcements")
    op.drop_table("announcements")
