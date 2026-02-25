from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Sequence

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
from app.core.email_i18n import email_t
from app.core.encryption import decrypt_token
from app.models.app_setting import AppSetting
from app.models.user import User
from app.services import app_settings as app_settings_service

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


BRAND_LOGO_SVG = """
<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 438 471' width='32' height='34' fill='currentColor'>
  <path
      d="M218.82 470.128a20.242 20.242 0 0 1-8.27-1.639L14.387 384.823C5.724 381.128 0 371.834 0 361.464v-238.72c0-.652.023-1.3.067-1.943.298-4.21 1.546-8.282 3.62-11.81 1.54-2.615 3.524-4.918 5.884-6.758a21.969 21.969 0 0 1 2.994-1.966l196.161-97.74C211.98.753 215.431-.054 218.82.002c3.39-.057 6.84.751 10.094 2.523l196.161 97.741a21.969 21.969 0 0 1 2.994 1.966c2.36 1.84 4.345 4.143 5.885 6.757 2.073 3.53 3.321 7.601 3.62 11.811.043.643.066 1.291.066 1.942v238.721c0 10.37-5.724 19.664-14.388 23.36l-196.16 83.665a20.242 20.242 0 0 1-8.272 1.64ZM137.623 188.27a24.668 24.668 0 0 1-22.62 1.39l-70.298-31.046v185.628l120.247 51.288V243.097a53.369 53.369 0 0 1 27.81-46.853 53.367 53.367 0 0 1 52.116 0l.5.28a53.369 53.369 0 0 1 27.31 46.573V395.53l120.247-51.288V158.613l-70.648 31.25a24.67 24.67 0 0 1-22.634-1.383l-.186-.112a24.669 24.669 0 0 1 2.616-43.713l56.324-25.09L218.82 52.643 79.233 119.565l55.934 24.884a24.668 24.668 0 0 1 2.626 43.718l-.17.102Z"
      fill="currentColor"
    />
    <ellipse
      cx="257.233"
      cy="209.745"
      rx="52.118"
      ry="36.171"
      transform="matrix(.76806 0 0 1.13407 21.073 -109.942)"
      fill="currentColor"
    />
    <path
      d="m137.623 188.27.17-.103a24.669 24.669 0 0 0-2.626-43.718l-55.934-24.884L218.82 52.643l139.587 66.922-56.324 25.09a24.67 24.67 0 0 0-2.616 43.713l.186.112a24.67 24.67 0 0 0 22.634 1.383l70.648-31.25v185.628L272.688 395.53V243.097a53.369 53.369 0 0 0-27.31-46.574l-.5-.279a53.367 53.367 0 0 0-52.116 0l-.5.28a53.369 53.369 0 0 0-27.31 46.573V395.53L44.705 344.241V158.613l70.298 31.045a24.668 24.668 0 0 0 22.62-1.389Zm81.02-101.366c-22.093 0-40.03 18.381-40.03 41.021s17.937 41.021 40.03 41.021c22.092 0 40.028-18.38 40.028-41.02 0-22.64-17.936-41.022-40.029-41.022Z"
      opacity=".25"
      fill="currentColor"
    />
  </svg>
</svg>
""".strip()


def _build_html_layout(title: str, body: str, accent_color: str, locale: str = "en") -> str:
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
        <div style="width:48px;height:48px;border-radius:14px;color:{accent_color};display:flex;align-items:center;justify-content:center;">
          <a href="{app_config.APP_URL}">{BRAND_LOGO_SVG}</a>
        </div>
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
        <a href="{app_config.APP_URL}/profile/notifications">{update_link_text}</a>.
      </p>
    </div>
  </body>
