"""A community's connection admits nobody until it says who.

``guild_connection_admits`` treated a connection naming no claim as counting
everybody the provider vouches for. For a provider that is only this
deployment's people that reading is harmless; for one that vouches for the
world it is the whole world, and paired with ``auto_join`` it places them.

This feature is for a deployment whose communities are separate tenants. A
deployment where the provider *is* everybody does not turn it on, so the
reading it existed for has no case left — and the safe direction for an
arrangement that has not said who belongs is nobody.

The write path refuses an enabled connection without a narrowing; this is the
other half, so a row that gets there another way grants nothing either. A
**disabled** row may still name no claim: that is how a community declines the
deployment's default, and it admits nobody by being disabled.

Revision ID: 20260920_0337
Revises: 20260920_0336
Create Date: 2026-09-20
"""

from alembic import op

revision = "20260920_0337"
down_revision = "20260920_0336"
branch_labels = None
depends_on = None

_ADMITS = "CREATE OR REPLACE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL::integer)\n RETURNS boolean\n LANGUAGE sql\n STABLE\nAS $function$\n    WITH effective AS (\n        -- What this community said, and the deployment's own answer for a\n        -- provider it has said nothing about. One row shadows one row: a\n        -- community's own connection replaces the default outright, including\n        -- one it wrote with `enabled` off to decline it.\n        SELECT c.provider_id, c.enabled, c.claim, c.claim_values\n        FROM public.guild_provider_connections c\n        WHERE c.guild_id = p_guild_id\n        UNION ALL\n        SELECT d.provider_id, d.enabled, d.claim, d.claim_values\n        FROM public.platform_provider_defaults d\n        WHERE NOT EXISTS (\n            SELECT 1\n            FROM public.guild_provider_connections own\n            WHERE own.guild_id = p_guild_id\n              AND own.provider_id = d.provider_id\n        )\n    )\n    SELECT EXISTS (\n        SELECT 1\n        FROM effective c\n        WHERE c.enabled\n          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)\n          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))\n          -- A connection names a claim and the values that count, or it\n          -- admits nobody. An arrangement that says who belongs by saying\n          -- nothing is not one this reads as everybody.\n          AND c.claim IS NOT NULL\n          AND c.claim_values IS NOT NULL\n          AND (\n              EXISTS (\n                  SELECT 1\n                  FROM jsonb_array_elements_text(\n                      CASE\n                          WHEN jsonb_typeof(\n                                   COALESCE(p_claims, '{}'::jsonb)\n                                       -> c.provider_id::text -> c.claim\n                               ) = 'array'\n                          THEN COALESCE(p_claims, '{}'::jsonb)\n                                   -> c.provider_id::text -> c.claim\n                          ELSE '[]'::jsonb\n                      END\n                  ) AS asserted(value)\n                  WHERE lower(asserted.value) = ANY (\n                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted\n                  )\n              )\n          )\n    )\n$function$\n\n"

_ADMITS_PREVIOUS = "CREATE OR REPLACE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL::integer)\n RETURNS boolean\n LANGUAGE sql\n STABLE\nAS $function$\n    WITH effective AS (\n        -- What this community said, and the deployment's own answer for a\n        -- provider it has said nothing about. One row shadows one row: a\n        -- community's own connection replaces the default outright, including\n        -- one it wrote with `enabled` off to decline it.\n        SELECT c.provider_id, c.enabled, c.claim, c.claim_values\n        FROM public.guild_provider_connections c\n        WHERE c.guild_id = p_guild_id\n        UNION ALL\n        SELECT d.provider_id, d.enabled, d.claim, d.claim_values\n        FROM public.platform_provider_defaults d\n        WHERE NOT EXISTS (\n            SELECT 1\n            FROM public.guild_provider_connections own\n            WHERE own.guild_id = p_guild_id\n              AND own.provider_id = d.provider_id\n        )\n    )\n    SELECT EXISTS (\n        SELECT 1\n        FROM effective c\n        WHERE c.enabled\n          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)\n          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))\n          -- A connection naming no claim counts everybody the provider does.\n          AND (\n              c.claim IS NULL\n              OR c.claim_values IS NULL\n              OR EXISTS (\n                  SELECT 1\n                  FROM jsonb_array_elements_text(\n                      CASE\n                          WHEN jsonb_typeof(\n                                   COALESCE(p_claims, '{}'::jsonb)\n                                       -> c.provider_id::text -> c.claim\n                               ) = 'array'\n                          THEN COALESCE(p_claims, '{}'::jsonb)\n                                   -> c.provider_id::text -> c.claim\n                          ELSE '[]'::jsonb\n                      END\n                  ) AS asserted(value)\n                  WHERE lower(asserted.value) = ANY (\n                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted\n                  )\n              )\n          )\n    )\n$function$\n\n"


def upgrade() -> None:
    op.execute(_ADMITS)


def downgrade() -> None:
    op.execute(_ADMITS_PREVIOUS)
