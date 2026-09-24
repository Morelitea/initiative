"""the janitor keeps what it uses

Announcements and their pictures are written under the platform tier that
manages them (0365). What the system engine still does with them is the
orphan-picture janitor: it reads every announcement's sections, reads each
picture's age, and deletes the pictures no announcement names. Each verb it no
longer exercises goes, and the registry (``app.db.system_grants``) records the
result.

* ``announcements``: ``INSERT``, ``UPDATE`` and ``DELETE`` go from
  ``app_admin``, and with them ``USAGE`` on the id sequence. ``SELECT`` stays.
* ``announcement_images``: ``INSERT`` and ``UPDATE`` go from ``app_admin``.
  ``SELECT`` and ``DELETE`` stay.

No rows move, and no policy changes: the system engine is not bound by the
tables' policies.

Revision ID: 20260923_0367
Revises: 20260923_0366
Create Date: 2026-09-23
"""

from alembic import op

revision = "20260923_0367"
down_revision = "20260923_0366"
branch_labels = None
depends_on = None

SYSTEM = "app_admin"

#: (privileges, object), revoked from the system engine on the way up and
#: granted back on the way down.
TAKEN_BACK: tuple[tuple[str, str], ...] = (
    ("INSERT, UPDATE, DELETE", "TABLE public.announcements"),
    ("USAGE", "SEQUENCE public.announcements_id_seq"),
    ("INSERT, UPDATE", "TABLE public.announcement_images"),
)


def _on_role(role: str, statement: str) -> None:
    """Run ``statement`` when ``role`` exists on this cluster."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                EXECUTE '{statement}';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    for privileges, target in TAKEN_BACK:
        _on_role(SYSTEM, f"REVOKE {privileges} ON {target} FROM {SYSTEM}")


def downgrade() -> None:
    """Give the verbs back, as 0218 granted them."""
    for privileges, target in TAKEN_BACK:
        _on_role(SYSTEM, f"GRANT {privileges} ON {target} TO {SYSTEM}")
