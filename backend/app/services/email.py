from __future__ import annotations

import asyncio
import logging
import html as _html
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.email_i18n import email_t
from app.core.encryption import decrypt_field, SALT_SMTP_PASSWORD
from app.models.app_setting import AppSetting
from app.models.user import User
from app.services import app_settings as app_settings_service

try:  # premailer inlines our <style> rules so they survive Gmail/Outlook stripping <style>
    from premailer import transform as _premailer_transform
except Exception:  # pragma: no cover - optional dependency guard
    _premailer_transform = None

logger = logging.getLogger(__name__)


class EmailNotConfiguredError(RuntimeError):
    pass


@dataclass
class SMTPConfig:
    host: str
    port: int
    secure: bool
    reject_unauthorized: bool
    username: str | None
    password: str | None
    from_address: str


def _accent_color(settings_obj: AppSetting | None) -> str:
    value = ""
    if settings_obj and settings_obj.light_accent_color:
        value = settings_obj.light_accent_color.strip()
    if not value or not re.match(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", value):
        return "#2563eb"
    return value


async def _email_context(session: AsyncSession) -> tuple[AppSetting, str]:
    settings_obj = await app_settings_service.get_app_settings(session)
    return settings_obj, _accent_color(settings_obj)


# Email clients (Gmail, Outlook, Yahoo) strip inline <svg>, so the brand mark is
# shipped as a raster PNG and embedded inline via a Content-ID reference. This
# displays without an external fetch — no "show images" prompt, no broken icon.
_LOGO_PATH = Path(__file__).resolve().parent.parent / "assets" / "email-logo.png"
LOGO_CID = "initiative-logo"


@lru_cache(maxsize=1)
def _logo_bytes() -> bytes | None:
    try:
        return _LOGO_PATH.read_bytes()
    except (
        OSError
    ):  # pragma: no cover - asset is committed; guard against odd packaging
        logger.warning("Email logo asset missing at %s", _LOGO_PATH)
        return None


def _build_html_layout(
    title: str, body: str, accent_color: str, locale: str = "en"
) -> str:
    footer_disclaimer = email_t("layout.footerDisclaimer", locale=locale)
    update_link_text = email_t("layout.updateNotifications", locale=locale)
    return f"""\
<html>
  <body style="font-family:'Outfit','Inter','Segoe UI',Arial,sans-serif;color:#0f172a;background-color:#f3f4f6;padding:24px;">
    <div style="max-width:520px;margin:0 auto;background-color:#ffffff;padding:28px;border-radius:16px;border:1px solid #e2e8f0;box-shadow:0 10px 40px rgba(15,23,42,0.08);">
      <style>
        a {{
          color: {accent_color};
          text-decoration: none;
          font-weight: 600;
        }}
      </style>
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">
        <a href="{app_config.APP_URL}" style="display:inline-block;">
          <img src="cid:{LOGO_CID}" width="44" height="44" alt="Initiative" style="display:block;width:44px;height:44px;border:0;border-radius:12px;" />
        </a>
        <div>
          <p style="margin:0;font-size:18px;font-weight:700;color:{accent_color};"><a href="{app_config.APP_URL}">initiative</a></p>
        </div>
      </div>
      <h2 style="margin-top:0;font-size:22px;color:#0f172a;">{title}</h2>
      <div style="font-size:15px;line-height:1.5;color:#334155;">{body}</div>
      <p style="font-size:12px;color:#94a3b8;margin-top:32px;">
        {footer_disclaimer}
      </p>
      <p>
        <a href="{app_config.APP_URL}/profile/notifications">{update_link_text}</a>
      </p>
    </div>
  </body>
</html>
"""


def _strip_html(html: str) -> str:
    """Reduce an HTML email fragment to its plain-text alternative.

    Strips trusted template tags, then unescapes entities so values that were
    HTML-escaped for the HTML part (see ``email_i18n``) read as the user's
    literal text in the text/plain part.

    Deliberate consequence: a user-supplied value that itself looks like markup
    (e.g. a display name of ``<a href="https://x">…</a>``) appears verbatim in
    the text part — including any URL, which a client's auto-linkification may
    make clickable. That is acceptable for text/plain (no styling or trust
    cues, unlike the brand-styled HTML part), and the alternative — leaving
    entities encoded — would corrupt legitimate names like ``Tom & Jerry``.
    """
    return _html.unescape(re.sub(r"<[^>]+>", "", html))


def _build_smtp_config(settings_obj: AppSetting) -> SMTPConfig:
    host = settings_obj.smtp_host
    from_address = settings_obj.smtp_from_address
    if not host or not from_address:
        raise EmailNotConfiguredError("SMTP host or from address missing")
    port = settings_obj.smtp_port or (465 if settings_obj.smtp_secure else 587)
    return SMTPConfig(
        host=host,
        port=port,
        secure=bool(settings_obj.smtp_secure),
        reject_unauthorized=bool(settings_obj.smtp_reject_unauthorized),
        username=settings_obj.smtp_username,
        password=decrypt_field(settings_obj.smtp_password_encrypted, SALT_SMTP_PASSWORD)
        if settings_obj.smtp_password_encrypted
        else None,
        from_address=from_address,
    )


def _smtp_context(reject_unauthorized: bool) -> ssl.SSLContext:
    if reject_unauthorized:
        return ssl.create_default_context()
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _deliver(config: SMTPConfig, message: EmailMessage) -> None:
    context = _smtp_context(config.reject_unauthorized)
    if config.secure:
        with smtplib.SMTP_SSL(config.host, config.port, context=context) as client:
            _send_via_client(client, config, message)
    else:
        with smtplib.SMTP(config.host, config.port) as client:
            client.ehlo()
            try:
                client.starttls(context=context)
                client.ehlo()
            except smtplib.SMTPException:
                logger.debug(
                    "STARTTLS not available for SMTP host %s:%s",
                    config.host,
                    config.port,
                )
            _send_via_client(client, config, message)


def _send_via_client(
    client: smtplib.SMTP, config: SMTPConfig, message: EmailMessage
) -> None:
    if config.username and config.password:
        client.login(config.username, config.password)
    client.send_message(message)


def _user_locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


def _display_name(user: User) -> str:
    return user.full_name or user.email


def _inline_css(html: str) -> str:
    """Inline <style> rules into element style attributes via premailer.

    Gmail's mobile app and several clients strip <style> blocks, which would
    drop our link colours/weights. Inlining makes them survive. Failures here
    must never block an email, so we fall back to the original HTML.
    """
    if _premailer_transform is None:
        return html
    try:
        return _premailer_transform(
            html,
            keep_style_tags=False,
            remove_classes=True,
            disable_validation=True,
            cssutils_logging_level=logging.CRITICAL,
        )
    except Exception:  # pragma: no cover - defensive: never fail send over styling
        logger.warning(
            "premailer CSS inlining failed; sending un-inlined HTML", exc_info=True
        )
        return html


def _cta_button(label: str, link: str, accent: str) -> str:
    return (
        f'<a href="{link}" style="background-color:{accent};color:#ffffff;'
        f"padding:12px 18px;border-radius:8px;text-decoration:none;"
        f'font-weight:600;display:inline-block;">{label}</a>'
    )


def _embed_logo(message: EmailMessage) -> None:
    """Attach the brand logo as an inline image referenced by ``cid:LOGO_CID``.

    The HTML alternative is wrapped in a multipart/related part holding the PNG,
    so the logo renders inline without an external fetch. No-op when the asset
    is missing (the <img> alt text shows instead).
    """
    logo = _logo_bytes()
    if not logo:
        return
    payload = message.get_payload()
    if not isinstance(payload, list):
        return
    # Locate the text/html alternative explicitly rather than assuming a
    # position, so this stays correct regardless of how the message was built.
    html_part = next(
        (part for part in payload if part.get_content_type() == "text/html"), None
    )
    if html_part is None:
        return
    html_part.add_related(logo, "image", "png", cid=f"<{LOGO_CID}>")


async def send_email(
    session: AsyncSession,
    *,
    recipients: Sequence[str],
    subject: str,
    html_body: str,
    text_body: str | None = None,
    settings_obj: AppSetting | None = None,
) -> None:
    if not recipients:
        raise ValueError("At least one recipient email is required")
    if settings_obj is None:
        settings_obj = await app_settings_service.get_app_settings(session)
    config = _build_smtp_config(settings_obj)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.from_address
    message["To"] = ", ".join(recipients)
    plain = text_body or _strip_html(html_body)
    message.set_content(plain)
    message.add_alternative(_inline_css(html_body), subtype="html")
    _embed_logo(message)
    try:
        await asyncio.to_thread(_deliver, config, message)
    except EmailNotConfiguredError:
        raise
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to send email: %s", exc)
        raise RuntimeError("Failed to send email") from exc


async def send_test_email(session: AsyncSession, recipient: str) -> None:
    settings_obj, accent = await _email_context(session)
    locale = "en"
    html_body = _build_html_layout(
        email_t("test.title", locale=locale),
        f"<p>{email_t('test.body', locale=locale)}</p>",
        accent,
        locale=locale,
    )
    await send_email(
        session,
        recipients=[recipient],
        subject=email_t("test.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=email_t("test.body", locale=locale, escape=False),
        settings_obj=settings_obj,
    )


def _frontend_url(path: str) -> str:
    base = app_config.APP_URL.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


async def send_verification_email(
    session: AsyncSession, user: User, token: str
) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url(f"/verify-email?token={token}")
    button = _cta_button(
        email_t("verification.buttonLabel", locale=locale), link, accent
    )
    body = f"""
    <p>{email_t("verification.greeting", locale=locale, name=name)}</p>
    <p>{email_t("verification.body", locale=locale)}</p>
    <p style="margin:24px 0;">{button}</p>
    <p>{email_t("verification.fallbackText", locale=locale)}<br/><code>{link}</code></p>
    """
    html_body = _build_html_layout(
        email_t("verification.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t("verification.textBody", locale=locale, link=link, escape=False)
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("verification.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_password_reset_email(
    session: AsyncSession, user: User, token: str
) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url(f"/reset-password?token={token}")
    button = _cta_button(
        email_t("passwordReset.buttonLabel", locale=locale), link, accent
    )
    body = f"""
    <p>{email_t("passwordReset.greeting", locale=locale, name=name)}</p>
    <p>{email_t("passwordReset.body", locale=locale)}</p>
    <p style="margin:24px 0;">{button}</p>
    <p>{email_t("passwordReset.fallbackText", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("passwordReset.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t(
        "passwordReset.textBody", locale=locale, link=link, escape=False
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("passwordReset.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_initiative_added_email(
    session: AsyncSession, user: User, initiative_name: str
) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url("/initiatives")
    button = _cta_button(
        email_t("initiativeAdded.buttonLabel", locale=locale), link, accent
    )
    body = f"""
    <p>{email_t("initiativeAdded.greeting", locale=locale, name=name)}</p>
    <p>{email_t("initiativeAdded.body", locale=locale, initiativeName=initiative_name)}</p>
    <p style="margin:24px 0;">{button}</p>
    """
    html_body = _build_html_layout(
        email_t("initiativeAdded.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t(
        "initiativeAdded.textBody",
        locale=locale,
        initiativeName=initiative_name,
        link=link,
        escape=False,
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t(
            "initiativeAdded.subject",
            locale=locale,
            initiativeName=initiative_name,
            escape=False,
        ),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_project_added_to_initiative_email(
    session: AsyncSession,
    user: User,
    *,
    initiative_name: str,
    project_name: str,
    project_id: int,
) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url(f"/projects/{project_id}")
    button = _cta_button(
        email_t("projectAdded.buttonLabel", locale=locale), link, accent
    )
    body = f"""
    <p>{email_t("projectAdded.greeting", locale=locale, name=name)}</p>
    <p>{email_t("projectAdded.body", locale=locale, projectName=project_name, initiativeName=initiative_name)}</p>
    <p style="margin:24px 0;">{button}</p>
    """
    html_body = _build_html_layout(
        email_t("projectAdded.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t(
        "projectAdded.textBody",
        locale=locale,
        projectName=project_name,
        initiativeName=initiative_name,
        link=link,
        escape=False,
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t(
            "projectAdded.subject",
            locale=locale,
            initiativeName=initiative_name,
            escape=False,
        ),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_access_grant_email(
    session: AsyncSession,
    user: User,
    *,
    event: str,
    guild_name: str,
    access_level: str | None = None,
    requester: str | None = None,
) -> None:
    """Email a PAM access-grant lifecycle event.

    ``event`` is one of ``requested`` | ``approved`` | ``denied`` | ``revoked``.
    ``requester`` is only used for the ``requested`` event (sent to approvers).
    All link to the platform Access dashboard.
    """
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url("/settings/admin/access")
    button = _cta_button(
        email_t("accessGrant.buttonLabel", locale=locale), link, accent
    )
    level_label = ""
    if access_level:
        level_key = (
            "accessGrant.levelReadWrite"
            if access_level == "read_write"
            else "accessGrant.levelRead"
        )
        level_label = email_t(level_key, locale=locale)
    base = f"accessGrant.{event}"
    vars_ = {
        "guildName": guild_name,
        "level": level_label,
        "requester": requester or "",
    }
    body = f"""
    <p>{email_t("accessGrant.greeting", locale=locale, name=name)}</p>
    <p>{email_t(f"{base}.body", locale=locale, **vars_)}</p>
    <p style="margin:24px 0;">{button}</p>
    """
    html_body = _build_html_layout(
        email_t(f"{base}.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t(
        f"{base}.textBody", locale=locale, link=link, escape=False, **vars_
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t(
            f"{base}.subject", locale=locale, guildName=guild_name, escape=False
        ),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_task_assignment_digest_email(
    session: AsyncSession,
    user: User,
    assignments: Sequence[dict],
) -> None:
    if not assignments:
        return
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)

    def assignment_html(item: dict) -> str:
        # ``title`` is user-controlled and spliced into markup directly (not via
        # email_t), so escape it here.
        title = _html.escape(item.get("task_title") or "Task")
        project_name = item.get("project_name") or "a project"
        assigned_by = item.get("assigned_by_name")
        link = item.get("link")
        title_markup = (
            f'<a href="{link}"><strong>{title}</strong></a>'
            if link
            else f"<strong>{title}</strong>"
        )
        assigned_fragment = (
            f" ({email_t('taskAssignment.assignedBy', locale=locale, name=assigned_by)})"
            if assigned_by
            else ""
        )
        return f"<li>{title_markup} {email_t('taskAssignment.inProject', locale=locale, projectName=project_name)}{assigned_fragment}</li>"

    def assignment_text(item: dict) -> str:
        title = item.get("task_title") or "Task"
        project_name = item.get("project_name") or "a project"
        assigned_by = item.get("assigned_by_name")
        link = item.get("link")
        in_project = _strip_html(
            email_t(
                "taskAssignment.inProject",
                locale=locale,
                projectName=project_name,
                escape=False,
            )
        )
        line = f"- {title} {in_project}"
        if assigned_by:
            assigned = _strip_html(
                email_t(
                    "taskAssignment.assignedBy",
                    locale=locale,
                    name=assigned_by,
                    escape=False,
                )
            )
            line += f" ({assigned})"
        if link:
            line += f" -> {link}"
        return line

    items_html = "".join(assignment_html(item) for item in assignments)
    body = f"""
    <p>{email_t("taskAssignment.greeting", locale=locale, name=name)}</p>
    <p>{email_t("taskAssignment.body", locale=locale)}</p>
    <ul>{items_html}</ul>
    <p>{email_t("taskAssignment.footer", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("taskAssignment.title", locale=locale), body, accent, locale=locale
    )
    text_lines = [
        email_t("taskAssignment.textBody", locale=locale, escape=False),
        *(assignment_text(item) for item in assignments),
        email_t("taskAssignment.footer", locale=locale, escape=False),
    ]
    text_body = "\n".join(text_lines)
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("taskAssignment.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_mention_email(
    session: AsyncSession,
    user: User,
    *,
    subject: str,
    headline: str,
    body_text: str,
    link: str | None = None,
) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    if link:
        button = _cta_button(
            email_t("mention.buttonLabel", locale=locale), link, accent
        )
        body = f"""
    <p>{email_t("mention.greeting", locale=locale, name=name)}</p>
    <p>{body_text}</p>
    <p style="margin:24px 0;">{button}</p>
    """
    else:
        body = f"""
    <p>{email_t("mention.greeting", locale=locale, name=name)}</p>
    <p>{body_text}</p>
    """
    html_body = _build_html_layout(headline, body, accent, locale=locale)
    # body_text is an HTML fragment (locale strings bold {{vars}} via <strong>);
    # strip tags for the plain-text alternative.
    plain = _strip_html(body_text)
    if link:
        plain += f"\n\nView: {link}"
    await send_email(
        session,
        recipients=[user.email],
        subject=subject,
        html_body=html_body,
        text_body=plain,
        settings_obj=settings_obj,
    )


async def send_overdue_tasks_email(
    session: AsyncSession,
    user: User,
    tasks: Sequence[dict],
) -> None:
    if not tasks:
        return
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)

    def overdue_html(item: dict) -> str:
        # ``title`` is user-controlled and spliced into markup directly (not via
        # email_t), so escape it here.
        title = _html.escape(item.get("title") or "Task")
        project_name = item.get("project_name") or "a project"
        due_date = item.get("due_date") or "N/A"
        link = item.get("link")
        title_markup = (
            f'<a href="{link}"><strong>{title}</strong></a>'
            if link
            else f"<strong>{title}</strong>"
        )
        detail = email_t(
            "overdue.taskDetail",
            locale=locale,
            projectName=project_name,
            dueDate=due_date,
        )
        return f"<li>{title_markup} ({detail})</li>"

    def overdue_text(item: dict) -> str:
        title = item.get("title") or "Task"
        project_name = item.get("project_name") or "a project"
        due_date = item.get("due_date") or "N/A"
        link = item.get("link")
        detail = _strip_html(
            email_t(
                "overdue.taskDetail",
                locale=locale,
                projectName=project_name,
                dueDate=due_date,
                escape=False,
            )
        )
        line = f"- {title} ({detail})"
        if link:
            line += f" -> {link}"
        return line

    task_count = len(tasks)
    items_html = "".join(overdue_html(item) for item in tasks)
    body = f"""
    <p>{email_t("overdue.greeting", locale=locale, name=name)}</p>
    <p>{email_t("overdue.body", locale=locale, count=task_count)}</p>
    <ul>{items_html}</ul>
    <p>{email_t("overdue.footer", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("overdue.title", locale=locale), body, accent, locale=locale
    )
    text_lines = [
        email_t("overdue.textBody", locale=locale, count=task_count, escape=False),
        *(overdue_text(item) for item in tasks),
        email_t("overdue.footer", locale=locale, escape=False),
    ]
    text_body = "\n".join(text_lines)
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("overdue.subject", locale=locale, escape=False),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )
