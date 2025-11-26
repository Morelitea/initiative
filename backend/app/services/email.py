from __future__ import annotations

import asyncio
import logging
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Iterable, Sequence

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_config
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
    settings_obj = await app_settings_service.get_or_create_app_settings(session)
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


def _build_html_layout(title: str, body: str, accent_color: str) -> str:
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
        This message was sent by Initiative. If you weren't expecting it, you can ignore this email.
      </p>
      <p>
        <a href="{app_config.APP_URL}/profile/notifications">Update notification settings</a>.
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
        password=settings_obj.smtp_password,
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
        settings_obj = await app_settings_service.get_or_create_app_settings(session)
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
    html_body = _build_html_layout(
        "SMTP test email",
        "<p>This is a test email confirming SMTP settings are configured correctly.</p>",
        accent,
    )
    await send_email(
        session,
        recipients=[recipient],
        subject="SMTP configuration test",
        html_body=html_body,
        text_body="This is a test email confirming SMTP settings are configured correctly.",
        settings_obj=settings_obj,
    )


def _frontend_url(path: str) -> str:
    base = app_config.APP_URL.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


async def send_verification_email(session: AsyncSession, user: User, token: str) -> None:
    settings_obj, accent = await _email_context(session)
    link = _frontend_url(f"/verify-email?token={token}")
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>Confirm your email to finish setting up your Initiative account.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:{accent};color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">Verify email</a>
    </p>
    <p>If the button doesn't work, copy and paste this link into your browser:<br/><code>{link}</code></p>
    """
    html_body = _build_html_layout("Verify your email", body, accent)
    text_body = f"Confirm your Initiative account by visiting {link}"
    await send_email(
        session,
        recipients=[user.email],
        subject="Verify your Initiative account",
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_password_reset_email(session: AsyncSession, user: User, token: str) -> None:
    settings_obj, accent = await _email_context(session)
    link = _frontend_url(f"/reset-password?token={token}")
    body = f"""
    <p>Hello {user.full_name or user.email},</p>
    <p>We received a request to reset your Initiative password.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:{accent};color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">Reset password</a>
    </p>
    <p>If you didn't request this, you can ignore this email. The link expires soon.</p>
    """
    html_body = _build_html_layout("Reset your password", body, accent)
    text_body = f"Reset your Initiative password by visiting {link}"
    await send_email(
        session,
        recipients=[user.email],
        subject="Reset your Initiative password",
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )


async def send_initiative_added_email(session: AsyncSession, user: User, initiative_name: str) -> None:
    settings_obj, accent = await _email_context(session)
    link = _frontend_url("/initiatives")
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>You have been added to the <strong>{initiative_name}</strong> initiative.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:{accent};color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">View initiatives</a>
    </p>
    """
    html_body = _build_html_layout("You joined a new initiative", body, accent)
    text_body = f"You have been added to the {initiative_name} initiative. Visit {link} to view it."
    await send_email(
        session,
        recipients=[user.email],
        subject=f"Added to initiative {initiative_name}",
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
    link = _frontend_url(f"/projects/{project_id}")
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>A new project, <strong>{project_name}</strong>, was added to the <strong>{initiative_name}</strong> initiative.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:{accent};color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;display:inline-block;">Open project</a>
    </p>
    """
    html_body = _build_html_layout("New project in your initiative", body, accent)
    text_body = (
        f"A new project, {project_name}, was added to the {initiative_name} initiative. View it at {link}."
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=f"New project in {initiative_name}",
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
    items_html = "".join(
        f"<li><strong>{item['task_title']}</strong> in {item['project_name']} (assigned by {item['assigned_by_name']})</li>"
        for item in assignments
    )
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>Here is your hourly summary of tasks assigned to you:</p>
    <ul>{items_html}</ul>
    <p>Visit Initiative to review the tasks.</p>
    """
    html_body = _build_html_layout("Task assignment summary", body, accent)
    text_lines = [
        "Here is your hourly summary of tasks assigned to you:",
        *(f"- {item['task_title']} in {item['project_name']} (assigned by {item['assigned_by_name']})" for item in assignments),
        "Visit Initiative to review the tasks.",
    ]
    text_body = "\n".join(text_lines)
    await send_email(
        session,
        recipients=[user.email],
        subject="New tasks assigned to you",
        html_body=html_body,
        text_body=text_body,
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
    items_html = "".join(
        f"<li><strong>{item['title']}</strong> (project: {item['project_name']}, due {item['due_date']})</li>"
        for item in tasks
    )
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>You have {len(tasks)} overdue task(s):</p>
    <ul>{items_html}</ul>
    <p>Visit Initiative to get back on track.</p>
    """
    html_body = _build_html_layout("Overdue tasks reminder", body, accent)
    text_lines = [
        f"You have {len(tasks)} overdue task(s):",
        *(f"- {item['title']} (project: {item['project_name']}, due {item['due_date']})" for item in tasks),
        "Visit Initiative to get back on track.",
    ]
    text_body = "\n".join(text_lines)
    await send_email(
        session,
        recipients=[user.email],
        subject="Overdue tasks reminder",
        html_body=html_body,
        text_body=text_body,
        settings_obj=settings_obj,
    )
