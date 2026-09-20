"""What a line says about the request it came from."""

import pytest

from app.core import audit_context

pytestmark = pytest.mark.unit


def test_outside_a_request_there_is_no_context():
    """A background sweep writes a line with nothing to say about a request,
    rather than an invented one."""
    assert audit_context.envelope_context() is None


def test_a_request_carries_its_id_and_where_it_came_from():
    context, token = audit_context.begin(
        request_id="abc123", source_ip="203.0.113.7", user_agent="Firefox/1"
    )
    try:
        assert audit_context.current() is context
        assert audit_context.envelope_context() == {
            "request_id": "abc123",
            "source_ip": "203.0.113.7",
            "user_agent": "Firefox/1",
        }
    finally:
        audit_context.end(token)
    assert audit_context.current() is None


def test_a_long_user_agent_is_cut_to_a_length():
    context, token = audit_context.begin(request_id="x", user_agent="u" * 5000)
    try:
        assert context.user_agent is not None
        assert len(context.user_agent) == audit_context.MAX_USER_AGENT
    finally:
        audit_context.end(token)


def test_an_ordinary_request_says_nothing_about_a_grant():
    """The grant half appears only where there is a grant, so a filter on it
    selects the privileged requests and nothing else."""
    _, token = audit_context.begin(request_id="x")
    try:
        assert "grant_id" not in audit_context.envelope_context()
        assert audit_context.current().is_privileged is False
    finally:
        audit_context.end(token)


def test_a_granted_request_names_the_grant_that_serves_it():
    _, token = audit_context.begin(request_id="x")
    try:
        audit_context.note_grant(
            actor_user_id=42,
            guild_id=7,
            grant_id=88,
            access_level="read_write",
            settings_grant_id=89,
            settings_level="superadmin",
            break_glass=True,
        )
        context = audit_context.current()
        assert context.is_privileged
        assert context.actor_user_id == 42
        assert context.guild_id == 7
        assert audit_context.envelope_context() == {
            "request_id": "x",
            "source_ip": None,
            "user_agent": None,
            "grant_id": 88,
            "access_level": "read_write",
            "settings_grant_id": 89,
            "settings_level": "superadmin",
            "break_glass": True,
        }
    finally:
        audit_context.end(token)


def test_the_grant_that_admitted_the_request_is_the_one_kept():
    """A request may route into a second community part-way through. What let
    it in is what it was admitted on, not what it touched afterwards."""
    _, token = audit_context.begin(request_id="x")
    try:
        audit_context.note_grant(actor_user_id=1, guild_id=7, grant_id=88)
        audit_context.note_grant(actor_user_id=1, guild_id=9, grant_id=99)
        context = audit_context.current()
        assert (context.guild_id, context.grant_id) == (7, 88)
    finally:
        audit_context.end(token)


def test_noting_a_grant_outside_a_request_does_nothing():
    """The socket paths route a session with no request open; they record no
    line, so there is nothing for this to reach."""
    audit_context.note_grant(actor_user_id=1, guild_id=7, grant_id=88)
    assert audit_context.current() is None


@pytest.mark.parametrize(
    "supplied",
    ["abc-123", "A.B_c", "0", "f" * audit_context.MAX_REQUEST_ID],
)
def test_an_id_of_letters_digits_and_separators_is_kept(supplied):
    assert audit_context.clean_request_id(supplied) == supplied


@pytest.mark.parametrize(
    "supplied",
    [
        None,
        "",
        "has space",
        "quote'd",
        "new\nline",
        '{"json":1}',
        "f" * (audit_context.MAX_REQUEST_ID + 1),
    ],
)
def test_anything_else_is_not_an_id(supplied):
    """The id reaches a log line as it arrived, so it is held to a shape."""
    assert audit_context.clean_request_id(supplied) is None


def test_a_fresh_id_is_its_own():
    assert audit_context.new_request_id() != audit_context.new_request_id()
    assert audit_context.clean_request_id(audit_context.new_request_id())
