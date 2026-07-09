"""One periodic worker that prunes every one-shot ``jti`` replay-guard table.

Both jti blocklists — the billing service JWT blocklist and the
initiative-auto delegation blocklist — are the same maintenance concern:
shared ``public`` tables of spent one-shot tokens that grow forever unless
swept. They run on one hourly cadence, so one worker sweeps them all rather
than a near-identical janitor per table (the per-table DELETE lives in
:func:`app.db.jti_blocklist.purge_expired_jtis`).

Each entry is gated by whether its integration is configured: on a self-host
with neither wired, the worker is a strict no-op (no session opened). The
sweep runs on the system engine (``app_admin`` holds DELETE on both tables);
the request path never deletes. Pruning is always safe — an expired token is
refused by its own ``exp`` at verification before its blocklist is consulted,
so removing the spent row never re-opens a replay window.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sqlmodel import SQLModel

from app.core.config import settings
from app.db.jti_blocklist import purge_expired_jtis
from app.models.platform.auto_delegation_jti import AutoDelegationJti
from app.models.platform.billing import BillingJti
from app.services.platform.billing import billing_inbound_enabled

logger = logging.getLogger(__name__)

# Same cadence as the token purge; each table is cheap to sweep.
JTI_PURGE_POLL_SECONDS = 3600


@dataclass(frozen=True)
class _Blocklist:
    model: type[SQLModel]
    enabled: Callable[[], bool]
    label: str


def _auto_delegation_enabled() -> bool:
    return bool(settings.AUTO_DELEGATION_PUBLIC_KEY_PEM)


# One entry per jti blocklist. Add a table here and it is swept automatically.
_BLOCKLISTS: tuple[_Blocklist, ...] = (
    _Blocklist(BillingJti, billing_inbound_enabled, "billing"),
    _Blocklist(AutoDelegationJti, _auto_delegation_enabled, "auto-delegation"),
)


async def process_jti_blocklist_purges() -> None:
    active = [b for b in _BLOCKLISTS if b.enabled()]
    if not active:
        return  # self-host default: nothing wired, nothing can have filled
    from app.db.session import AdminSessionLocal

    async with AdminSessionLocal() as session:
        for entry in active:
            # Independent per table: one failing sweep must not skip the rest.
            try:
                purged = await purge_expired_jtis(session, entry.model)
            except Exception:  # pragma: no cover - defensive, logged and retried
                logger.exception("jti-purge: %s sweep failed", entry.label)
                continue
            if purged:
                logger.info(
                    "jti-purge: removed %s expired %s rows", purged, entry.label
                )
