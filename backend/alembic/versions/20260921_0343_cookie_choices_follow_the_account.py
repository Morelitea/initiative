"""An account's cookie answer follows it to the next browser.

The answer has to exist in the browser as well: somebody reading the landing
page has no account, and the question is about what that browser keeps. This
table is what carries the answer to a browser that was never asked, and what
carries a change of mind back to one that was.

``user_cookie_consent`` holds one row per account -- the current answer, not a
history of them. Changing your mind replaces it, which is why this is a
settings row and not the append-only shape ``legal_acceptances`` uses.

There is nothing to carry in: an account that has never answered has no row,
and that is exactly what "not asked yet" looks like. So the table is created
and locked down in one go.

The request path reads and writes its own row and no other, through the two
base roles it assumes. The system engine reads (an account's own payload is
built on it during registration) and deletes; nothing else needs it.

Revision ID: 20260921_0343
Revises: 20260921_0342
Create Date: 2026-09-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.config import settings

revision = "20260921_0343"
down_revision = "20260921_0342"
branch_labels = None
depends_on = None


_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"

#: The read half of ``app_guild_base``, which the query role and
#: ``guild_<id>_ro`` inherit. It takes no default privileges, so the table is
#: granted and policed for it here rather than arriving with the schema.
_READ_FLOOR = "app_guild_base_ro"

#: The categories the app has names for. A value added later is an
#: ``ALTER TYPE``; see ``app.core.cookie_categories``.
_CATEGORIES = ("analytics", "marketing")


def _base_roles() -> tuple[str, ...]:
    """Roles the request path assumes.

    Every platform tier inherits the platform base and every guild role
    inherits ``app_guild_base``, so a policy granted to the two bases covers
    both halves of the request path. The platform ladder is prefixed per test
    worker, so it is read from settings rather than spelled out.
    """
    return (f"{settings.PLATFORM_ROLE_PREFIX}platform_base", "app_guild_base")


def upgrade() -> None:
    postgresql.ENUM(*_CATEGORIES, name="cookie_category").create(
        op.get_bind(), checkfirst=True
    )
    op.create_table(
        "user_cookie_consent",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "granted",
            postgresql.ARRAY(
                postgresql.ENUM(*_CATEGORIES, name="cookie_category", create_type=False)
            ),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.execute("ALTER TABLE public.user_cookie_consent ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.user_cookie_consent FORCE ROW LEVEL SECURITY")
    for base in _base_roles():
        op.execute(
            "GRANT SELECT, INSERT, UPDATE ON TABLE public.user_cookie_consent "
            f'TO "{base}"'
        )
        for command in ("SELECT", "INSERT", "UPDATE"):
            clause = (
                f"WITH CHECK (user_id = {_USER_ID})"
                if command == "INSERT"
                else f"USING (user_id = {_USER_ID})"
                + (f" WITH CHECK (user_id = {_USER_ID})" if command == "UPDATE" else "")
            )
            op.execute(
                f"CREATE POLICY user_cookie_consent_self_{command.lower()}_{base} "
                f"ON public.user_cookie_consent AS PERMISSIVE FOR {command} "
                f'TO "{base}" {clause}'
            )
    op.execute(f'GRANT SELECT ON TABLE public.user_cookie_consent TO "{_READ_FLOOR}"')
    op.execute(
        f"CREATE POLICY user_cookie_consent_self_select_{_READ_FLOOR} "
        "ON public.user_cookie_consent AS PERMISSIVE FOR SELECT "
        f'TO "{_READ_FLOOR}" USING (user_id = {_USER_ID})'
    )
    op.execute("GRANT SELECT, DELETE ON TABLE public.user_cookie_consent TO app_admin")


def downgrade() -> None:
    for base in _base_roles():
        for command in ("select", "insert", "update"):
            op.execute(
                f"DROP POLICY IF EXISTS user_cookie_consent_self_{command}_{base} "
                "ON public.user_cookie_consent"
            )
    op.execute(
        f"DROP POLICY IF EXISTS user_cookie_consent_self_select_{_READ_FLOOR} "
        "ON public.user_cookie_consent"
    )
    op.execute("ALTER TABLE public.user_cookie_consent NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.user_cookie_consent DISABLE ROW LEVEL SECURITY")
    op.drop_table("user_cookie_consent")
    postgresql.ENUM(name="cookie_category").drop(op.get_bind(), checkfirst=True)
