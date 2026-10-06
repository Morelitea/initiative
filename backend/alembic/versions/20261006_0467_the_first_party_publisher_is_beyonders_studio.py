"""The first-party publisher is ``beyonders-studio``; ``morelitea`` stops being it.

The organization was renamed, and with it the prefix of every plug-in this
project ships: ``morelitea.github`` is ``beyonders-studio.github`` now, and the
registry delegates to ``beyonders-studio`` and no longer to ``morelitea``. Boot
seeds the new publisher, verified, under its own id
(``seed_publishers``). What is left is the old seeded row, still verified, for
a prefix the organization gave up and anyone can now claim on GitHub.

- Unreferenced — no registration, no listing points at it — it is deleted.
  That is the normal case: registrations and listings find their publisher by
  prefix, so the renamed plug-ins already sit under the new row.
- Still referenced — a registration or listing left over under a
  ``morelitea.*`` id — it is kept but demoted: unverified, ``source`` operator
  (so a registry refresh leaves it alone), and the listings under it lose the
  verified badge they carried. A stale entry must not borrow first-party trust.

``publishers`` and ``plugin_service_registrations`` force row security, so the
statements here lift ``FORCE`` on each table they touch for their length and
restore it in the same transaction, as the migration that created them did.

``downgrade()`` makes the ``morelitea`` row the verified seed again, recreating
it when it was deleted, which is what the previous version's boot expects. The
``beyonders-studio`` row is left: the previous version does not read it.

Revision ID: 20261006_0467
Revises: 20261006_0466
Create Date: 2026-10-06
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import sqlalchemy as sa
from alembic import op

revision = "20261006_0467"
down_revision = "20261006_0466"
branch_labels = None
depends_on = None

PUBLISHERS = "publishers"
REGISTRATIONS = "plugin_service_registrations"
LISTINGS = "marketplace_listings"

#: The prefix the organization gave up, and the name it was seeded under.
OLD_PREFIX = "morelitea"
OLD_NAME = "Morelitea"


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


@contextmanager
def _unforced(*tables: str) -> Iterator[None]:
    """Lift FORCE ROW LEVEL SECURITY on each table that has it, and put it back."""
    forced: list[str] = []
    if _is_postgres():
        for table in tables:
            is_forced = (
                op.get_bind()
                .execute(
                    sa.text(
                        "SELECT c.relforcerowsecurity FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relname = :table"
                    ).bindparams(table=table)
                )
                .scalar()
            )
            if is_forced:
                op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
                forced.append(table)
    try:
        yield
    finally:
        for table in forced:
            op.execute(f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    bind = op.get_bind()
    with _unforced(PUBLISHERS, REGISTRATIONS, LISTINGS):
        old_id = bind.execute(
            sa.text(
                f"SELECT id FROM public.{PUBLISHERS} WHERE prefix = :prefix"
            ).bindparams(prefix=OLD_PREFIX)
        ).scalar()
        if old_id is None:
            return
        referenced = bind.execute(
            sa.text(
                f"SELECT EXISTS (SELECT 1 FROM public.{REGISTRATIONS} WHERE publisher_id = :id) "
                f"OR EXISTS (SELECT 1 FROM public.{LISTINGS} WHERE publisher_id = :id)"
            ).bindparams(id=old_id)
        ).scalar()
        if not referenced:
            op.execute(
                sa.text(f"DELETE FROM public.{PUBLISHERS} WHERE id = :id").bindparams(
                    id=old_id
                )
            )
            return
        op.execute(
            sa.text(
                f"UPDATE public.{PUBLISHERS} "
                "SET verified = false, source = 'operator', display_name = :prefix "
                "WHERE id = :id"
            ).bindparams(id=old_id, prefix=OLD_PREFIX)
        )
        op.execute(
            sa.text(
                f"UPDATE public.{LISTINGS} SET publisher_verified = false WHERE publisher_id = :id"
            ).bindparams(id=old_id)
        )


def downgrade() -> None:
    bind = op.get_bind()
    with _unforced(PUBLISHERS):
        exists = bind.execute(
            sa.text(
                f"SELECT 1 FROM public.{PUBLISHERS} WHERE prefix = :prefix"
            ).bindparams(prefix=OLD_PREFIX)
        ).scalar()
        if exists:
            op.execute(
                sa.text(
                    f"UPDATE public.{PUBLISHERS} "
                    "SET verified = true, source = 'seed', display_name = :name "
                    "WHERE prefix = :prefix"
                ).bindparams(prefix=OLD_PREFIX, name=OLD_NAME)
            )
        else:
            op.execute(
                sa.text(
                    f"INSERT INTO public.{PUBLISHERS} "
                    "(prefix, display_name, verified, enabled, source, created_at) "
                    "VALUES (:prefix, :name, true, true, 'seed', now())"
                ).bindparams(prefix=OLD_PREFIX, name=OLD_NAME)
            )
