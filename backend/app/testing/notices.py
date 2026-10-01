"""Delivering the notices a test caused, as the worker would."""

from __future__ import annotations


async def drain_notices() -> None:
    """Deliver every notice written so far: bell lines, email, push.

    ``notify`` writes a notice down and the worker delivers it after the
    request commits, so a test that reads what a notice produced calls this
    first, once whatever caused it has committed.
    """
    from app.services.platform import notice_outbox

    await notice_outbox.process_notice_outbox()
