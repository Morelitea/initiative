"""comment reactions

Emoji reactions, built as a general facility rather than a comment feature.

Two guild-scoped tables:

* ``reactions`` — one row per (person, emoji, target), where the target is named
  polymorphically by ``(target_type, target_id)``. The CHECK constraint's
  vocabulary comes from ``app.core.reactions.REACTION_TARGETS``, so the next
  reactable kind extends it the way ``recent_views`` and ``search_entries``
  extend theirs.
* ``reaction_digest_items`` — the queue behind the "someone reacted to your
  post" email/push digest, the same bookkeeping shape as
  ``task_assignment_digest_items``.

Both are created, indexed and locked down in one pass because both start EMPTY:
there is nothing to carry in, so the create-then-backfill-then-FORCE ordering a
populated table requires does not apply.

``public.users`` gains the pair of preference columns that gate the reaction
digest. Reactions get their OWN gate rather than riding on ``*_mentions``: a
reaction is a far lighter signal than being named.

The RLS policies here match ``reactions_path()`` in
``app/db/initiative_rls.py`` — a reaction is reached by whoever can reach the
thing it is on, which for a comment is that comment's own multi-parent gate.
The registry edit bumps the provisioning stamp, so new guilds render the same
policies from it and existing ones pick them up on the next boot backfill.

Revision ID: 20260902_0210
Revises: 20260901_0209
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings
from app.db.guild_migrations import run_for_each_guild_schema

revision = "20260902_0210"
down_revision = "20260901_0209"
branch_labels = None
depends_on = None

#: Target kinds this migration was written with, frozen as its CHECK
#: constraint (spelled out rather than read from ``app.core.reactions``: a
#: later member must not reach back and change what this revision does). A new
#: kind extends it in its own migration, the same way ``recent_views`` does.
TARGET_TYPES = ("comment",)
_TARGET_VALUES = ", ".join(f"'{value}'" for value in TARGET_TYPES)

#: The initiative gate, matching ``reactions_path()`` in
#: ``app/db/initiative_rls.py``: a reaction is reached by whoever can reach the
#: thing it is on, which for a comment is that comment's own multi-parent gate
#: (one leg per comment parent, as of this revision).
_UID = "(NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer"

#: (comment column, FROM clause, tie to the comment row, initiative column).
_COMMENT_PARENTS = (
    (
        "task_id",
        "tasks tk JOIN projects pr ON pr.id = tk.project_id",
        "tk.id",
        "pr.initiative_id",
    ),
    ("document_id", "documents d", "d.id", "d.initiative_id"),
    ("project_id", "projects p", "p.id", "p.initiative_id"),
    ("queue_id", "queues q", "q.id", "q.initiative_id"),
    ("counter_group_id", "counter_groups cg", "cg.id", "cg.initiative_id"),
    ("calendar_id", "calendars cal", "cal.id", "cal.initiative_id"),
    ("dashboard_id", "dashboards dsh", "dsh.id", "dsh.initiative_id"),
)


def _comment_access(write: bool) -> str:
    """Whether the request may reach the comment aliased ``rt``."""
    flag = "true" if write else "false"
    legs = [
        f"(rt.{col} IS NOT NULL AND EXISTS ("
        f"SELECT 1 FROM {frm} WHERE {tie} = rt.{col} "
        f"AND public.initiative_access({init}, {_UID}, {flag})))"
        for col, frm, tie, init in _COMMENT_PARENTS
    ]
    return "(" + " OR ".join(legs) + ")"


def _access(table: str, write: bool) -> str:
    """The policy body for one of the two reaction tables."""
    return (
        f"({table}.target_type = 'comment' AND EXISTS ("
        f"SELECT 1 FROM comments rt WHERE rt.id = {table}.target_id "
        f"AND {_comment_access(write)}))"
    )


#: The digest preference columns added to ``public.users``.
_USER_PREFS = ("email_comment_reactions", "push_comment_reactions")

#: ``reactions.guild_id`` is denormalized off the target the same way
#: ``comments.guild_id`` is denormalized off its parent — the shared function
#: reads the target table unqualified, so under
#: ``search_path = <guild_schema>, public`` it finds that guild's own rows.
_GUILD_ID_FN = """
CREATE OR REPLACE FUNCTION public.fn_reactions_set_guild_id() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            IF NEW.guild_id IS NULL OR
               (TG_OP = 'UPDATE' AND (OLD.target_type IS DISTINCT FROM NEW.target_type
                    OR OLD.target_id IS DISTINCT FROM NEW.target_id)) THEN
                IF NEW.target_type = 'comment' THEN
                    SELECT guild_id INTO NEW.guild_id FROM comments WHERE id = NEW.target_id;
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
"""

_GUILD_ID_TRIGGER = (
    "CREATE OR REPLACE TRIGGER tr_reactions_set_guild_id "
    "BEFORE INSERT OR UPDATE OF target_type, target_id ON reactions "
    "FOR EACH ROW EXECUTE FUNCTION public.fn_reactions_set_guild_id()"
)

_POLICY_NAMES = (
    "initiative_member_select",
    "initiative_member_insert",
    "initiative_member_update",
    "initiative_member_delete",
)


def _policies(table: str) -> list[str]:
    read = _access(table, False)
    write = _access(table, True)
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
        f"CREATE POLICY initiative_member_select ON {table} "
        f"AS PERMISSIVE FOR SELECT USING ({read})",
        f"CREATE POLICY initiative_member_insert ON {table} "
        f"AS PERMISSIVE FOR INSERT WITH CHECK ({write})",
        f"CREATE POLICY initiative_member_update ON {table} "
        f"AS PERMISSIVE FOR UPDATE USING ({write}) WITH CHECK ({write})",
        f"CREATE POLICY initiative_member_delete ON {table} "
        f"AS PERMISSIVE FOR DELETE USING ({write})",
    ]


def upgrade() -> None:
    for column in _USER_PREFS:
        op.add_column(
            "users",
            sa.Column(
                column,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    # 0144 replaced the request path's table-wide UPDATE on ``public.users``
    # with a column list computed from the catalog at that revision, so a
    # column added later is not in it. Name the new ones explicitly — the
    # own-row policies from 0202 still decide *whose* row they reach.
    platform_base = f"{settings.PLATFORM_ROLE_PREFIX}platform_base"
    for role in ("app_user", "app_guild_base", platform_base):
        op.execute(
            f'GRANT UPDATE ({", ".join(_USER_PREFS)}) ON TABLE public.users TO "{role}"'
        )
    # The trigger function is shared in public — applied once, outside the loop.
    op.execute(_GUILD_ID_FN)
    run_for_each_guild_schema(op.get_bind(), _apply_upgrade)


def _apply_upgrade() -> None:
    op.create_table(
        "reactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_type",
            "target_id",
            "created_by",
            "emoji",
            name="uq_reactions_target_user_emoji",
        ),
    )
    op.execute(
        "ALTER TABLE reactions ADD CONSTRAINT ck_reactions_target_type "
        f"CHECK (target_type IN ({_TARGET_VALUES}))"
    )
    # The thread's chips are read by target, always.
    op.execute("CREATE INDEX ix_reactions_target ON reactions (target_type, target_id)")
    op.execute(_GUILD_ID_TRIGGER)

    op.create_table(
        "reaction_digest_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("reaction_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=False),
        sa.Column("target_path", sa.Text(), nullable=False),
        sa.Column("context_title", sa.String(length=255), nullable=False),
        sa.Column("reactor_name", sa.String(length=255), nullable=False),
        sa.Column("reactor_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX ix_reaction_digest_items_user_id "
        "ON reaction_digest_items (user_id)"
    )
    # The withdraw path (un-reacting inside the quiet period) looks the queue
    # up by the reaction it came from.
    op.execute(
        "CREATE INDEX ix_reaction_digest_items_reaction_id "
        "ON reaction_digest_items (reaction_id)"
    )

    # Locked down at creation: both tables are empty, so there is no backfill
    # to order before FORCE.
    for table in ("reactions", "reaction_digest_items"):
        for statement in _policies(table):
            op.execute(statement)


def downgrade() -> None:
    run_for_each_guild_schema(op.get_bind(), _apply_downgrade)
    op.execute("DROP FUNCTION IF EXISTS public.fn_reactions_set_guild_id()")
    for column in _USER_PREFS:
        op.drop_column("users", column)


def _apply_downgrade() -> None:
    for table in ("reaction_digest_items", "reactions"):
        for name in _POLICY_NAMES:
            op.execute(f"DROP POLICY IF EXISTS {name} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TRIGGER IF EXISTS tr_reactions_set_guild_id ON reactions")
    op.drop_table("reaction_digest_items")
    op.drop_table("reactions")
