"""A provider says whether its word counts for a second factor.

An identity provider that ran a second factor names it in the ``amr`` of the
token it returns, and that value has been read straight into the session's own
markers — the set a community's sign-in rule and the deployment's own
requirement are both written against. Whether a given provider's word is worth
anything is a judgement about that provider, so it becomes a column the
operator who registered it answers.

``false`` on every existing row except the ones whose product documents the
claim: Entra, Okta and Auth0 emit ``amr`` with ``mfa`` when one ran. Google is
not among them — it does not emit ``amr`` at all — so a deployment signing in
through Google is unaffected either way.

The backfill is keyed on ``slug``, which is what the setup wizard writes for a
preset and what an operator may have changed. A deployment that renamed one
answers the question on the provider's own page.

Revision ID: 20260921_0339
Revises: 20260920_0338
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260921_0339"
down_revision = "20260920_0338"
branch_labels = None
depends_on = None

#: The presets whose product documents an ``amr`` carrying ``mfa``. Narrow on
#: purpose: a provider that is not here is asked about rather than guessed at.
KNOWN_ASSERTING_SLUGS = ("microsoft", "okta", "auth0")


def upgrade() -> None:
    op.add_column(
        "auth_providers",
        sa.Column(
            "asserts_second_factor",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # ``auth_providers`` is ENABLE + FORCE with no policies, and FORCE binds
    # the owner this migration runs as, so the UPDATE below would match no rows
    # at all. Lift it for the write and restore it in the same transaction.
    op.execute("ALTER TABLE auth_providers NO FORCE ROW LEVEL SECURITY")
    try:
        touched = (
            op.get_bind()
            .execute(
                sa.text(
                    "UPDATE auth_providers SET asserts_second_factor = true "
                    "WHERE slug = ANY(:slugs)"
                ).bindparams(sa.bindparam("slugs", list(KNOWN_ASSERTING_SLUGS)))
            )
            .rowcount
        )
        print(f"asserts_second_factor: {touched} provider(s) carried over")
    finally:
        op.execute("ALTER TABLE auth_providers FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_column("auth_providers", "asserts_second_factor")
