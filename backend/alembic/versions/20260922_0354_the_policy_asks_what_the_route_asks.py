"""take two request-path writes back to the system engine

``guild_memberships`` is joined on the system engine — an invite redeemed, a
community joined, a sign-in synced — and never on a routed request. The floors
kept the schema-default ``INSERT`` on it, behind a member-only policy that no
request-path writer reached. Both go: the verb from the two floors here, and
the two policies, which the registry (``app.db.public_rls``) no longer names.

``oidc_claim_mappings`` is read at sign-in and written by the seat's claim-rule
routes, both on the system engine. The floors held full DML behind a policy
that admitted any routed session of the mapping's community. The verbs go
here — from the read half as well as the two writable floors, so the two halves
still name the same tables — the policy with them, and the registry records the
table as ``FORCED_NO_POLICY`` — row security on, nothing admitted on the
request path.

``guild_invites`` keeps its verbs on both floors: an administrator writes an
invite on a routed request. Its policies now ask for the administrator, as the
route does; that is the registry's to render at boot, not this file's.

Revision ID: 20260922_0354
Revises: 20260922_0353
Create Date: 2026-09-22
"""

from alembic import op

from app.core.config import settings

revision = "20260922_0354"
down_revision = "20260922_0353"
branch_labels = None
depends_on = None

FLOORS = ("app_guild_base", f"{settings.PLATFORM_ROLE_PREFIX}platform_base")

#: The read half of ``app_guild_base``, which holds SELECT where the writable
#: floor holds it and nothing where it does not.
READ_FLOOR = "app_guild_base_ro"


def _on_role(role: str, statement: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE '{statement.format(floor=role)}';
            END IF;
        END
        $$;
        """
    )


def _for_each_floor(statement: str) -> None:
    for floor in FLOORS:
        _on_role(floor, statement)


def upgrade() -> None:
    _for_each_floor("REVOKE INSERT ON public.guild_memberships FROM {floor}")
    op.execute(
        "DROP POLICY IF EXISTS guild_memberships_insert ON public.guild_memberships"
    )
    op.execute(
        "DROP POLICY IF EXISTS guild_memberships_request_insert_member_only"
        " ON public.guild_memberships"
    )
    _for_each_floor("REVOKE ALL ON public.oidc_claim_mappings FROM {floor}")
    _on_role(READ_FLOOR, "REVOKE ALL ON public.oidc_claim_mappings FROM {floor}")
    op.execute("DROP POLICY IF EXISTS guild_isolation ON public.oidc_claim_mappings")


def downgrade() -> None:
    """Give the verbs back. The policies are the registry's: a boot on the
    revision this reverts to renders them again from what it names."""
    _for_each_floor("GRANT INSERT ON public.guild_memberships TO {floor}")
    _for_each_floor(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON public.oidc_claim_mappings TO {floor}"
    )
    # The read half takes back the read half.
    _on_role(READ_FLOOR, "GRANT SELECT ON public.oidc_claim_mappings TO {floor}")
