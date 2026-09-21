"""A community may ask for a second factor without asking for a provider.

The community-level requirement lived in ``guild_auth_policies.require_methods``
as ``totp``, which tied it to a sign-in rule: a community that lets its members
arrive however they like holds no policy row at all — choosing "open" deletes
it — so it had no way to ask. The answer moves to ``guilds``, beside
``allow_api_keys`` and ``enforce_compliance_session``, which are there for the
same reason and say so.

Existing rules are carried over and the ``totp`` element removed, so one place
holds the answer. ``guild_auth_satisfied`` gains a leg reading the new column,
outside the policy-row check for the same reason the column is not on it.

Both writes lift FORCE and restore it: these tables force RLS on their owner,
which is the role a migration runs as, so the statements would match no rows.

Revision ID: 20260921_0340
Revises: 20260921_0339
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa

revision = "20260921_0340"
down_revision = "20260921_0339"
branch_labels = None
depends_on = None


GUILD_AUTH_SATISFIED = """CREATE OR REPLACE FUNCTION public.guild_auth_satisfied()
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
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this. Unsatisfied is what this finds,
            -- like the leg above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = NULLIF(
                    current_setting('app.current_guild_id', true), ''
                  )::int
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
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


def upgrade() -> None:
    op.add_column(
        "guilds",
        sa.Column(
            "require_second_factor",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    bind = op.get_bind()
    op.execute("ALTER TABLE guilds NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guild_auth_policies NO FORCE ROW LEVEL SECURITY")
    try:
        carried = bind.execute(
            sa.text(
                "UPDATE guilds SET require_second_factor = true "
                "WHERE id IN (SELECT guild_id FROM guild_auth_policies "
                "             WHERE 'totp' = ANY(require_methods))"
            )
        ).rowcount
        bind.execute(
            sa.text(
                "UPDATE guild_auth_policies "
                "SET require_methods = array_remove(require_methods, 'totp') "
                "WHERE 'totp' = ANY(require_methods)"
            )
        )
        print(f"require_second_factor: {carried} community rule(s) carried over")
    finally:
        op.execute("ALTER TABLE guild_auth_policies FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE guilds FORCE ROW LEVEL SECURITY")
    op.execute(GUILD_AUTH_SATISFIED)


def downgrade() -> None:
    op.execute(PREVIOUS_GUILD_AUTH_SATISFIED)
    bind = op.get_bind()
    op.execute("ALTER TABLE guilds NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guild_auth_policies NO FORCE ROW LEVEL SECURITY")
    try:
        bind.execute(
            sa.text(
                "UPDATE guild_auth_policies p "
                "SET require_methods = require_methods || ARRAY['totp']::login_method[] "
                "FROM guilds g "
                "WHERE g.id = p.guild_id AND g.require_second_factor "
                "  AND NOT ('totp' = ANY(p.require_methods))"
            )
        )
    finally:
        op.execute("ALTER TABLE guild_auth_policies FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE guilds FORCE ROW LEVEL SECURITY")
    op.drop_column("guilds", "require_second_factor")
