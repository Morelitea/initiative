"""Tests for the shared rate limiter configuration (SEC-14).

These assert *configuration* rather than throttling behaviour: the suite sets
``limiter.enabled = False`` (see ``conftest.py``), so a burst test would be
meaningless here and would flake against the hundreds of rapid requests other
tests make from the same client IP. We instead verify that the global default
limit and storage backend are settings-driven, and that ``SlowAPIMiddleware`` is
actually registered on the app so ``default_limits`` is no longer inert.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware, _find_route_handler
from starlette.datastructures import Headers
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import (
    _default_limits,
    get_inet_client_ip,
    get_real_client_ip,
    get_user_or_ip_key,
    limiter,
)
from app.main import _MOUNTED, _route_endpoint, app


class TestDefaultLimitsBuilder:
    """The default-limit list is derived from RATE_LIMIT_DEFAULT."""

    def test_configured_value_produces_one_entry(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "100/minute")
        assert _default_limits() == ["100/minute"]

    def test_empty_string_disables_default(self, monkeypatch):
        """An empty value means "no global default" — and must NOT be passed to
        slowapi as ``[""]`` (which raises ValueError during parsing)."""
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "")
        assert _default_limits() == []

    def test_whitespace_only_disables_default(self, monkeypatch):
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "   ")
        assert _default_limits() == []

    def test_empty_default_builds_a_usable_limiter(self, monkeypatch):
        """A limiter built from an empty default must construct without error."""
        monkeypatch.setattr(settings, "RATE_LIMIT_DEFAULT", "")
        built = Limiter(
            key_func=get_real_client_ip,
            default_limits=_default_limits(),
            storage_uri=settings.RATE_LIMIT_STORAGE_URI,
        )
        assert built._default_limits == []


class TestLimiterConfiguration:
    """The shared limiter instance reflects the configured settings."""

    def test_default_limit_registered(self):
        # The module is imported with the packaged default ("100/minute"), so a
        # single default LimitGroup should be present.
        assert len(limiter._default_limits) == 1

    def test_storage_uri_is_settings_driven(self):
        # Defaults to in-memory; a multi-worker deploy can point this at Redis
        # via RATE_LIMIT_STORAGE_URI with no code change.
        assert limiter._storage_uri == settings.RATE_LIMIT_STORAGE_URI

    def test_default_storage_is_in_memory(self):
        assert settings.RATE_LIMIT_STORAGE_URI == "memory://"


class TestMiddlewareRegistration:
    """SlowAPIMiddleware must be in the app's middleware stack, otherwise the
    limiter's default_limits never apply to undecorated routes (SEC-14)."""

    def test_slowapi_middleware_registered(self):
        registered = {m.cls for m in app.user_middleware}
        assert any(issubclass(cls, SlowAPIMiddleware) for cls in registered), registered

    def test_app_uses_shared_limiter(self):
        assert app.state.limiter is rate_limit.limiter


class TestRouteResolution:
    """The middleware has to read the route the router will actually run.

    Upstream picks one by scanning every route and keeping the LAST that
    matches; this app ends with a catch-all serving the SPA, which matches
    everything. ``_route_endpoint`` resolves the way the router does instead.
    """

    def _endpoint(self, path: str, method: str = "GET", host=app):
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [],
            "root_path": "",
            "app": host,
        }
        return _route_endpoint(Request(scope))

    def test_resolves_the_route_the_router_runs(self):
        assert self._endpoint("/api/v1/version").__name__ == "get_version"
        assert self._endpoint("/api/v1/readyz").__name__ == "readyz"

    def test_upstream_would_have_answered_the_catch_all(self):
        """Pins why this app cannot use the stock middleware. Should a later
        slowapi resolve first-match, this fails and the override can go."""
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/version",
            "headers": [],
            "root_path": "",
        }
        assert _find_route_handler(app.routes, scope).__name__ == "serve_spa"

    def test_an_unmatched_request_resolves_to_nothing(self):
        assert self._endpoint("/api/v1/version", method="DELETE") is None

    def test_a_mounted_sub_app_is_told_apart_from_no_match(self):
        """A mount carries no endpoint. That must not read back as "no route",
        which slowapi treats as exempt — a whole mounted surface would lose the
        default limit. Built here rather than read off the app so the case is
        covered whether or not this configuration mounts anything."""
        host = Starlette(routes=[Mount("/sub", app=Starlette())])
        assert self._endpoint("/sub/anything", host=host) is _MOUNTED


