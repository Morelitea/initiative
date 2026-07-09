"""grant app_admin DELETE on auto_delegation_jti_blocklist (janitor)

The ``auto_delegation_jti_blocklist`` replay guard grew without bound: rows
were only ever inserted (one per redeemed delegation JWT), never pruned. The
shared jti janitor (``app.services.platform.jti_purge``) now sweeps expired
rows from every jti blocklist, which needs DELETE for the system
engine — the same access the billing jti blocklist already granted in
``20260708_0134``.

Only ``app_admin`` (the janitor's engine) gets DELETE; the request-path
login role keeps SELECT/INSERT only. Pruning is safe: an expired delegation
JWT is refused by its own ``exp`` at verification before the blocklist is
read, so removing its spent row never re-opens a replay window. The registry
decision lives in ``app/db/system_grants.py``
(``SHARED_TABLE_SYSTEM_GRANTS``); this migration is the immutable record of
*when* the access changed (``security_invariants_test`` fails if the two
drift).
"""

from alembic import op

revision = "20260709_0135"
down_revision = "20260708_0134"
branch_labels = None
depends_on = None

_TABLE = "public.auto_delegation_jti_blocklist"


def upgrade() -> None:
    op.execute(f"GRANT DELETE ON TABLE {_TABLE} TO app_admin")


def downgrade() -> None:
    op.execute(f"REVOKE DELETE ON TABLE {_TABLE} FROM app_admin")
