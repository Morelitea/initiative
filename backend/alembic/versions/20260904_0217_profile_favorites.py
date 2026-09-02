"""Who one account has starred on My Contacts

``public.profile_favorites`` holds the top section of the My Contacts page: a
row is one person on one person's list.

Access shape:

* **Your list is yours to read.** SELECT is scoped to ``user_id``, and
  deliberately not also to ``favorite_user_id`` — the list is one-directional,
  so who has starred *you* is not a question this table answers for anybody.
* **Your list is yours to write.** INSERT and DELETE carry the same own-row
  predicate.
* **Nothing is UPDATE-able**, so no UPDATE policy is created and no UPDATE is
  granted. A row is (who, whom, when); an unstar is a delete.
* Clearing an anonymized account off other people's lists runs on the system
  engine, which is why no request-path policy mentions it.

The schema's default privileges make every new ``public`` table writable by the
routed base roles, so they are wound back before anything else and granted
again deliberately.

Revision ID: 20260904_0217
Revises: 20260903_0216
Create Date: 2026-09-04
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260904_0217"
down_revision = "20260903_0216"
branch_labels = None
depends_on = None


# NULLIF-guarded: an unset context leaves the value empty, and a bare ''::int
# would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"

_TABLE = "public.profile_favorites"


def _platform(role: str) -> str:
    return f'"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"'


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "profile_favorites",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("favorite_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["favorite_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "favorite_user_id"),
        sa.CheckConstraint(
            "user_id <> favorite_user_id", name="ck_profile_favorites_not_self"
        ),
    )
    # The primary key covers ``user_id`` as a prefix, which is the read the page
    # makes. This is the other direction: every list an account appears on.
    op.create_index(
        "ix_profile_favorites_favorite_user",
        "profile_favorites",
        ["favorite_user_id"],
    )

    base = _platform("base")
    request_roles = f"app_guild_base, {base}, app_user"
    _run(
        [
            f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE {_TABLE} FROM {request_roles}",
            # The page runs on the platform tiers, which inherit this floor.
            # Nothing inside a guild reads the table, and nothing reads it
            # before a session is routed, so neither of the other two is
            # granted anything.
            f"GRANT SELECT, INSERT, DELETE ON TABLE {_TABLE} TO {base}",
            f"GRANT SELECT, DELETE ON TABLE {_TABLE} TO app_admin",
            f"DROP POLICY IF EXISTS profile_favorites_self_read ON {_TABLE}",
            f"CREATE POLICY profile_favorites_self_read ON {_TABLE} "
            f"AS PERMISSIVE FOR SELECT TO {base} "
            f"USING (user_id = {_USER_ID})",
            f"DROP POLICY IF EXISTS profile_favorites_self_insert ON {_TABLE}",
            f"CREATE POLICY profile_favorites_self_insert ON {_TABLE} "
            f"AS PERMISSIVE FOR INSERT TO {base} "
            f"WITH CHECK (user_id = {_USER_ID})",
            f"DROP POLICY IF EXISTS profile_favorites_self_delete ON {_TABLE}",
            f"CREATE POLICY profile_favorites_self_delete ON {_TABLE} "
            f"AS PERMISSIVE FOR DELETE TO {base} "
            f"USING (user_id = {_USER_ID})",
        ]
    )


def downgrade() -> None:
    _run(
        [
            f"DROP POLICY IF EXISTS profile_favorites_self_delete ON {_TABLE}",
            f"DROP POLICY IF EXISTS profile_favorites_self_insert ON {_TABLE}",
            f"DROP POLICY IF EXISTS profile_favorites_self_read ON {_TABLE}",
            f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_index("ix_profile_favorites_favorite_user", table_name="profile_favorites")
    op.drop_table("profile_favorites")
