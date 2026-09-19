"""a deployment may ask for a second factor

One column on the singleton and one more condition in the gate every guild
content policy already defers to.

``app_settings.second_factor_requirement`` says who is asked: nobody, the
platform rungs above ``member``, or everybody. A real Postgres enum for the
reason ``login_methods`` is one — the database validates the value, and a rung
added later is a value on the type rather than a column here. ``nobody`` on
every fresh and upgraded install, so an upgrade asks nothing of anybody it was
not already asking. ``ADD COLUMN`` with a server default is metadata-only in
Postgres, so there is no row rewrite and no policy-bound DML to route around
``FORCE ROW LEVEL SECURITY``; ``app_settings`` is granted table-wide to the
owner tier, so the column arrives writable.

``public.platform_factor_satisfied()`` is the new function. It reads the level
from the settings row — readable under every routed role, the SELECT-only
guild floor included — and two GUCs the request writes with the rest of its
context: ``app.platform_role``, because ``public.users`` is not on a guild
request's path, and ``app.platform_factor``, which says whether the account
answers. Unset reads as fail-closed in both: no rung recorded is not
``member``, and no standing recorded is not answered.

``guild_auth_satisfied()`` gains it as a conjunct, inside the short-circuits
for pure system routing and the sentinel a user-attributed job sets. Both
functions are ``CREATE OR REPLACE``, which keeps each OID, so every policy that
defers to them picks this up unrewritten and no guild schema is re-rendered.

The bodies are stated here rather than read from ``app.db.authorization``.
That module is what every database converges on, being re-applied on every
boot, but a migration is a record of one revision: a body read from the live
module changes what a past revision does when that module is edited.

Revision ID: 20260918_0318
Revises: 20260918_0317
Create Date: 2026-09-18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260918_0318"
down_revision = "20260918_0317"
branch_labels = None
depends_on = None


# The gate as 0316 left it: a provider leg, a second-factor leg, a passkey leg
# and a single-sign-on one, and nothing above them.
GUILD_AUTH_SATISFIED_AT_0316 = """\
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
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
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
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND COALESCE(
                            current_setting('app.session_passkey', true), 'false'
                          ) <> 'true'
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
$function$

"""


PLATFORM_FACTOR_SATISFIED_AT_0318 = """\
CREATE OR REPLACE FUNCTION public.platform_factor_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.app_settings s
        WHERE s.id = 1
          AND s.second_factor_requirement <> 'nobody'
          AND (
              s.second_factor_requirement = 'everyone'
              OR COALESCE(current_setting('app.platform_role', true), '') <> 'member'
          )
          AND COALESCE(
                current_setting('app.platform_factor', true), 'false'
              ) <> 'true'
    )
$function$

"""


# And the gate with the deployment's own question ahead of the community's.
GUILD_AUTH_SATISFIED_AT_0318 = """\
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
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = NULLIF(
                    current_setting('app.current_guild_id', true), ''
                  )::int
              AND p.policy <> 'open'
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
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
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND COALESCE(
                            current_setting('app.session_passkey', true), 'false'
                          ) <> 'true'
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        ))
$function$

"""


def upgrade() -> None:
    requirement = postgresql.ENUM(
        "nobody",
        "platform_roles",
        "everyone",
        name="second_factor_requirement",
    )
    requirement.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "app_settings",
        sa.Column(
            "second_factor_requirement",
            requirement,
            nullable=False,
            server_default="nobody",
        ),
    )

    # The bodies name guild-local tables that are not on the ``search_path``
    # when the function is created; names are resolved per call, against the
    # caller's route. The module that applies these on every boot says the
    # same.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(PLATFORM_FACTOR_SATISFIED_AT_0318)
    op.execute(GUILD_AUTH_SATISFIED_AT_0318)


def downgrade() -> None:
    # The gate stops asking before the function it asks goes, so no policy
    # ever names something that is not there.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(GUILD_AUTH_SATISFIED_AT_0316)
    op.execute("DROP FUNCTION IF EXISTS public.platform_factor_satisfied()")

    op.drop_column("app_settings", "second_factor_requirement")
    op.execute("DROP TYPE IF EXISTS second_factor_requirement")
