"""Tests for XSS sanitisation on task title and description fields.

Findings addressed:
  CRIT-002 – Stored XSS + DoS via task title/description
  (pentest 2026-05-07, initiative-dev.morels.me)
"""

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskBase, TaskUpdate


# ---------------------------------------------------------------------------
# Title sanitisation – plain text only, all HTML stripped
# ---------------------------------------------------------------------------


class TestTaskTitleSanitization:
    def test_plain_text_unchanged(self):
        t = TaskBase(title="Fix login bug", project_id=1)
        assert t.title == "Fix login bug"

    def test_img_onerror_stripped(self):
        """The exact payload used in the pentest."""
        payload = '<img src=x onerror=window.__xss=document.cookie>'
        t = TaskBase(title=payload, project_id=1)
        assert "<img" not in t.title
        assert "onerror" not in t.title

    def test_script_tag_stripped(self):
        t = TaskBase(title="<script>alert(1)</script>hello", project_id=1)
        assert "<script>" not in t.title
        assert "hello" in t.title

    def test_anchor_tag_stripped(self):
        t = TaskBase(title='<a href="javascript:alert(1)">click</a>', project_id=1)
        assert "<a" not in t.title
        assert "click" in t.title

    def test_nested_html_stripped(self):
        t = TaskBase(title="<b><i>bold italic</i></b>", project_id=1)
        assert "<b>" not in t.title
        assert "bold italic" in t.title

    def test_empty_string_stays_empty(self):
        # Empty string is falsy — validator should pass it through
        # (validation still rejects empty after strip in Pydantic min_length if set,
        #  but our validator should not crash on it)
        with pytest.raises(ValidationError):
            TaskBase(title="", project_id=1)

    def test_task_update_title_sanitized(self):
        u = TaskUpdate(title='<img src=x onerror=alert(1)> urgent fix')
        assert "<img" not in u.title
        assert "urgent fix" in u.title


# ---------------------------------------------------------------------------
# Description sanitisation – dangerous tags/attrs stripped, safe content kept
# ---------------------------------------------------------------------------


class TestTaskDescriptionSanitization:
    def test_none_unchanged(self):
        t = TaskBase(title="Task", description=None, project_id=1)
        assert t.description is None

    def test_plain_text_unchanged(self):
        t = TaskBase(title="Task", description="Steps to reproduce", project_id=1)
        assert t.description == "Steps to reproduce"

    def test_script_tag_stripped(self):
        """Exact pentest payload."""
        payload = '"><script>window.__desc_xss=1</script><b onmouseover=window.__x=1>hover</b>'
        t = TaskBase(title="Task", description=payload, project_id=1)
        assert "<script>" not in t.description
        assert "window.__desc_xss" not in t.description

    def test_event_handlers_stripped(self):
        t = TaskBase(
            title="Task",
            description='<b onmouseover="alert(1)">text</b>',
            project_id=1,
        )
        assert "onmouseover" not in t.description
        # The text inside should survive
        assert "text" in t.description

    def test_javascript_uri_blocked(self):
        t = TaskBase(
            title="Task",
            description='<a href="javascript:alert(1)">link</a>',
            project_id=1,
        )
        assert "javascript:" not in t.description

    def test_iframe_stripped(self):
        t = TaskBase(
            title="Task",
            description='<iframe src="https://evil.com"></iframe>',
            project_id=1,
        )
        assert "<iframe" not in t.description

    def test_onerror_attribute_stripped(self):
        t = TaskBase(
            title="Task",
            description='<img src=x onerror=fetch("//evil.com")>',
            project_id=1,
        )
        assert "onerror" not in t.description

    def test_task_update_description_sanitized(self):
        u = TaskUpdate(description='<script>steal(document.cookie)</script>notes')
        assert "<script>" not in u.description
        assert "notes" in u.description


# ---------------------------------------------------------------------------
# CORS config – settings.cors_origins returns correct allowlist
# ---------------------------------------------------------------------------


class TestCorsOrigins:
    def test_defaults_to_app_url(self, monkeypatch):
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x",
            DATABASE_URL_APP="postgresql+asyncpg://a:b@localhost/c",
            DATABASE_URL_ADMIN="postgresql+asyncpg://a:b@localhost/c",
            APP_URL="https://app.example.com",
        )
        assert "https://app.example.com" in s.cors_origins

    def test_allowed_origins_string_parsed(self, monkeypatch):
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

    def test_wildcard_not_in_default_origins(self):
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x",
            DATABASE_URL_APP="postgresql+asyncpg://a:b@localhost/c",
            DATABASE_URL_ADMIN="postgresql+asyncpg://a:b@localhost/c",
        )
        assert "*" not in s.cors_origins
