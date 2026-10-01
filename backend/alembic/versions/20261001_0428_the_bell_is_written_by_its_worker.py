"""the bell is written by its worker

A request that causes a notice now writes it to ``notice_outbox``, and the
notice worker writes the bell line and queues the email on the system engine.
Direct messages, the suspension notice, the digests and the account letters
write on the system engine too. No request floor writes ``notifications`` or
``email_outbox`` any more, so:

- the four ``notifications_*_named_recipient`` policies go, with the
  ``app.notify_target_user_id`` setting they read;
- the routed and install floors lose what they held on ``notifications``, and
  the routed read floor its ``SELECT``;
- the routed, platform and install floors lose ``INSERT`` on ``email_outbox``;
- each of those floors loses the sequence it needed to insert.

The reader's own bell (``notifications_self_*``, on the platform floor) stays.

Revision ID: 20261001_0428
Revises: 20261001_0427
Create Date: 2026-10-01
"""

from __future__ import annotations

from alembic import op

from app.core.config import settings

revision = "20261001_0428"
down_revision = "20261001_0427"
branch_labels = None
depends_on = None

POLICIES = (
    "notifications_write_named_recipient",
    "notifications_insert_named_recipient",
    "notifications_update_named_recipient",
    "notifications_delete_named_recipient",
)


def _platform_base() -> str:
    """Read at apply time, not at import: the platform prefix is a setting, and
    the migrations test swaps it around the chain it runs."""
    return f"{settings.PLATFORM_ROLE_PREFIX}platform_base"


def upgrade() -> None:
    for name in POLICIES:
        op.execute(f"DROP POLICY IF EXISTS {name} ON public.notifications")

    for role in ("app_guild_base", "app_guild_base_ro", "app_install_base"):
        op.execute(f'REVOKE ALL ON TABLE public.notifications FROM "{role}"')
    for role in ("app_guild_base", "app_install_base"):
        op.execute(f'REVOKE ALL ON SEQUENCE public.notifications_id_seq FROM "{role}"')

    for role in ("app_guild_base", _platform_base(), "app_install_base"):
        op.execute(f'REVOKE ALL ON TABLE public.email_outbox FROM "{role}"')
        op.execute(f'REVOKE ALL ON SEQUENCE public.email_outbox_id_seq FROM "{role}"')


def downgrade() -> None:
    # The policies come back from the registry the older code renders at boot.
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notifications "
        "TO app_guild_base"
    )
    op.execute("GRANT SELECT ON TABLE public.notifications TO app_guild_base_ro")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON TABLE public.notifications TO app_install_base"
    )
    for role in ("app_guild_base", "app_install_base"):
        op.execute(
            f'GRANT USAGE, SELECT ON SEQUENCE public.notifications_id_seq TO "{role}"'
        )

    for role in ("app_guild_base", _platform_base(), "app_install_base"):
        op.execute(f'GRANT INSERT ON TABLE public.email_outbox TO "{role}"')
        op.execute(
            f'GRANT USAGE, SELECT ON SEQUENCE public.email_outbox_id_seq TO "{role}"'
        )
