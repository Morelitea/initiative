"""a guest is asked the guest half of a sign-in rule

- ``guild_auth_policies`` gains a guest half: ``guest_policy`` (``open`` or
  ``required``, open by default), ``guest_provider_id`` and its slug, and
  ``guest_require_methods``, held to the same rules as the members' half.
- ``public.guild_auth_satisfied()`` asks a request routed as a guest the
  guest half, and everybody else the members' half. The deployment's second
  factor and the community's ask-everybody second factor apply to both.

The function is stated here as it was and as it becomes, so this revision
reads the same whatever the module says later.

Revision ID: 20261011_0500
Revises: 20261010_0499
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261011_0500"
down_revision = "20261010_0499"
branch_labels = None
depends_on = None

_TABLE = "guild_auth_policies"

#: (name, condition) for the guest half, as the members' half has them.
_CHECKS = (
    ("ck_guild_auth_policies_guest_policy", "guest_policy IN ('open', 'required')"),
    (
        "ck_guild_auth_policies_guest_required_names_something",
        "guest_policy = 'open'"
        " OR (guest_provider_id IS NOT NULL AND guest_provider_slug IS NOT NULL)"
        " OR cardinality(guest_require_methods) > 0",
    ),
    (
        "ck_guild_auth_policies_guest_require_methods_no_password",
        "NOT ('password'::login_method = ANY (guest_require_methods))",
    ),
    (
        "ck_guild_auth_policies_guest_require_methods_no_email_otp",
        "NOT ('email_otp'::login_method = ANY (guest_require_methods))",
    ),
)

GUILD_AUTH_SATISFIED = """CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL
        OR current_setting('app.satisfied_providers'::text, true) = 'system'::text
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1
            FROM public.guild_auth_policies r
            -- The half that applies: a request routed into one of the
            -- community's guest roles, each granted the guest floor, is asked
            -- what the community asks of its guests.
            CROSS JOIN LATERAL (
                SELECT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    WHERE m.member = to_regrole(current_user)
                      AND m.roleid = to_regrole('guest_base')
                ) AS guest
            ) routed
            CROSS JOIN LATERAL (
                SELECT
                    r.guild_id,
                    CASE WHEN routed.guest THEN r.guest_policy ELSE r.policy END
                        AS policy,
                    CASE WHEN routed.guest THEN r.guest_provider_id ELSE r.provider_id END
                        AS provider_id,
                    CASE WHEN routed.guest THEN r.guest_require_methods
                        ELSE r.require_methods END
                        AS require_methods
            ) p
            WHERE r.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
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
                  -- Both factor legs apply while the community holds
                  -- ``providers``; the arrival legs apply whatever it holds.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                      AND public.guild_holds_option(p.guild_id, 'providers')
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
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(g.id, 'restrictions')
        ))
$function$

"""

PREVIOUS_GUILD_AUTH_SATISFIED = """CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
 RETURNS boolean
 LANGUAGE sql
 STABLE
AS $function$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL
        OR current_setting('app.satisfied_providers'::text, true) = 'system'::text
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
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
                  -- Both factor legs apply while the community holds
                  -- ``providers``; the arrival legs apply whatever it holds.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                      AND public.guild_holds_option(p.guild_id, 'providers')
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
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(g.id, 'restrictions')
        ))
$function$

"""


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("guest_policy", sa.String(16), nullable=False, server_default="open"),
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "guest_provider_id",
            sa.Integer(),
            sa.ForeignKey("auth_providers.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(_TABLE, sa.Column("guest_provider_slug", sa.Text(), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column(
            "guest_require_methods",
            postgresql.ARRAY(postgresql.ENUM(name="login_method", create_type=False)),
            nullable=False,
            server_default="{}",
        ),
    )
    for name, condition in _CHECKS:
        op.create_check_constraint(name, _TABLE, condition)
    op.get_bind().exec_driver_sql(GUILD_AUTH_SATISFIED)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(PREVIOUS_GUILD_AUTH_SATISFIED)
    for name, _condition in _CHECKS:
        op.drop_constraint(name, _TABLE)
    for column in (
        "guest_require_methods",
        "guest_provider_slug",
        "guest_provider_id",
        "guest_policy",
    ):
        op.drop_column(_TABLE, column)
