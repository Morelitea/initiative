"""The request path resolves the client sector, and only that one.

``identity_refs`` has been system-engine-only since it was created: every
sector in it named a party outside the deployment, and the request path had no
business reading the mapping. The ``client`` sector is not like that — its
holder is the browser or native app presenting a signed token, and resolving
its ``sub`` is the first thing every authenticated request does.

So the bare login role gets ``SELECT``, and one policy decides which rows it
reaches. ``billing``, ``app`` and ``webhook`` stay where they were.
"""

from alembic import op

revision = "20260913_0267"
down_revision = "20260913_0266"
branch_labels = None
depends_on = None

POLICY = "identity_refs_client_sector"


def upgrade() -> None:
    op.execute("GRANT SELECT ON TABLE public.identity_refs TO app_user")
    op.execute(
        f"""
        CREATE POLICY {POLICY} ON public.identity_refs
            FOR SELECT TO app_user
            USING (purpose = 'client' AND entity_type = 'user')
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON public.identity_refs")
    op.execute("REVOKE SELECT ON TABLE public.identity_refs FROM app_user")