</html>
"""


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


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
        password=decrypt_token(settings_obj.smtp_password_encrypted) if settings_obj.smtp_password_encrypted else None,
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
                logger.debug("STARTTLS not available for SMTP host %s:%s", config.host, config.port)
            _send_via_client(client, config, message)


def _send_via_client(client: smtplib.SMTP, config: SMTPConfig, message: EmailMessage) -> None:
    if config.username and config.password:
        client.login(config.username, config.password)
    client.send_message(message)


def _user_locale(user: User) -> str:
    return getattr(user, "locale", None) or "en"


def _display_name(user: User) -> str:
    return user.full_name or user.email


def _cta_button(label: str, link: str, accent: str) -> str:
    return (
        f'<a href="{link}" style="background-color:{accent};color:#ffffff;'
        f'padding:12px 18px;border-radius:8px;text-decoration:none;'
        f'font-weight:600;display:inline-block;">{label}</a>'
    )


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
    message.add_alternative(html_body, subtype="html")
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
        subject=email_t("test.subject", locale=locale),
        html_body=html_body,
        text_body=email_t("test.body", locale=locale),
        settings_obj=settings_obj,
    )


def _frontend_url(path: str) -> str:
    base = app_config.APP_URL.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


async def send_verification_email(session: AsyncSession, user: User, token: str) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url(f"/verify-email?token={token}")
    button = _cta_button(email_t("verification.buttonLabel", locale=locale), link, accent)
    body = f"""
    <p>{email_t("verification.greeting", locale=locale, name=name)}</p>
    <p>{email_t("verification.body", locale=locale)}</p>
    <p style="margin:24px 0;">{button}</p>
    <p>{email_t("verification.fallbackText", locale=locale)}<br/><code>{link}</code></p>
    """
    html_body = _build_html_layout(
        email_t("verification.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t("verification.textBody", locale=locale, link=link)
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("verification.subject", locale=locale),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_password_reset_email(session: AsyncSession, user: User, token: str) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url(f"/reset-password?token={token}")
    button = _cta_button(email_t("passwordReset.buttonLabel", locale=locale), link, accent)
    body = f"""
    <p>{email_t("passwordReset.greeting", locale=locale, name=name)}</p>
    <p>{email_t("passwordReset.body", locale=locale)}</p>
    <p style="margin:24px 0;">{button}</p>
    <p>{email_t("passwordReset.fallbackText", locale=locale)}</p>
    """
    html_body = _build_html_layout(
        email_t("passwordReset.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t("passwordReset.textBody", locale=locale, link=link)
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("passwordReset.subject", locale=locale),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_initiative_added_email(session: AsyncSession, user: User, initiative_name: str) -> None:
    settings_obj, accent = await _email_context(session)
    locale = _user_locale(user)
    name = _display_name(user)
    link = _frontend_url("/initiatives")
    button = _cta_button(email_t("initiativeAdded.buttonLabel", locale=locale), link, accent)
    body = f"""
    <p>{email_t("initiativeAdded.greeting", locale=locale, name=name)}</p>
    <p>{email_t("initiativeAdded.body", locale=locale, initiativeName=initiative_name)}</p>
    <p style="margin:24px 0;">{button}</p>
    """
    html_body = _build_html_layout(
        email_t("initiativeAdded.title", locale=locale), body, accent, locale=locale
    )
    text_body = email_t(
        "initiativeAdded.textBody", locale=locale, initiativeName=initiative_name, link=link
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("initiativeAdded.subject", locale=locale, initiativeName=initiative_name),
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
    button = _cta_button(email_t("projectAdded.buttonLabel", locale=locale), link, accent)
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
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("projectAdded.subject", locale=locale, initiativeName=initiative_name),
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
        title = item.get("task_title") or "Task"
        project_name = item.get("project_name") or "a project"
        assigned_by = item.get("assigned_by_name")
        link = item.get("link")
        title_markup = f'<a href="{link}"><strong>{title}</strong></a>' if link else f"<strong>{title}</strong>"
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
        line = f"- {title} {email_t('taskAssignment.inProject', locale=locale, projectName=project_name)}"
        if assigned_by:
            line += f" ({email_t('taskAssignment.assignedBy', locale=locale, name=assigned_by)})"
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
        email_t("taskAssignment.textBody", locale=locale),
        *(assignment_text(item) for item in assignments),
        email_t("taskAssignment.footer", locale=locale),
    ]
    text_body = "\n".join(text_lines)
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("taskAssignment.subject", locale=locale),
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
        button = _cta_button(email_t("mention.buttonLabel", locale=locale), link, accent)
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
    plain = f"{body_text}"
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
        title = item.get("title") or "Task"
        project_name = item.get("project_name") or "a project"
        due_date = item.get("due_date") or "N/A"
        link = item.get("link")
        title_markup = f'<a href="{link}"><strong>{title}</strong></a>' if link else f"<strong>{title}</strong>"
        detail = email_t("overdue.taskDetail", locale=locale, projectName=project_name, dueDate=due_date)
        return f"<li>{title_markup} ({detail})</li>"

    def overdue_text(item: dict) -> str:
        title = item.get("title") or "Task"
        project_name = item.get("project_name") or "a project"
        due_date = item.get("due_date") or "N/A"
        link = item.get("link")
        detail = email_t("overdue.taskDetail", locale=locale, projectName=project_name, dueDate=due_date)
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
        email_t("overdue.textBody", locale=locale, count=task_count),
        *(overdue_text(item) for item in tasks),
        email_t("overdue.footer", locale=locale),
    ]
    text_body = "\n".join(text_lines)
    await send_email(
        session,
        recipients=[user.email],
        subject=email_t("overdue.subject", locale=locale),
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )
