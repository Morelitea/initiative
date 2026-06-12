"""Tests for application settings parsing."""

from app.core.config import CAPACITOR_NATIVE_ORIGINS, Settings


def _settings(**overrides) -> Settings:
    overrides.setdefault("APP_URL", "https://app.example.com")
    return Settings(
        SECRET_KEY="test-secret",
        DATABASE_URL_APP="postgresql+asyncpg://app:app@localhost/app",
        DATABASE_URL_ADMIN="postgresql+asyncpg://admin:admin@localhost/app",
        **overrides,
    )


def test_cors_allowed_origins_accepts_comma_separated_string():
    settings = _settings(
        CORS_ALLOWED_ORIGINS="https://a.example.com, https://b.example.com",
    )

    # The raw field holds only the operator-supplied extras.
    assert settings.CORS_ALLOWED_ORIGINS == [
        "https://a.example.com",
        "https://b.example.com",
    ]
    # The effective allowlist always prepends APP_URL and appends native origins.
    assert settings.cors_origins == [
        "https://app.example.com",
        "https://a.example.com",
        "https://b.example.com",
        *CAPACITOR_NATIVE_ORIGINS,
    ]


def test_cors_origins_blank_does_not_fall_back_to_wildcard():
    # CRIT-001 regression: an unset/blank allowlist must NOT become "*".
    settings = _settings(CORS_ALLOWED_ORIGINS="")

    assert settings.CORS_ALLOWED_ORIGINS == []
    assert "*" not in settings.cors_origins
    assert settings.cors_origins == [
        "https://app.example.com",
        *CAPACITOR_NATIVE_ORIGINS,
    ]


def test_cors_origins_wildcard_is_dropped():
    # Even an explicit "*" is ignored — never reflected with credentials.
    settings = _settings(CORS_ALLOWED_ORIGINS="*, https://ok.example.com")

    assert "*" not in settings.cors_origins
    assert "https://ok.example.com" in settings.cors_origins
    assert "https://app.example.com" in settings.cors_origins


def test_cors_origins_always_includes_app_url_and_native_origins():
    settings = _settings(CORS_ALLOWED_ORIGINS="https://prod.example.com")

    assert "https://app.example.com" in settings.cors_origins
    for origin in CAPACITOR_NATIVE_ORIGINS:
        assert origin in settings.cors_origins


def test_cors_origins_no_duplicates():
    # Listing APP_URL / native origins explicitly must not duplicate them.
    settings = _settings(
        CORS_ALLOWED_ORIGINS=", ".join(
            [
                "https://app.example.com",
                "https://prod.example.com",
                *CAPACITOR_NATIVE_ORIGINS,
            ]
        ),
    )

    for origin in ["https://app.example.com", *CAPACITOR_NATIVE_ORIGINS]:
        assert settings.cors_origins.count(origin) == 1


def test_cors_origins_strips_trailing_slash():
    settings = _settings(
        APP_URL="https://app.example.com/",
        CORS_ALLOWED_ORIGINS="https://b.example.com/",
    )

    assert "https://app.example.com" in settings.cors_origins
    assert "https://b.example.com" in settings.cors_origins
    assert "https://app.example.com/" not in settings.cors_origins


def test_cors_origins_strips_path_component():
    # An Origin header is scheme+host only; a path on APP_URL (or an operator
    # origin) must be dropped or every credentialed cross-origin request fails.
    settings = _settings(
        APP_URL="https://app.example.com/initiative",
        CORS_ALLOWED_ORIGINS="https://admin.example.com/console",
    )

    assert "https://app.example.com" in settings.cors_origins
    assert "https://admin.example.com" in settings.cors_origins
    assert all(
        "/initiative" not in origin and "/console" not in origin
        for origin in settings.cors_origins
    )


def _directive(policy: str, name: str) -> str:
    """Return one directive segment (e.g. "script-src 'self'") from a CSP string."""
    for part in policy.split(";"):
        part = part.strip()
        if part == name or part.startswith(name + " "):
            return part
    return ""


def test_csp_confines_scripts_and_locks_down_vectors():
    csp = _settings().content_security_policy

    # Scripts are same-origin only — NO unsafe-inline/eval, so injected markup
    # can't execute even if it reaches the DOM.
    assert _directive(csp, "script-src") == "script-src 'self'"
    assert "'unsafe-eval'" not in csp

    # High-value hardening directives.
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    assert "form-action 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_csp_allows_inline_styles_but_not_scripts():
    # The chart component / UI libs inject inline <style>, so style-src must
    # permit 'unsafe-inline' — but script-src must not (asserted above).
    csp = _settings().content_security_policy
    assert "'unsafe-inline'" in _directive(csp, "style-src")
    assert "'unsafe-inline'" not in _directive(csp, "script-src")


def test_csp_websocket_scheme_follows_app_url():
    https = _settings(APP_URL="https://app.example.com").content_security_policy
    assert "wss:" in _directive(https, "connect-src")

    http = _settings(APP_URL="http://localhost:5173").content_security_policy
    assert "ws:" in _directive(http, "connect-src")


def test_csp_captcha_origins_only_when_configured():
    assert "hcaptcha.com" not in _settings().content_security_policy

    on = _settings(CAPTCHA_PROVIDER="hcaptcha").content_security_policy
    assert "https://*.hcaptcha.com" in _directive(on, "script-src")


def test_csp_advanced_tool_origin_only_when_configured():
    assert "tool.example.com" not in _settings().content_security_policy

    on = _settings(ADVANCED_TOOL_URL="https://tool.example.com/embed?x=1")
    csp = on.content_security_policy
    assert "https://tool.example.com" in _directive(csp, "frame-src")
    assert "https://tool.example.com" in _directive(csp, "connect-src")


def test_app_url_is_https_true_for_https():
    # Drives both the Secure cookie flag and the HSTS header (pentest SEC-16).
    assert _settings(APP_URL="https://app.example.com").app_url_is_https is True
    assert _settings(APP_URL="https://app.example.com").cookie_secure is True


def test_app_url_is_https_false_for_http():
    s = _settings(APP_URL="http://localhost:5173")
    assert s.app_url_is_https is False
    assert s.cookie_secure is False


def test_app_url_is_https_ignores_substring_scheme():
    # A host that merely contains "https" must not be treated as https — only
    # the URL scheme counts.
    assert _settings(APP_URL="http://https.example.com").app_url_is_https is False


def test_enable_api_docs_defaults_true():
    # Default on for dev ergonomics; operators set it False in production.
    assert _settings().ENABLE_API_DOCS is True


def test_enable_api_docs_can_be_disabled():
    assert _settings(ENABLE_API_DOCS=False).ENABLE_API_DOCS is False
