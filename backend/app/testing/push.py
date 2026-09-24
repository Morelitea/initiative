"""A deployment with push switched on, for a test about what a push carries."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import AsyncMock, patch

from app.services.platform import push_config


@contextmanager
def push_switched_on() -> Iterator[None]:
    """Resolve the push configuration as enabled for the duration.

    The switch lives on the settings row, behind a process-wide snapshot, so
    this patches the resolved answer rather than seeding the row and the cache.
    """
    enabled = push_config.ResolvedPushConfig(
        enabled=True,
        project_id="test-project",
        application_id=None,
        api_key=None,
        sender_id=None,
        service_account_json=None,
    )
    with patch.object(
        push_config, "ensure_push_config_fresh", AsyncMock(return_value=enabled)
    ):
        yield
