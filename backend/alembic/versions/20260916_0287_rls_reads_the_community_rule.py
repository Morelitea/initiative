"""The database layer reads a method rule too.

``public.guild_auth_satisfied()`` asked one question — has this session
satisfied the provider this guild names — and a requirement can now also ask
for the community's own single sign-on without naming which provider served it.
The function gains that leg, reading ``app.sso_guilds``, the GUC the request
sets beside ``app.satisfied_providers``.

It reads a GUC rather than joining the provider registry: the fact is settled
where it is known, at the moment a community's own provider completes a
sign-in, and the session carries it from there.

Replaced in place with ``CREATE OR REPLACE``: the signature is unchanged, so
every policy and every ``public.initiative_access`` call that already defers to
it picks the new body up without being rewritten.

Fail-closed exactly as the provider leg is. An unset or empty GUC is SQL NULL
once ``NULLIF`` has had it, ``&&`` against NULL is NULL, and ``COALESCE`` reads
that as "not satisfied" rather than letting a NULL admit the row.

Revision ID: 20260916_0287
Revises: 20260916_0286
Create Date: 2026-09-16
"""

from alembic import op

revision = "20260916_0287"
down_revision = "20260916_0286"
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
                  -- provider registry.
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
              AND p.provider_id IS NOT NULL
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


def upgrade() -> None:
    op.execute(GUILD_AUTH_SATISFIED_FN)


def downgrade() -> None:
    op.execute(PRIOR_FN)
