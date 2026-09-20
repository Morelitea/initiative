"""an account agrees to the terms

``public.legal_acceptances`` is the record that an account was shown this
deployment's terms and privacy policy and agreed to them. A row is one
acceptance of one document: an event, not a state. Re-consent appends;
nothing updates a row, and only the cascade off ``users`` removes one.

Access shape:

* **Your consent record is yours to read.** SELECT is scoped to ``user_id``.
* **Your consent record is yours to add to.** INSERT carries the same own-row
  predicate — the after-sign-in screen writes through the account's own
  session.
* **Nothing is UPDATE-able or DELETE-able on the request path**, so neither a
  policy nor a grant exists for either.
* Registration itself runs on the system engine, which is why that role holds
  SELECT and INSERT.

The schema's default privileges make every new ``public`` table writable by
the routed base roles, so they are wound back before anything else and
granted again deliberately.

Revision ID: 20260919_0321
Revises: 20260919_0320
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260919_0321"
down_revision = "20260919_0320"
branch_labels = None
depends_on = None


# NULLIF-guarded: an unset context leaves the value empty, and a bare ''::int
# would raise and fault the whole query rather than fail the policy.
_USER_ID = "NULLIF(current_setting('app.current_user_id', true), '')::int"

_TABLE = "public.legal_acceptances"


def _platform(role: str) -> str:
    return f'"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"'


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "legal_acceptances",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document", sa.String(32), nullable=False),
        sa.Column("version", sa.String(32), nullable=True),
        sa.Column("document_sha256", sa.String(64), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )
    # The one read there is: has this account accepted this document.
    op.create_index(
        "ix_legal_acceptances_user_document",
        "legal_acceptances",
        ["user_id", "document"],
    )

    base = _platform("base")
    request_roles = f"app_guild_base, {base}, app_user"
    _run(
        [
            f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE {_TABLE} FROM {request_roles}",
            "REVOKE ALL ON SEQUENCE public.legal_acceptances_id_seq "
            f"FROM {request_roles}",
            # The screen that asks runs on the platform tiers, which inherit
            # this floor. Nothing inside a guild reads the table, and nothing
            # reads it before a session is routed.
            f"GRANT SELECT, INSERT ON TABLE {_TABLE} TO {base}",
            f"GRANT USAGE, SELECT ON SEQUENCE public.legal_acceptances_id_seq TO {base}",
            f"GRANT SELECT, INSERT ON TABLE {_TABLE} TO app_admin",
            "GRANT USAGE, SELECT ON SEQUENCE public.legal_acceptances_id_seq "
            "TO app_admin",
            f"DROP POLICY IF EXISTS legal_acceptances_self_read ON {_TABLE}",
            f"CREATE POLICY legal_acceptances_self_read ON {_TABLE} "
            f"AS PERMISSIVE FOR SELECT TO {base} "
            f"USING (user_id = {_USER_ID})",
            f"DROP POLICY IF EXISTS legal_acceptances_self_insert ON {_TABLE}",
            f"CREATE POLICY legal_acceptances_self_insert ON {_TABLE} "
            f"AS PERMISSIVE FOR INSERT TO {base} "
            f"WITH CHECK (user_id = {_USER_ID})",
        ]
    )


def downgrade() -> None:
    _run(
        [
            f"DROP POLICY IF EXISTS legal_acceptances_self_insert ON {_TABLE}",
            f"DROP POLICY IF EXISTS legal_acceptances_self_read ON {_TABLE}",
            f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY",
        ]
    )
    op.drop_index("ix_legal_acceptances_user_document", table_name="legal_acceptances")
    op.drop_table("legal_acceptances")
