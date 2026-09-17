"""A community may ask that a session carried a second factor.

``guild_auth_policies.require_methods`` could hold one requirable value, and
the enum behind it now holds ``totp`` as well (0291). This is the leg that
makes asking for it mean something at the database, beside the provider leg and
the single-sign-on one it already had.

It reads ``app.session_mfa``, the GUC the request sets from its own session's
``amr`` — the marker written when a code was presented. Fail-closed like its
neighbours: unset reads as ``false`` and the row is withheld.

Executed from ``app.db.authorization``, which is the source for these five
functions and re-applies them on every boot; a copy here would go stale at the
next edit. ``CREATE OR REPLACE`` keeps the OID, so every policy that defers to
it picks this up unrewritten.

Revision ID: 20260917_0293
Revises: 20260917_0292
Create Date: 2026-09-17
"""

from alembic import op

from app.db.authorization import GUILD_AUTH_SATISFIED

revision = "20260917_0293"
down_revision = "20260917_0292"
branch_labels = None
depends_on = None


# The body as 0289 left it: a provider leg and a method leg that knew only
# single sign-on. Kept here and nowhere else — the module carries what the rule
# is, and only this revision knows what preceded it.
PRIOR_FN = """
CREATE OR REPLACE FUNCTION public.guild_auth_satisfied() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        NULLIF(current_setting('app.current_user_id', true), '') IS NULL
        OR current_setting('app.satisfied_providers', true) = 'system'
        OR NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = NULLIF(
                    current_setting('app.current_guild_id', true), ''
                  )::int
              AND p.policy <> 'open'
              AND (
                  (
                      p.provider_id IS NOT NULL
                      AND NOT COALESCE(
                            p.provider_id = ANY(
                                string_to_array(
                                    NULLIF(
                                        current_setting(
                                            'app.satisfied_providers', true
                                        ), ''
                                    ),
                                    ','
                                )::int[]
                            ),
                            false
                          )
                  )
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT COALESCE(
                            p.guild_id = ANY(
                                string_to_array(
                                    NULLIF(
                                        current_setting('app.sso_guilds', true), ''
                                    ),
                                    ','
                                )::int[]
                            ),
                            false
                          )
                  )
              )
        )
$$;
"""


def upgrade() -> None:
    op.execute(GUILD_AUTH_SATISFIED)


def downgrade() -> None:
    op.execute(PRIOR_FN)
