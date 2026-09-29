"""Every request is named, and says so on the way out."""

from httpx import AsyncClient
from prometheus_client import REGISTRY

from app.core import audit_context, metrics
from app.core.audit_events import AuditEventType
from app.core.config import settings
from app.core.request_audit import (
    REQUEST_ID_HEADER,
    RequestAuditMiddleware,
    record_privileged_edit,
)
from app.testing import emitted


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


# --- sockets ------------------------------------------------------------


async def _drive_socket(scope: dict, inside) -> None:
    """Run ``inside`` as the app a socket handshake reaches."""

    async def app(_scope, _receive, _send):
        inside()

    async def receive():
        return {"type": "websocket.connect"}

    async def send(_message):
        return None

    await RequestAuditMiddleware(app)(scope, receive, send)


def _ws_scope() -> dict:
    return {
        "type": "websocket",
        "path": "/ws",
        "client": ("203.0.113.7", 51234),
        "headers": [(b"user-agent", b"Firefox/1")],
    }


async def test_a_socket_is_named_for_as_long_as_it_is_open():
    """A socket has no response to carry an id back on, but every line it
    writes still says which session wrote it."""
    seen = {}

    def inside():
        context = audit_context.current()
        seen["request_id"] = context.request_id
        seen["source_ip"] = context.source_ip

    await _drive_socket(_ws_scope(), inside)

    assert audit_context.clean_request_id(seen["request_id"])
    assert seen["source_ip"] == "203.0.113.7"
    assert audit_context.current() is None


def _requests_counted(route: str, status: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "initiative_http_requests_total",
            {"method": "GET", "route": route, "status": status},
        )
        or 0.0
    )


async def test_a_request_is_counted_by_the_route_it_matched(client: AsyncClient):
    """The label is the route as written, so every community's list is one
    series rather than one per community."""
    route = "/api/v1/c/{guild_id}/initiatives/"
    before = _requests_counted(route, "401")

    answered = await client.get("/api/v1/c/424242/initiatives/")

    assert answered.status_code == 401
    assert _requests_counted(route, "401") == before + 1
    assert (
        REGISTRY.get_sample_value(
            "initiative_http_request_duration_seconds_count",
            {"method": "GET", "route": route},
        )
        or 0
    ) >= 1
    assert (
        REGISTRY.get_sample_value(
            "initiative_http_requests_in_progress", {"method": "GET"}
        )
        == 0
    )


async def test_an_open_socket_is_counted_until_it_closes():
    seen = {}

    def inside():
        seen["open"] = REGISTRY.get_sample_value("initiative_websocket_connections")

    before = REGISTRY.get_sample_value("initiative_websocket_connections")
    await _drive_socket(_ws_scope(), inside)

    assert seen["open"] == before + 1
    assert REGISTRY.get_sample_value("initiative_websocket_connections") == before


def test_an_unknown_method_is_labelled_other():
    assert metrics.method_label("GET") == "GET"
    assert metrics.method_label("BREW") == "other"
    assert metrics.method_label(None) == "other"


async def test_a_grantees_first_edit_is_written_down(capfd):
    """One line per session: that they edited it is the fact worth having."""
    recorded = {}

    def inside():
        audit_context.note_grant(
            actor_user_id=42, guild_id=7, grant_id=88, access_level="read_write"
        )
        capfd.readouterr()
        recorded["first"] = record_privileged_edit(
            guild_id=7, resource_type="document", resource_id=931, actor_user_id=42
        )
        recorded["lines"] = emitted(capfd, AuditEventType.PAM_CONTENT_EDITED)

    await _drive_socket(_ws_scope(), inside)

    assert recorded["first"] is True
    (line,) = recorded["lines"]
    assert line["actor_user_id"] == 42
    assert line["guild_id"] == 7
    assert line["target"] == {"type": "document", "id": 931}
    assert line["is_write"] is True
    assert line["context"]["grant_id"] == 88
    assert line["context"]["source_ip"] == "203.0.113.7"


async def test_a_members_own_editing_is_not_written_down(capfd):
    """This records privileged access. A member editing their community's own
    document is ordinary work."""
    recorded = {}

    def inside():
        capfd.readouterr()
        recorded["wrote"] = record_privileged_edit(
            guild_id=7, resource_type="document", resource_id=931, actor_user_id=42
        )
        recorded["lines"] = emitted(capfd)

    await _drive_socket(_ws_scope(), inside)

    assert recorded["wrote"] is False
    assert recorded["lines"] == []


async def test_an_edit_outside_any_session_records_nothing():
    assert (
        record_privileged_edit(
            guild_id=7, resource_type="document", resource_id=931, actor_user_id=42
        )
        is False
    )
