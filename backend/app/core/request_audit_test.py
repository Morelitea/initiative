"""Every request is named, and says so on the way out."""

import pytest
from httpx import AsyncClient

from app.core import audit_context
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.request_audit import REQUEST_ID_HEADER
from app.testing import emitted

pytestmark = pytest.mark.integration

VERSION = "/api/v1/version"
SIGN_IN = "/api/v1/auth/token"


async def test_a_response_carries_the_id_of_the_request(client: AsyncClient):
    answered = await client.get(VERSION)
    assert answered.status_code == 200
    assert audit_context.clean_request_id(answered.headers[REQUEST_ID_HEADER])


async def test_each_request_is_named_once(client: AsyncClient):
    first = await client.get(VERSION)
    second = await client.get(VERSION)
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


async def test_a_supplied_id_is_ignored_where_nothing_sits_in_front(
    client: AsyncClient, monkeypatch
):
    """Reached directly, nothing upstream has named this request, so what
    arrives claiming to be its name is not."""
    monkeypatch.setattr(settings, "BEHIND_PROXY", False)
    answered = await client.get(VERSION, headers={REQUEST_ID_HEADER: "from-outside"})
    assert answered.headers[REQUEST_ID_HEADER] != "from-outside"


async def test_a_proxys_id_is_kept_so_both_logs_say_the_same_name(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "BEHIND_PROXY", True)
    answered = await client.get(VERSION, headers={REQUEST_ID_HEADER: "edge-abc-123"})
    assert answered.headers[REQUEST_ID_HEADER] == "edge-abc-123"


async def test_an_unusable_id_is_replaced_rather_than_passed_on(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "BEHIND_PROXY", True)
    answered = await client.get(VERSION, headers={REQUEST_ID_HEADER: "two words"})
    assert answered.headers[REQUEST_ID_HEADER] != "two words"
    assert audit_context.clean_request_id(answered.headers[REQUEST_ID_HEADER])


async def test_a_line_written_during_a_request_says_which_request(
    client: AsyncClient, capfd
):
    """The thread between this stream and the deployment's own logs: the id on
    the response is the id in the record."""
    capfd.readouterr()
    answered = await client.post(
        SIGN_IN, data={"username": "nobody@example.com", "password": "wrong-password"}
    )
    assert answered.status_code == 400

    (line,) = emitted(capfd, AuditEventType.AUTH_SIGN_IN_FAILED)
    assert line["context"]["request_id"] == answered.headers[REQUEST_ID_HEADER]
    assert line["context"]["source_ip"]
    assert "grant_id" not in line["context"]


async def test_a_line_written_by_nobody_carries_no_request(session, capfd):
    """A sweep runs outside any request and says so, rather than borrowing the
    name of one."""
    from app.services import audit as audit_service
    from app.testing import create_user

    actor = await create_user(session)
    capfd.readouterr()
    await audit_service.record(
        session,
        event_type=AuditEventType.USER_AVATAR_REMOVED,
        actor_user_id=actor.id,
    )
    await session.commit()

    (line,) = emitted(capfd, AuditEventType.USER_AVATAR_REMOVED)
    assert line["context"] is None
