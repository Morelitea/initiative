"""Give notification settings a home of their own, and the inbox its own rule

Twenty boolean columns on ``public.users`` held what an account wanted to hear
about. Two things were wrong with that. They gated email and push only, so the
bell was written unconditionally and could not be turned down at all; and they
sat on the table the platform tiers read whole, when what somebody has chosen
to hear about is their own business.

Both are settled here. ``user_notification_prefs`` holds one sparse settings
document per account, reachable by that account and the system engine that
delivers for it — the shape and the reasoning ``user_dm_settings`` already
established. A key exists only where a default has been overridden, so an
account that never opens the page stores ``{}`` and a community joined tomorrow
needs no write.

``public.notifications`` gains the same rule. It had none: the request roles
hold DML on it and every query scoped itself in the application. The policies
here say the same thing one layer down, where it is the database's answer
rather than the query's.

It also gains the place a notification happened — guild, initiative and tool,
each independently optional — promoted out of the JSON payload that already
carries them so that "where is there something unread" is an index-only scan
rather than a scan of the whole inbox.

Ordering follows the rule for a table under FORCE RLS: create, move the rows
in, and only then lock it down. The backfill runs before any policy exists,
because a migration has no request context for one to match.

Revision ID: 20260909_0245
Revises: 20260909_0244
Create Date: 2026-09-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260909_0245"
down_revision = "20260909_0244"
branch_labels = None
depends_on = None


_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"


def _base_roles() -> tuple[str, ...]:
    """Roles the request path assumes.

    Every platform tier inherits the platform base and every guild role
    inherits ``app_guild_base``, so a policy granted to the two bases covers
    both halves of the request path. The platform ladder is prefixed per test
    worker, so it is read from settings rather than spelled out.
    """
    return (f"{settings.PLATFORM_ROLE_PREFIX}platform_base", "app_guild_base")


#: The read half of ``app_guild_base``, which the query role and ``guild_<id>_ro``
#: inherit. It takes no default privileges, so the table is granted and policed
#: for it here rather than arriving with the schema (0239); it reads the same one
#: row and writes nothing. ``guild_base_ro_parity_test`` is what asks for this.
_READ_FLOOR = "app_guild_base_ro"


#: Old column -> the categories it gated. ``email_mentions`` gated five
#: notification types that are now three categories, so it seeds all three:
#: somebody who switched it off wanted all of it off.
_EMAIL_SOURCES: dict[str, tuple[str, ...]] = {
    "email_mentions": ("mentions", "replies", "comments"),
    "email_comment_reactions": ("reactions",),
    "email_task_assignment": ("assignments",),
    "email_overdue_tasks": ("due_dates",),
    "email_posts": ("posts",),
    "email_events": ("events",),
    "email_event_reminders": ("event_reminders",),
    "email_direct_messages": ("direct_messages",),
}
_PUSH_SOURCES: dict[str, tuple[str, ...]] = {
    "push_mentions": ("mentions", "replies", "comments"),
    "push_comment_reactions": ("reactions",),
    "push_task_assignment": ("assignments",),
    "push_overdue_tasks": ("due_dates",),
    "push_posts": ("posts",),
    "push_events": ("events",),
    "push_event_reminders": ("event_reminders",),
    "push_direct_messages": ("direct_messages",),
}

#: ``initiative_addition`` and ``project_added`` both land in ``membership``,
#: so the merged value is off only when both were. Switching a category off
#: because one of its two sources was off would take something away that was
#: never asked for; the other direction only ever leaves one extra kind of
#: notice arriving, which the account can then turn off itself.
_MEMBERSHIP_SOURCES = {
    "email": ("email_initiative_addition", "email_project_added"),
    "push": ("push_initiative_addition", "push_project_added"),
}

_DROPPED_COLUMNS = (
    "email_initiative_addition",
    "email_task_assignment",
    "email_project_added",
    "email_overdue_tasks",
    "email_mentions",
    "email_comment_reactions",
    "push_initiative_addition",
    "push_task_assignment",
    "push_project_added",
    "push_overdue_tasks",
    "push_mentions",
    "push_comment_reactions",
    "email_direct_messages",
    "push_direct_messages",
    "email_posts",
    "push_posts",
    "email_events",
    "push_events",
    "email_event_reminders",
    "push_event_reminders",
)


def _backfill_expression() -> str:
    """One JSONB object per account, built from whichever columns are off.

    ``jsonb_strip_nulls`` over a rebuilt object is what keeps it sparse: a
    column left on contributes nothing, and an account that changed nothing
    ends with ``{}``.
    """
    legs: list[str] = []
    per_category: dict[str, list[str]] = {}
    for column, categories in _EMAIL_SOURCES.items():
        for category in categories:
            per_category.setdefault(category, []).append(
                f"'email', CASE WHEN {column} IS FALSE THEN to_jsonb(false) END"
            )
    for column, categories in _PUSH_SOURCES.items():
        for category in categories:
            per_category.setdefault(category, []).append(
                f"'push', CASE WHEN {column} IS FALSE THEN to_jsonb(false) END"
            )
    for channel, columns in _MEMBERSHIP_SOURCES.items():
        both_off = " AND ".join(f"{column} IS FALSE" for column in columns)
        per_category.setdefault("membership", []).append(
            f"'{channel}', CASE WHEN {both_off} THEN to_jsonb(false) END"
        )
    for category, pairs in sorted(per_category.items()):
        legs.append(
            f"'{category}', "
            f"NULLIF(jsonb_strip_nulls(jsonb_build_object({', '.join(pairs)})), '{{}}')"
        )
    categories = (
        f"NULLIF(jsonb_strip_nulls(jsonb_build_object({', '.join(legs)})), '{{}}')"
    )
    return "jsonb_strip_nulls(jsonb_build_object('categories', " + categories + "))"


def upgrade() -> None:
    conn = op.get_bind()

    # --- the settings document ------------------------------------------------
    op.create_table(
        "user_notification_prefs",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "prefs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Rows first, policies after: FORCE RLS binds the owner too, and a
    # migration carries none of the request context a policy reads.
    result = conn.execute(
        sa.text(
            "INSERT INTO public.user_notification_prefs "
            "  (user_id, prefs, created_at, updated_at) "
            "SELECT id, " + _backfill_expression() + ", now(), now() "
            "FROM public.users"
        )
    )
    accounts = conn.execute(sa.text("SELECT count(*) FROM public.users")).scalar_one()
    seeded = conn.execute(
        sa.text("SELECT count(*) FROM public.user_notification_prefs")
    ).scalar_one()
    if seeded != accounts:
        raise RuntimeError(
            f"user_notification_prefs backfill covered {seeded} of {accounts} accounts"
        )
    # A silent no-op write is the failure this catches; rowcount is -1 on some
    # drivers, so it is only checked when the driver reports one.
    if result.rowcount not in (-1, accounts):
        raise RuntimeError(
            f"user_notification_prefs insert reported {result.rowcount} rows "
            f"for {accounts} accounts"
        )

    op.execute("ALTER TABLE public.user_notification_prefs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.user_notification_prefs FORCE ROW LEVEL SECURITY")
    for base in _base_roles():
        op.execute(
            f'GRANT SELECT, INSERT, UPDATE ON TABLE public.user_notification_prefs TO "{base}"'
        )
        for command in ("SELECT", "INSERT", "UPDATE"):
            name = f"user_notification_prefs_self_{command.lower()}_{base}"
            clause = (
                f"WITH CHECK (user_id = {_USER_ID})"
                if command == "INSERT"
                else f"USING (user_id = {_USER_ID})"
                + (f" WITH CHECK (user_id = {_USER_ID})" if command == "UPDATE" else "")
            )
            op.execute(
                f"CREATE POLICY {name} ON public.user_notification_prefs "
                f'AS PERMISSIVE FOR {command} TO "{base}" {clause}'
            )
    op.execute(
        f'GRANT SELECT ON TABLE public.user_notification_prefs TO "{_READ_FLOOR}"'
    )
    op.execute(
        f"CREATE POLICY user_notification_prefs_self_select_{_READ_FLOOR} "
        "ON public.user_notification_prefs AS PERMISSIVE FOR SELECT "
        f'TO "{_READ_FLOOR}" USING (user_id = {_USER_ID})'
    )
    # The system engine seeds a new account's row and reads it while delivering.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_notification_prefs "
        "TO app_admin"
    )

    # --- where a notification happened ---------------------------------------
    op.add_column("notifications", sa.Column("guild_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "notifications_guild_id_fkey",
        "notifications",
        "guilds",
        ["guild_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column(
        "notifications", sa.Column("initiative_id", sa.Integer(), nullable=True)
    )
    op.add_column("notifications", sa.Column("tool", sa.String(32), nullable=True))

    # Promoted out of the payload that already carries them. A guild id naming
    # a row that has since gone stays NULL rather than failing the migration.
    op.execute(
        """
        UPDATE public.notifications AS n
           SET guild_id = g.id
          FROM public.guilds AS g
         WHERE g.id = NULLIF(n.data->>'guild_id', '')::int
        """
    )
    op.execute(
        """
        UPDATE public.notifications
           SET initiative_id = NULLIF(data->>'initiative_id', '')::int
         WHERE data->>'initiative_id' ~ '^[0-9]+$'
        """
    )
    op.execute(
        """
        UPDATE public.notifications
           SET tool = data->>'entity_type'
         WHERE data->>'entity_type' IN
               ('project','document','queue','counter_group','calendar',
                'dashboard','post')
        """
    )
    op.create_index(
        "ix_notifications_unread_place",
        "notifications",
        ["user_id", "guild_id", "initiative_id", "tool"],
        postgresql_where=sa.text("read_at IS NULL"),
    )

    # --- the inbox answers to its owner --------------------------------------
    op.execute("ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.notifications FORCE ROW LEVEL SECURITY")
    for base in _base_roles():
        for command in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            name = f"notifications_self_{command.lower()}_{base}"
            if command == "INSERT":
                clause = f"WITH CHECK (user_id = {_USER_ID})"
            elif command == "UPDATE":
                clause = (
                    f"USING (user_id = {_USER_ID}) WITH CHECK (user_id = {_USER_ID})"
                )
            else:
                clause = f"USING (user_id = {_USER_ID})"
            op.execute(
                f"CREATE POLICY {name} ON public.notifications "
                f'AS PERMISSIVE FOR {command} TO "{base}" {clause}'
            )

    # --- the columns the document replaces -----------------------------------
    for column in _DROPPED_COLUMNS:
        op.drop_column("users", column)


def _restore_expression() -> str:
    """The reverse of the backfill: each column false where the document says so.

    A downgrade that recreated the columns at their default would discard every
    opt-out the account had made, so the values come back out of the document
    before it is dropped. ``membership`` seeded two columns, and both take its
    value back.
    """
    legs: list[str] = []
    for column, categories in _EMAIL_SOURCES.items():
        # A column that seeded several categories is back off only if every one
        # of them is off — the same direction the merge went.
        tests = " AND ".join(
            f"(p.prefs #>> '{{categories,{category},email}}') = 'false'"
            for category in categories
        )
        legs.append(f"{column} = NOT ({tests})")
    for column, categories in _PUSH_SOURCES.items():
        tests = " AND ".join(
            f"(p.prefs #>> '{{categories,{category},push}}') = 'false'"
            for category in categories
        )
        legs.append(f"{column} = NOT ({tests})")
    for channel, columns in _MEMBERSHIP_SOURCES.items():
        test = f"(p.prefs #>> '{{categories,membership,{channel}}}') = 'false'"
        for column in columns:
            legs.append(f"{column} = NOT {test}")
    return ", ".join(legs)


def downgrade() -> None:
    conn = op.get_bind()
    for column in _DROPPED_COLUMNS:
        op.add_column(
            "users",
            sa.Column(
                column, sa.Boolean(), nullable=False, server_default=sa.text("true")
            ),
        )
    # Values first, while the document still exists.
    conn.execute(
        sa.text(
            "UPDATE public.users AS u SET " + _restore_expression() + " "
            "FROM public.user_notification_prefs AS p WHERE p.user_id = u.id"
        )
    )

    for base in _base_roles():
        for command in ("select", "insert", "update", "delete"):
            op.execute(
                f"DROP POLICY IF EXISTS notifications_self_{command}_{base} "
                "ON public.notifications"
            )
    op.execute("ALTER TABLE public.notifications NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.notifications DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_notifications_unread_place", table_name="notifications")
    op.drop_constraint(
        "notifications_guild_id_fkey", "notifications", type_="foreignkey"
    )
    op.drop_column("notifications", "tool")
    op.drop_column("notifications", "initiative_id")
    op.drop_column("notifications", "guild_id")

    for base in _base_roles():
        for command in ("select", "insert", "update"):
            op.execute(
                f"DROP POLICY IF EXISTS user_notification_prefs_self_{command}_{base} "
                "ON public.user_notification_prefs"
            )
    op.execute(
        f"DROP POLICY IF EXISTS user_notification_prefs_self_select_{_READ_FLOOR} "
        "ON public.user_notification_prefs"
    )
    op.execute("ALTER TABLE public.user_notification_prefs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.user_notification_prefs DISABLE ROW LEVEL SECURITY")
    op.drop_table("user_notification_prefs")
