"""Take the retired badges off the profiles still wearing them.

Three badges shipped with every account — ``core.founder``, ``core.storyteller``
and ``core.trailblazer`` — and were removed, because a badge everybody has is
not a mark of belonging to anything. The client draws only ids it has artwork
for, so a profile still naming one renders bare rather than wrong; but "my
badges vanished and the picker says I am wearing something" is a worse answer
than "my badges are gone", so the ids come out of the stored look as well.

Writes to ``public.users``, which is FORCE RLS: the owner is bound by its own
policies, and those key on request GUCs a migration has no value for, so the
UPDATE would match nothing at all. FORCE is lifted for the statement and put
straight back.

Revision ID: 20260903_0216
Revises: 20260902_0215
Create Date: 2026-09-03
"""

from alembic import op

revision = "20260903_0216"
down_revision = "20260902_0215"
branch_labels = None
depends_on = None

RETIRED = ("core.founder", "core.storyteller", "core.trailblazer")


def upgrade() -> None:
    retired = ", ".join(f"'{badge}'" for badge in RETIRED)
    op.execute("ALTER TABLE public.users NO FORCE ROW LEVEL SECURITY")
    try:
        op.execute(
            f"""
            UPDATE public.users
            SET profile_decorations = jsonb_set(
                profile_decorations,
                '{{badges}}',
                COALESCE(
                    (
                        SELECT jsonb_agg(badge)
                        FROM jsonb_array_elements_text(profile_decorations->'badges') AS badge
                        WHERE badge NOT IN ({retired})
                    ),
                    '[]'::jsonb
                )
            )
            WHERE profile_decorations->'badges' @> '["core.founder"]'
               OR profile_decorations->'badges' @> '["core.storyteller"]'
               OR profile_decorations->'badges' @> '["core.trailblazer"]'
            """
        )
    finally:
        op.execute("ALTER TABLE public.users FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Nothing to put back: the badges they named no longer exist."""
