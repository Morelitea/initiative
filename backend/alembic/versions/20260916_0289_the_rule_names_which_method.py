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

**Stated here, not imported.** ``app/db/authorization.py`` is what these five
functions converge on — it is re-applied on every boot — but a migration is a
record of one revision, and a body read from the live module changes what this
revision does every time that module is edited. It did: a later revision added
a label to the enum this body compares against, and an upgrade from empty
reached here first and named a value that did not exist yet. The body below is
what this revision installs; the module is what every database ends up with.
The method leg it carries was introduced by ``0286``/``0287``, written on a
branch running beside the one that gave these functions a home, so each was
correct about the half it could see.

``CREATE OR REPLACE`` keeps the function's OID, so every policy and every
``public.initiative_access`` call that already defers to it picks the new body
up without being rewritten.

Revision ID: 20260916_0289
Revises: 20260916_0288
Create Date: 2026-09-16
"""

from alembic import op

revision = "20260916_0289"
down_revision = "20260916_0288"
branch_labels = None
depends_on = None


# The body as ``0287`` left it, for the downgrade. A copy is right here and
# nowhere else: the module carries what the rule *is*, and only this revision
# knows what preceded it.
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


GUILD_AUTH_SATISFIED_AT_0289 = """
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
    op.execute(GUILD_AUTH_SATISFIED_AT_0289)


def downgrade() -> None:
    op.execute(PRIOR_FN)
