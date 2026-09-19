"""A community may ask that a session carried a second factor.

``guild_auth_policies.require_methods`` could hold one requirable value, and
the enum behind it now holds ``totp`` as well (0291). This is the leg that
makes asking for it mean something at the database, beside the provider leg and
the single-sign-on one it already had.

It reads ``app.session_mfa``, the GUC the request sets from its own session's
``amr`` — the marker written when a code was presented. Fail-closed like its
neighbours: unset reads as ``false`` and the row is withheld.

The body is stated here rather than read from ``app.db.authorization``. That
module is what every database converges on, being re-applied on every boot, but
a migration is a record of one revision: a body read from the live module
changes what a past revision does when that module is edited. ``CREATE OR
REPLACE`` keeps the OID, so every policy that defers to it picks this up
unrewritten.

Revision ID: 20260917_0293
Revises: 20260917_0292
Create Date: 2026-09-17
"""

from alembic import op

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


GUILD_AUTH_SATISFIED_AT_0293 = """\
CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
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
              AND (
                  -- The provider this guild names, if it names one.
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
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND COALESCE(
                            current_setting('app.session_mfa', true), 'false'
                          ) <> 'true'
                  )
                  -- Or its own single sign-on, whichever of its providers
                  -- served it. The session records each community whose sign-in
                  -- it completed, so this is answered without reading the
                  -- provider registry. Named rather than counted, so a list
                  -- holding some other method is not read as this one.
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
$function$
"""


def upgrade() -> None:
    # The module sets this before applying these functions and says why: the
    # bodies name things that are not resolvable at creation time. The enum
    # label this one compares against is added by 0291, and validating the body
    # here would evaluate it against the type as this transaction first saw it.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(GUILD_AUTH_SATISFIED_AT_0293)


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(PRIOR_FN)
