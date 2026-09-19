"""a community may ask for a passkey

``guild_auth_policies.require_methods`` gained a third requirable value with
the enum label 0314 added. This is the leg that makes asking for it mean
something at the database, beside the provider leg, the second-factor one and
the single-sign-on one it already had.

It reads ``app.session_passkey``, the GUC the request sets from its own
session's ``amr`` — the markers a WebAuthn assertion writes. Its own leg rather
than the second factor's: every assertion here verifies the person as well as
the device and so records ``mfa`` too, and a community naming a passkey is
naming the key. Fail-closed like its neighbours: unset reads as ``false`` and
the row is withheld.

The body is stated here rather than read from ``app.db.authorization``. That
module is what every database converges on, being re-applied on every boot, but
a migration is a record of one revision: a body read from the live module
changes what a past revision does when that module is edited. ``CREATE OR
REPLACE`` keeps the OID, so every policy that defers to it picks this up
unrewritten.

Revision ID: 20260918_0316
Revises: 20260918_0315
Create Date: 2026-09-18
"""

from alembic import op

revision = "20260918_0316"
down_revision = "20260918_0315"
branch_labels = None
depends_on = None


# The body as 0303 left it: a provider leg, a second-factor leg and a
# single-sign-on one. Kept here and nowhere else — the module carries what the
# rule is, and only this revision knows what preceded it.
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


# And with the passkey leg, as this revision leaves it.
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


def upgrade() -> None:
    # The module sets this before applying these functions and says why: the
    # bodies name things that are not resolvable at creation time. The enum
    # label this one compares against is added by 0314, and validating the body
    # here would evaluate it against the type as this transaction first saw it.
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(GUILD_AUTH_SATISFIED_AT_0316)


def downgrade() -> None:
    op.execute("SET LOCAL check_function_bodies = false")
    op.execute(PRIOR_FN)
