"""one set of markers instead of a flag per method

``guild_auth_satisfied`` asked two of its questions of a GUC of its own:
``app.session_mfa`` for the second factor, ``app.session_passkey`` for a key.
Each method a community can require meant another boolean carried from the
credential validator, through the request context, onto the connection, and
into a leg here. This replaces both with ``app.session_amr`` — the markers the
session recorded about how it was opened, narrowed to a closed vocabulary and
comma-joined — and a reader, ``public.session_amr()``, that parses it once.

The reader is where the parsing lives. ``string_to_array`` of an unset setting
is NULL, and the COALESCE to an empty array is what the legs are written
against, so an absent setting reads as a session that recorded nothing.

The rules are unchanged: ``totp`` is answered by ``mfa``, ``passkey`` by
``hwk`` or ``swk``. Shipped as a migration rather than left to the next boot so
a deployment converges before it serves: the request path writes the new
setting from the moment it starts, and the bodies this replaces read settings
nobody writes any more.

The bodies are stated here rather than read from ``app.db.authorization``. That
module is what every database converges on, being re-applied on every boot, but
a migration is a record of one revision: a body read from the live module
changes what a past revision does when that module is edited. ``CREATE OR
REPLACE`` keeps the OID, so every policy that defers to these picks them up
unrewritten.

Revision ID: 20260920_0326
Revises: 20260920_0325
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0326"
down_revision = "20260920_0325"
branch_labels = None
depends_on = None


# The reader this revision introduces.
SESSION_AMR = """\
CREATE OR REPLACE FUNCTION public.session_amr()
 RETURNS text[]
 LANGUAGE sql
 STABLE
AS $function$
    SELECT COALESCE(
        string_to_array(
            NULLIF(current_setting('app.session_amr', true), ''),
            ','
        ),
        ARRAY[]::text[]
    )
$function$

"""


# ``guild_auth_satisfied`` with both legs reading it.
GUILD_AUTH_SATISFIED_AT_0326 = """\
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
                      AND NOT ('mfa' = ANY(public.session_amr()))
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
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


# The body as 0318 left it: the two legs reading a setting each. Kept here and
# nowhere else — the module carries what the rule is, and only this revision
# knows what preceded it.
PRIOR_FN = """\
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
    # The module sets this before applying these functions and says why: the
    # bodies name guild-local tables that are not on the ``search_path`` when
    # the function is created. Names are resolved per call, against the
    # caller's route.
    op.execute("SET LOCAL check_function_bodies = false")
    # The reader first: the body below calls it.
    op.execute(SESSION_AMR)
    op.execute(GUILD_AUTH_SATISFIED_AT_0326)


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    # The caller first, so nothing refers to the reader when it goes.
    op.execute(PRIOR_FN)
    op.execute("DROP FUNCTION IF EXISTS public.session_amr()")
