"""Tests for the advanced-tool purge notification pipeline.

The contract under test: a HARD purge of an advanced tool queues a
(guild_id, advanced_tool_id) pair on the session, the drain hands it
over exactly once, and the outbound envelope is signed the way the
receiving service verifies it (``sha256=<hex>`` over
``{timestamp}.{body}`` with the shared secret). Soft deletes must queue
nothing — the mirror discovers those by syncing against our API.
"""

import hashlib
import hmac

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.tenant.advanced_tool import AdvancedTool
from app.services.tenant.advanced_tool_notify import (
    _sign,
    drain_purged_advanced_tools,
    notify_purged_advanced_tools,
    queue_purged_advanced_tool,
)
from app.services.tenant.soft_delete import (
    hard_purge_entity,
    soft_delete_entity,
)
from app.testing import create_guild, create_user, route_session_to_guild


async def _make_tool(session: AsyncSession) -> AdvancedTool:
    user = await create_user(session)
    guild = await create_guild(session, creator=user)
    await route_session_to_guild(session, guild.id)
    tool = AdvancedTool(guild_id=guild.id, name="Nightly export", created_by_id=user.id)
    session.add(tool)
    await session.commit()
    await session.refresh(tool)
    return tool


@pytest.mark.unit
def test_signature_matches_the_receivers_scheme():
    secret, timestamp, body = "s3cret", "1720000000", b'{"guild_id":1}'
    mac = hmac.new(secret.encode(), digestmod=hashlib.sha256)
    mac.update(b"1720000000.")
    mac.update(body)
    assert _sign(secret, timestamp, body) == f"sha256={mac.hexdigest()}"


@pytest.mark.service
async def test_hard_purge_queues_the_pair(session: AsyncSession):
    tool = await _make_tool(session)
    guild_id, tool_id = tool.guild_id, tool.id

    await hard_purge_entity(session, tool)
    await session.commit()

    assert drain_purged_advanced_tools(session) == [(guild_id, tool_id)]
    # Drained exactly once.
    assert drain_purged_advanced_tools(session) == []


@pytest.mark.service
async def test_soft_delete_queues_nothing(session: AsyncSession):
    tool = await _make_tool(session)

    await soft_delete_entity(
        session, tool, deleted_by_user_id=tool.created_by_id, retention_days=30
    )
    await session.commit()

    assert drain_purged_advanced_tools(session) == []


@pytest.mark.service
async def test_notify_is_a_noop_without_config(monkeypatch):
    """Unconfigured deployments (default OSS image) must not attempt any
    HTTP call — notify returns before touching the network."""
    from app.services.tenant import advanced_tool_notify as module

    monkeypatch.setattr(module.settings, "ADVANCED_TOOL_BACKEND_URL", None)
    monkeypatch.setattr(module.settings, "ADVANCED_TOOL_PURGE_SECRET", None)

    class Boom:
        def __call__(self, *a, **k):
            raise AssertionError("no HTTP client should be constructed")

    monkeypatch.setattr(module.httpx, "AsyncClient", Boom())
    await notify_purged_advanced_tools([(1, 2)])


@pytest.mark.unit
def test_queue_and_drain_accumulate_in_order():
    class FakeSession:
        info: dict = {}

    fake = FakeSession()
    queue_purged_advanced_tool(fake, guild_id=1, advanced_tool_id=10)
    queue_purged_advanced_tool(fake, guild_id=1, advanced_tool_id=11)
    assert drain_purged_advanced_tools(fake) == [(1, 10), (1, 11)]