class TestDefaultLimitThrottlesUndecoratedRoute:
    """The global default applied via the middleware actually throttles a route
    that has no ``@limiter.limit`` decorator (SEC-14 acceptance).

    Built on a throwaway app + a fresh Limiter (its own in-memory storage), so
    it shares no state with the suite-wide limiter and can't flake against other
    tests' requests. Enabled here on purpose; the suite-wide limiter stays off.
    """

    def _build_app(self, default: str) -> FastAPI:
        burst_limiter = Limiter(
            key_func=lambda request: "fixed-test-key",
            default_limits=[default] if default else [],
            storage_uri="memory://",
        )
        burst_app = FastAPI()
        burst_app.state.limiter = burst_limiter
        burst_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        burst_app.add_middleware(SlowAPIMiddleware)

        @burst_app.get("/undecorated")
        async def undecorated() -> dict[str, bool]:
            return {"ok": True}

        return burst_app

    async def test_burst_past_default_is_rejected(self):
        burst_app = self._build_app("3/minute")
        transport = ASGITransport(app=burst_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            statuses = [(await c.get("/undecorated")).status_code for _ in range(5)]
        # First 3 within the window succeed, the rest are throttled.
        assert statuses[:3] == [200, 200, 200]
        assert 429 in statuses[3:]

    async def test_empty_default_does_not_throttle(self):
        """With RATE_LIMIT_DEFAULT unset, undecorated routes are unthrottled."""
        burst_app = self._build_app("")
        transport = ASGITransport(app=burst_app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            statuses = [(await c.get("/undecorated")).status_code for _ in range(10)]
        assert all(code == 200 for code in statuses)


class TestInetClientIp:
    """``get_inet_client_ip`` returns a value suitable for Postgres ``inet``."""

    @staticmethod
    def _request(address: str):
        class _Client:
            host = address

        class _Req:
            headers = {}
            client = _Client()

        return _Req()

    def test_an_ipv6_zone_identifier_is_removed(self):
        req = self._request("fe80::1%eth0")
        result = get_inet_client_ip(req)
        assert result == "fe80::1"
        assert "%" not in result

    def test_addresses_come_back_normalized(self):
        assert get_inet_client_ip(self._request("2001:DB8::1")) == "2001:db8::1"
        assert get_inet_client_ip(self._request("203.0.113.9")) == "203.0.113.9"

    def test_a_non_address_is_refused(self):
        assert get_inet_client_ip(self._request("not-an-ip")) is None


class TestRealClientIp:
    def test_the_address_comes_from_the_asgi_server(self):
        """The ASGI server, not application code, decides which proxy to trust."""

        class _Client:
            host = "198.51.100.7"

        class _Request:
            headers = Headers(
                {
                    "X-Forwarded-For": "203.0.113.9",
                    "X-Real-IP": "203.0.113.10",
                }
            )
            client = _Client()

        assert get_real_client_ip(_Request()) == "198.51.100.7"


class TestUserOrIpKey:
    """``get_user_or_ip_key`` counts per account where there is one.

    The routes that use it are reached only while signed in, and several
    accounts commonly share one address, so the account is the counter rather
    than the address it arrived from.
    """

    @staticmethod
    def _request(*, user_id: int | None = None) -> Request:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/",
                "headers": [],
                "client": ("198.51.100.7", 40404),
            }
        )
        if user_id is not None:
            request.state.user_id = user_id
        return request

    def test_a_signed_in_account_is_its_own_counter(self):
        assert get_user_or_ip_key(self._request(user_id=42)) == "user:42"

    def test_the_address_is_the_counter_when_nobody_is_named(self):
        assert get_user_or_ip_key(self._request()) == "198.51.100.7"

    def test_an_installed_app_is_counted_by_client_and_install(self):
        request = self._request()
        request.state.app_install = ("acme.widgets", 7, 3)
        assert get_user_or_ip_key(request) == "install:acme.widgets:7:3"


class TestDefaultLimitOnTheRealApp:
    """What the default does on the app as assembled, catch-all and all.

    ``TestDefaultLimitThrottlesUndecoratedRoute`` above builds a throwaway app
    with two routes, where slowapi's last-match resolution happens to land on
    the right one. These go through the real router, which is where it does
    not.
    """

    @pytest.fixture(autouse=True)
    def _throttled(self, rate_limit_of_one_per_minute):
        pass

    async def test_an_undecorated_route_takes_the_default(self, client):
        assert (await client.get("/api/v1/version")).status_code == 200
        assert (await client.get("/api/v1/version")).status_code == 429

    async def test_a_decorated_route_takes_its_own_limit_instead(self, client):
        """A route carrying ``@limiter.limit`` is left to its decorator rather
        than also counted against the default, so one set ABOVE the default is
        not quietly held down to it. ``/auth/username-available`` asks for 60 a
        minute, so under a 1-a-minute default it still answers a second time."""
        path = "/api/v1/auth/username-available?username=someone"
        assert (await client.get(path)).status_code == 200
        assert (await client.get(path)).status_code == 200

    async def test_an_exempt_route_takes_no_limit_at_all(self, client):
        assert (await client.get("/api/v1/healthz")).status_code == 200
        assert (await client.get("/api/v1/healthz")).status_code == 200
