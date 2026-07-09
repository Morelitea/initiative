"""The OIDC relying-party flow: ``begin`` (authorization redirect) and
``complete`` (code exchange + verified identity).

Composes the package's building blocks — discovery, the encrypted flow state,
the JWKS resolver, and the id_token verifier — into the two operations a login
endpoint needs. Pure with respect to storage: configuration comes in as plain
values (the caller loads the provider row and decrypts the client secret), and
the result is the token response plus **verified** id_token claims; identity
resolution against the database is the caller's next step.

``complete`` accepts nothing on trust: the callback's ``state`` must decrypt
and be fresh, the token response must carry an ``id_token``, and the id_token
must verify (signature via the provider's JWKS, issuer, audience, expiry, and
the nonce bound to this login attempt). Signing algorithms are the
intersection of what discovery advertises with the asymmetric allowlist —
empty intersection is an error, never a fallback.

Every failure raises :class:`OidcFlowError` carrying a stable ``code`` for the
endpoint to map to a user-facing error; details stay server-side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

from app.services.auth.oidc._http import (
    DEFAULT_HTTP_TIMEOUT_SECONDS,
    ClientFactory,
    OidcHttpError,
    fetch_json,
    post_form_json,
)
from app.services.auth.oidc.discovery import (
    DiscoveryError,
    OidcDiscovery,
    OidcMetadata,
)
from app.services.auth.oidc.flow_state import (
    DEFAULT_MAX_AGE_SECONDS,
    FlowStateError,
    create_flow_state,
    decode_flow_state,
)
from app.services.auth.oidc.id_token import (
    ASYMMETRIC_ALGORITHMS,
    DEFAULT_ALGORITHMS,
    IdTokenVerificationError,
    verify_id_token,
)
from app.services.auth.oidc.jwks import JwksResolutionError, JwksResolver

DEFAULT_SCOPES = "openid email profile"


class OidcFlowError(Exception):
    """A login flow step failed; the attempt must be rejected (fail-closed).

    ``code`` is a stable machine-readable identifier for the endpoint to map to
    a localized user-facing error; the message is for server logs only.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class OidcClientConfig:
    """One provider's client registration, as plain values.

    Raises :class:`ValueError` at construction for an empty ``issuer``,
    ``client_id``, or ``redirect_uri`` — a misconfiguration must surface where
    the provider is built, not as a stray error mid-login.
    """

    issuer: str
    client_id: str
    redirect_uri: str
    client_secret: str | None = None  # None = public client (PKCE-only)
    scopes: str = DEFAULT_SCOPES

    def __post_init__(self) -> None:
        for field_name in ("issuer", "client_id", "redirect_uri"):
            if not getattr(self, field_name):
                raise ValueError(f"OidcClientConfig.{field_name} must be non-empty")


@dataclass(frozen=True)
class OidcBegin:
    """What the login endpoint needs to redirect the user to the IdP."""

    authorization_url: str
    state: str


@dataclass(frozen=True)
class OidcCompletion:
    """The outcome of a verified code exchange.

    ``claims`` are the **verified** id_token claims — the identity source of
    truth. ``access_token`` is kept for userinfo/claim-mapping enrichment;
    ``refresh_token`` (if the IdP issued one) for group re-sync.
    """

    subject: str
    claims: dict[str, Any]
    id_token: str
    access_token: str | None
    refresh_token: str | None
    mobile: bool
    device_name: str


