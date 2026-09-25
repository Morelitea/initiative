"""A vendor and an app, answering the calls a connection's flow makes.

Every outbound call the flow module makes goes through one transport
(``app_connection_flows.http_transport``) after the pinned egress helper has
resolved its host. :meth:`FakeVendor.install` points both at this object: the
host resolves to a fixed public address, and the request is answered here by
the host it names.

The vendor side is an OAuth 2.0 authorization server with PKCE, refresh,
revocation and a GitHub-style installation token exchange. The app side answers
the two hooks.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import parse_qsl

import httpx

from app.services import safe_http
from app.services.webhook_target_url import ValidatedTarget

__all__ = ["FakeVendor"]

VENDOR_HOST = "github.test"


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class FakeVendor:
    client_id: str = "client-123"
    client_secret: str = "client-secret-456"
    #: What each new access token lives, in seconds.
    expires_in: int = 28800
    #: The vendor refuses every refresh.
    refuse_refresh: bool = False
    #: What the app's after_connect hook answers.
    after_connect_answer: Any = field(
        default_factory=lambda: {
            "values": {"login": "alice"},
            "account_label": "@alice",
        }
    )
    #: The status the app's hooks answer with.
    hook_status: int = 200
    #: The status the vendor's revocation endpoint answers with.
    revoke_status: int = 200

    codes: dict[str, str] = field(default_factory=dict)
    token_requests: list[dict[str, str]] = field(default_factory=list)
    refreshes: int = 0
    revocations: list[dict[str, str]] = field(default_factory=list)
    hooks: list[tuple[str, dict[str, Any], str]] = field(default_factory=list)
    exchanges: list[str] = field(default_factory=list)
    _serial: Any = field(default_factory=lambda: itertools.count(1))

    # --- the test's side ------------------------------------------------

    def install(self, monkeypatch: Any) -> None:
        """Answer every outbound call of the flow module from here."""
        from app.services.tenant import app_connection_flows

        async def resolve(url: str, *, allow_private: bool = False) -> ValidatedTarget:
            host = httpx.URL(url).host
            return ValidatedTarget(
                hostname=host, addresses=(ipaddress.ip_address("93.184.216.34"),)
            )

        monkeypatch.setattr(safe_http, "resolve_validated_target_async", resolve)
        monkeypatch.setattr(
            app_connection_flows, "http_transport", httpx.MockTransport(self.handle)
        )

    def authorize(self, challenge: Optional[str]) -> str:
        """What the vendor's authorization page does when the person agrees:
        mint a code bound to the challenge it was sent."""
        code = f"code-{next(self._serial)}"
        self.codes[code] = challenge or ""
        return code

    # --- the vendor's and the app's side --------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host", "")
        path = request.url.path
        if host == VENDOR_HOST:
            if path == "/login/oauth/access_token":
                return self._token(request)
            if path == "/revoke":
                self.revocations.append(dict(parse_qsl(request.content.decode())))
                return httpx.Response(self.revoke_status)
            if path.startswith("/app/installations/"):
                return self._exchange(request)
            return httpx.Response(404)
        if path.startswith("/v1/hooks/"):
            name = path[len("/v1/hooks/") :]
            self.hooks.append(
                (
                    name,
                    json.loads(request.content or b"{}"),
                    request.headers.get("authorization", ""),
                )
            )
            if self.hook_status >= 300:
                return httpx.Response(self.hook_status)
            if name == "revoke":
                return httpx.Response(204)
            return httpx.Response(200, json=self.after_connect_answer)
        return httpx.Response(404)

    def _issue(self) -> dict[str, Any]:
        serial = next(self._serial)
        return {
            "access_token": f"gho_access_{serial}",
            "refresh_token": f"ghr_refresh_{serial}",
            "expires_in": self.expires_in,
            "token_type": "bearer",
        }

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        self.token_requests.append(form)
        if (
            form.get("client_id") != self.client_id
            or form.get("client_secret") != self.client_secret
        ):
            return httpx.Response(401, json={"error": "invalid_client"})
        if form.get("grant_type") == "refresh_token":
            self.refreshes += 1
            if self.refuse_refresh:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json=self._issue())
        code = form.get("code", "")
        if code not in self.codes:
            # A success status carrying an error, as some vendors answer.
            return httpx.Response(200, json={"error": "bad_verification_code"})
        challenge = self.codes.pop(code)
        verifier = form.get("code_verifier", "")
        if challenge and _challenge(verifier) != challenge:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json=self._issue())

    def _exchange(self, request: httpx.Request) -> httpx.Response:
        self.exchanges.append(request.headers.get("authorization", ""))
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        return httpx.Response(
            201,
            json={
                "token": f"ghs_installation_{next(self._serial)}",
                "expires_at": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
