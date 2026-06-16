"""Drop the legacy ``public.is_initiative_member`` function — one source of truth.

Initiative access is now defined in exactly ONE place: ``public.initiative_access``
(migration 0110), which backs the PERMISSIVE ``initiative_member_*`` policies on
every per-guild content table (generated into ``guild_rls.sql``) and the
app-layer ``membership.initiative_scope_clause``.

``is_initiative_member`` was its predecessor: ``SECURITY DEFINER SET search_path
= public``, read-only, with a roster-derived guild-admin leg. In the
schema-per-guild world it is pure legacy — it backs RESTRICTIVE policies only on
the ``public`` *copies* of the content tables (migrations 0057/0062/0066/0074/
0075/0085/0093/0108), which are inert on the request path (every request routes
into a ``guild_<id>`` schema whose tables carry only the ``initiative_access``
policies). No application code calls it, and being pinned to ``public`` it would
read the empty public ``initiative_members`` anyway. Two competing access rules
is exactly what we don't want, so this removes it.

Drops every policy that references the function (wherever it lives), then the
function itself. NO DOWNGRADE: reviving a dead, search_path-broken second access
rule has no value — roll forward only.

Revision ID: 20260616_0111
Revises: 20260616_0110
Create Date: 2026-06-16
"""

from alembic import op

revision = "20260616_0111"
down_revision = "20260616_0110"
branch_labels = None
depends_on = None


# Drop any policy whose USING / WITH CHECK expression mentions the function,
# across every schema/table — so the subsequent DROP FUNCTION can't fail on a
# lingering dependency.
_DROP_POLICIES = """
DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE coalesce(qual, '') LIKE '%is_initiative_member%'
           OR coalesce(with_check, '') LIKE '%is_initiative_member%'
    LOOP
        EXECUTE format(
            'DROP POLICY IF EXISTS %I ON %I.%I',
            r.policyname, r.schemaname, r.tablename
        );
    END LOOP;
END $$;
"""


def upgrade() -> None:
    op.execute(_DROP_POLICIES)
    op.execute("DROP FUNCTION IF EXISTS public.is_initiative_member(integer, integer)")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade past 20260616_0111 (drop is_initiative_member) is not supported; "
        "roll forward. initiative_access is the single source of truth."
    )
