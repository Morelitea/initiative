"""Tests for the shared rate limiter configuration (SEC-14).

These assert *configuration* rather than throttling behaviour: the suite sets
``limiter.enabled = False`` (see ``conftest.py``), so a burst test would be
meaningless here and would flake against the hundreds of rapid requests other
tests make from the same client IP. We instead verify that the global default
limit and storage backend are settings-driven, and that ``SlowAPIMiddleware`` is
actually registered on the app so ``default_limits`` is no longer inert.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core import rate_limit
from app.core.config import settings
from app.core.rate_limit import _default_limits, get_real_client_ip, limiter
from app.main import app


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
        assert SlowAPIMiddleware in registered

    def test_app_uses_shared_limiter(self):
        assert app.state.limiter is rate_limit.limiter


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