class OidcProvider:
    """A relying-party client for one configured OIDC provider."""

    def __init__(
        self,
        config: OidcClientConfig,
        *,
        discovery: OidcDiscovery | None = None,
        jwks: JwksResolver | None = None,
        client_factory: ClientFactory | None = None,
        http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        max_state_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    ) -> None:
        self._config = config
        self._client_factory = client_factory
        self._timeout = http_timeout_seconds
        self._max_state_age = max_state_age_seconds
        self._discovery = discovery or OidcDiscovery(
            client_factory=client_factory, http_timeout_seconds=http_timeout_seconds
        )
        self._jwks = jwks or JwksResolver(
            client_factory=client_factory, http_timeout_seconds=http_timeout_seconds
        )

    async def begin(self, *, mobile: bool = False, device_name: str = "") -> OidcBegin:
        """Mint the flow state and build the authorization redirect URL."""
        metadata = await self._fetch_metadata()
        state, payload = create_flow_state(mobile=mobile, device_name=device_name)
        params = {
            "response_type": "code",
            "client_id": self._config.client_id,
            "redirect_uri": self._config.redirect_uri,
            "scope": self._config.scopes,
            "state": state,
            "nonce": payload.nonce,
            "code_challenge": payload.code_challenge,
            "code_challenge_method": "S256",
        }
        endpoint = metadata.authorization_endpoint
        separator = "&" if urlsplit(endpoint).query else "?"
        return OidcBegin(
            authorization_url=f"{endpoint}{separator}{urlencode(params)}",
            state=state,
        )

    async def complete(self, *, code: str, state: str) -> OidcCompletion:
        """Exchange the callback's authorization code and verify the id_token."""
        if not code:
            raise OidcFlowError("missing_authorization_code", "callback without code")
        try:
            flow = decode_flow_state(state, max_age_seconds=self._max_state_age)
        except FlowStateError as exc:
            raise OidcFlowError("invalid_state", str(exc)) from exc

        metadata = await self._fetch_metadata()
        token_data = await self._exchange_code(
            metadata, code=code, code_verifier=flow.code_verifier
        )
        raw_id_token = token_data.get("id_token")
        if not raw_id_token or not isinstance(raw_id_token, str):
            raise OidcFlowError(
                "token_missing_id_token", "token response carried no id_token"
            )

        try:
            signing_key = await self._jwks.resolve_signing_key(
                raw_id_token, jwks_uri=metadata.jwks_uri
            )
        except JwksResolutionError as exc:
            raise OidcFlowError("id_token_unverifiable", str(exc)) from exc
        try:
            claims = verify_id_token(
                raw_id_token,
                signing_key=signing_key,
                issuer=metadata.issuer,
                audience=self._config.client_id,
                nonce=flow.nonce,
                algorithms=self._allowed_algorithms(metadata),
            )
        except IdTokenVerificationError as exc:
            raise OidcFlowError("id_token_rejected", str(exc)) from exc

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        return OidcCompletion(
            subject=claims["sub"],
            claims=claims,
            id_token=raw_id_token,
            access_token=access_token if isinstance(access_token, str) else None,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            mobile=flow.mobile,
            device_name=flow.device_name,
        )

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any] | None:
        """Fetch the userinfo document for ``access_token``, or ``None`` when
        the provider advertises no userinfo endpoint.

        Enrichment only — identity always comes from the verified id_token.
        The caller must discard the result if its ``sub`` does not match the
        id_token's (OIDC Core §5.3.2). Raises :class:`OidcFlowError`
        (``userinfo_failed``) on a fetch or shape failure; the caller decides
        whether that is fatal for its flow.
        """
        metadata = await self._fetch_metadata()
        if not metadata.userinfo_endpoint:
            return None
        try:
            document = await fetch_json(
                metadata.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
                client_factory=self._client_factory,
                timeout_seconds=self._timeout,
            )
        except OidcHttpError as exc:
            raise OidcFlowError("userinfo_failed", str(exc)) from exc
        if not isinstance(document, dict):
            raise OidcFlowError("userinfo_failed", "userinfo is not a JSON object")
        return document

    async def _fetch_metadata(self) -> OidcMetadata:
        try:
            return await self._discovery.fetch(self._config.issuer)
        except DiscoveryError as exc:
            raise OidcFlowError("discovery_failed", str(exc)) from exc

    async def _exchange_code(
        self, metadata: OidcMetadata, *, code: str, code_verifier: str
    ) -> dict[str, Any]:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._config.redirect_uri,
            "client_id": self._config.client_id,
            "code_verifier": code_verifier,
        }
        # client_secret_post, matching the existing flow; a public (PKCE-only)
        # client simply sends no secret.
        if self._config.client_secret:
            payload["client_secret"] = self._config.client_secret
        try:
            token_data = await post_form_json(
                metadata.token_endpoint,
                payload,
                client_factory=self._client_factory,
                timeout_seconds=self._timeout,
            )
        except OidcHttpError as exc:
            raise OidcFlowError("token_request_failed", str(exc)) from exc
        if not isinstance(token_data, dict):
            raise OidcFlowError(
                "token_request_failed", "token response is not a JSON object"
            )
        return token_data

    def _allowed_algorithms(self, metadata: OidcMetadata) -> tuple[str, ...]:
        """The verifier allowlist: discovery's advertised algs filtered to the
        asymmetric set, or the default pair when discovery doesn't advertise.
        An intersection that comes up empty is an error, never a fallback."""
        advertised = metadata.id_token_signing_alg_values_supported
        if advertised is None:
            return DEFAULT_ALGORITHMS
        allowed = tuple(a for a in advertised if a in ASYMMETRIC_ALGORITHMS)
        if not allowed:
            raise OidcFlowError(
                "id_token_rejected",
                f"provider advertises no asymmetric id_token algs: {advertised}",
            )
        return allowed
