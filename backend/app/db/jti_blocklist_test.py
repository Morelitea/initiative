"""The shared jti purge must leave a shared session usable after a failure.

Because one janitor sweeps several blocklists on ONE session, a statement
error on one table must not leave an aborted transaction that poisons the
next sweep — ``purge_expired_jtis`` rolls back before re-raising.
"""

from __future__ import annotations

import pytest

from app.db.jti_blocklist import purge_expired_jtis
from app.models.platform.billing import BillingJti

pytestmark = pytest.mark.unit


class _FakeSession:
    """Minimal async-session stand-in: exec fails, rollback is observable."""

    def __init__(self) -> None:
        self.rolled_back = False
        self.committed = False

    async def exec(self, _stmt):
        raise RuntimeError("statement failed")

    async def commit(self):  # pragma: no cover - never reached after exec fails
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


async def test_purge_rolls_back_and_reraises_on_statement_error():
    session = _FakeSession()
    with pytest.raises(RuntimeError, match="statement failed"):
        await purge_expired_jtis(session, BillingJti)
    # The whole point: the aborted transaction is cleared, not left to poison
    # the next blocklist swept on this same session.
    assert session.rolled_back is True
    assert session.committed is False
