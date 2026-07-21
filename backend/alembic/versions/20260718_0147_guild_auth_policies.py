"""guild auth policies + database-layer session-satisfaction gate

Adds ``public.guild_auth_policies`` (per-guild sign-in requirement; no row =
open) and enforces it at the database layer, not just in the guild-access
gate:

* ``public.guild_auth_satisfied()`` reads the request's satisfied-provider
  GUC (``app.satisfied_providers``, set from the session token's ``sat``
  claim) against the current guild's policy row. Fail-closed: a required
  policy with no recorded satisfaction blocks. Two deliberate passes: a
  routing with no user context (pure system work — seeding, anonymize sweeps)
  and the explicit ``system`` sentinel a user-attributed background job sets
  after its enqueueing request already passed the gate.
* ``public.initiative_access`` gains a top-level AND on that function, so
  every initiative-scoped content table's RLS refuses an unsatisfied session
  uniformly — member, guild-admin, and PAM legs alike.

The table itself: readable on every request path (the gate runs pre-routing
on the login role, and the RLS function reads it under guild roles); written
only by the system engine (the guild-admin endpoint validates and writes
there). ``provider_id`` is ON DELETE RESTRICT — deleting a provider a guild
requires surfaces the conflict instead of silently reopening the guild.
"""

import sqlalchemy as sa
from alembic import op

from app.core.config import settings

revision = "20260718_0147"
down_revision = "20260717_0146"
branch_labels = None
depends_on = None

# NULLIF-guarded casts per the session-variable constants standard: an unset
# GUC is empty-string, and a bare ''::int would fault every policy on the table.
GUILD_AUTH_SATISFIED_FN = """
CREATE OR REPLACE FUNCTION public.guild_auth_satisfied() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id', true), '') IS NULL
        OR current_setting('app.satisfied_providers', true) = 'system'
        OR NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = NULLIF(
                    current_setting('app.current_guild_id', true), ''
                  )::int
              AND p.policy <> 'open'
              AND p.provider_id IS NOT NULL
              -- COALESCE keeps this fail-closed: an unset/empty GUC must
              -- read as "not satisfied", not SQL NULL.
              AND NOT COALESCE(
                    p.provider_id = ANY(
                        string_to_array(
                            NULLIF(
                                current_setting('app.satisfied_providers', true), ''
                            ),
                            ','
                        )::int[]
                    ),
                    false
                  )
        )
$$;
"""

# The prior body from the 0125 baseline, with the session-satisfaction gate
# AND-ed on top so every leg (guild-admin, PAM, member) honors it.
INITIATIVE_ACCESS_FN = """
CREATE OR REPLACE FUNCTION public.initiative_access(
    p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false
) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        public.guild_auth_satisfied()
        AND (
            current_setting('app.current_guild_role'::text, true) = 'admin'::text
            OR (CASE
                  WHEN p_need_write
                    THEN current_setting('app.pam_write'::text, true) = 'true'::text
                  ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                       OR current_setting('app.pam_write'::text, true) = 'true'::text
                END)
            OR EXISTS (
                SELECT 1 FROM initiative_members im
                WHERE im.initiative_id = p_initiative_id
                  AND im.user_id = p_user_id
            )
        )
$$;
"""

INITIATIVE_ACCESS_FN_PRIOR = """
CREATE OR REPLACE FUNCTION public.initiative_access(
    p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false
) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        current_setting('app.current_guild_role'::text, true) = 'admin'::text
        OR (CASE
              WHEN p_need_write
                THEN current_setting('app.pam_write'::text, true) = 'true'::text
              ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                   OR current_setting('app.pam_write'::text, true) = 'true'::text
            END)
        OR EXISTS (
            SELECT 1 FROM initiative_members im
            WHERE im.initiative_id = p_initiative_id
              AND im.user_id = p_user_id
        )
$$;
"""


def _platform(role: str) -> str:
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_{role}"


def _run(statements: list[str]) -> None:
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.create_table(
        "guild_auth_policies",
        sa.Column("guild_id", sa.Integer(), primary_key=True),
        sa.Column("policy", sa.String(length=16), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("provider_slug", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["auth_providers.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "policy IN ('open', 'required')", name="ck_guild_auth_policies_policy"
        ),
        sa.CheckConstraint(
            "policy = 'open' OR (provider_id IS NOT NULL AND provider_slug IS NOT NULL)",
            name="ck_guild_auth_policies_required_provider",
        ),
    )

    base = _platform("base")
    _run(
        [
            "ALTER TABLE public.guild_auth_policies ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE public.guild_auth_policies FORCE ROW LEVEL SECURITY",
            # Non-secret sign-in config, read by the access gate before any
            # guild context exists and by the RLS function under guild roles.
            (
                "CREATE POLICY guild_auth_policies_read ON public.guild_auth_policies "
                "FOR SELECT USING (true)"
            ),
            # Writes go through the system engine only (the guild-admin
            # endpoint validates the provider there).
            f'REVOKE ALL ON TABLE public.guild_auth_policies FROM app_guild_base, "{base}"',
            f'GRANT SELECT ON TABLE public.guild_auth_policies TO app_guild_base, "{base}", app_user',
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.guild_auth_policies TO app_admin",
            # initiative_access references the guild-local initiative_members,
            # which resolves per-call via the routed search_path — it does not
            # exist in public at creation time (same setting the baseline dump
            # uses). SET LOCAL: scoped to the migration's transaction.
            "SET LOCAL check_function_bodies = false",
            GUILD_AUTH_SATISFIED_FN,
            INITIATIVE_ACCESS_FN,
        ]
    )


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(INITIATIVE_ACCESS_FN_PRIOR)
    op.execute("DROP FUNCTION IF EXISTS public.guild_auth_satisfied()")
    op.drop_table("guild_auth_policies")
