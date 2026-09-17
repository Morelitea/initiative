"""A method requirement names the method it asks for.

``public.guild_auth_satisfied()`` reads ``guild_auth_policies.require_methods``
to decide whether a session has done what a community asks. It asked whether
that list held anything at all and, if so, looked for the community's own
single sign-on:

    cardinality(p.require_methods) > 0 AND NOT (p.guild_id = ANY(app.sso_guilds))

``require_methods`` is a ``login_method[]``, and the vocabulary it draws from
has one requirable value today, so "holds anything" and "holds ``sso``" are the
same question. They stop being the same question the moment the vocabulary
grows: the leg would answer for single sign-on whatever a community had
actually asked for. It now names ``sso`` directly, so each method the list may
hold is read as itself.

Behaviour is unchanged on every deployment — the two forms agree on every value
``require_methods`` can currently hold. The app-side mirror of this rule in
``app/api/deps.py`` moves with it.

Replaced in place with ``CREATE OR REPLACE``: the signature is unchanged, so
every policy and every ``public.initiative_access`` call that already defers to
it picks the new body up without being rewritten.

Revision ID: 20260916_0289
Revises: 20260916_0288
Create Date: 2026-09-16
"""

from alembic import op

revision = "20260916_0289"
down_revision = "20260916_0288"
branch_labels = None
depends_on = None


# NULLIF-guarded casts per the session-variable constants standard: an unset
# GUC is empty-string, and a bare cast would fault every policy on the table.
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
$$;
"""

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
                      cardinality(p.require_methods) > 0
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
    op.execute(GUILD_AUTH_SATISFIED_FN)


def downgrade() -> None:
    op.execute(PRIOR_FN)
