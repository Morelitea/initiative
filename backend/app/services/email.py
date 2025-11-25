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


def _build_html_layout(title: str, body: str) -> str:
    return f"""\
<html>
  <body style="font-family: Arial, Helvetica, sans-serif; color:#0f172a; background-color:#f8fafc; padding:24px;">
    <div style="max-width:520px;margin:0 auto;background-color:#ffffff;padding:24px;border-radius:12px;border:1px solid #e2e8f0;">
      <h2 style="margin-top:0;font-size:22px;color:#0f172a;">{title}</h2>
      <div style="font-size:15px;line-height:1.5;color:#334155;">{body}</div>
      <p style="font-size:12px;color:#94a3b8;margin-top:32px;">
        This message was sent by Initiative. If you weren't expecting it, you can ignore this email.
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
) -> None:
    if not recipients:
        raise ValueError("At least one recipient email is required")
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
    html_body = _build_html_layout(
        "SMTP test email",
        "<p>This is a test email confirming SMTP settings are configured correctly.</p>",
    )
    await send_email(
        session,
        recipients=[recipient],
        subject="SMTP configuration test",
        html_body=html_body,
        text_body="This is a test email confirming SMTP settings are configured correctly.",
    )


def _frontend_url(path: str) -> str:
    base = app_config.APP_URL.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"


async def send_verification_email(session: AsyncSession, user: User, token: str) -> None:
    link = _frontend_url(f"/verify-email?token={token}")
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>Confirm your email to finish setting up your Initiative account.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:#2563eb;color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;">Verify email</a>
    </p>
    <p>If the button doesn't work, copy and paste this link into your browser:<br/><code>{link}</code></p>
    """
    html_body = _build_html_layout("Verify your email", body)
    text_body = f"Confirm your Initiative account by visiting {link}"
    await send_email(session, recipients=[user.email], subject="Verify your Initiative account", html_body=html_body, text_body=text_body)


async def send_password_reset_email(session: AsyncSession, user: User, token: str) -> None:
    link = _frontend_url(f"/reset-password?token={token}")
    body = f"""
    <p>Hello {user.full_name or user.email},</p>
    <p>We received a request to reset your Initiative password.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:#2563eb;color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;">Reset password</a>
    </p>
    <p>If you didn't request this, you can ignore this email. The link expires soon.</p>
    """
    html_body = _build_html_layout("Reset your password", body)
    text_body = f"Reset your Initiative password by visiting {link}"
    await send_email(session, recipients=[user.email], subject="Reset your Initiative password", html_body=html_body, text_body=text_body)


async def send_initiative_added_email(session: AsyncSession, user: User, initiative_name: str) -> None:
    link = _frontend_url("/initiatives")
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>You have been added to the <strong>{initiative_name}</strong> initiative.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:#2563eb;color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;">View initiatives</a>
    </p>
    """
    html_body = _build_html_layout("You joined a new initiative", body)
    text_body = f"You have been added to the {initiative_name} initiative. Visit {link} to view it."
    await send_email(session, recipients=[user.email], subject=f"Added to initiative {initiative_name}", html_body=html_body, text_body=text_body)


async def send_project_added_to_initiative_email(
    session: AsyncSession,
    user: User,
    *,
    initiative_name: str,
    project_name: str,
    project_id: int,
) -> None:
    link = _frontend_url(f"/projects/{project_id}")
    body = f"""
    <p>Hi {user.full_name or user.email},</p>
    <p>A new project, <strong>{project_name}</strong>, was added to the <strong>{initiative_name}</strong> initiative.</p>
    <p style="margin:24px 0;">
      <a href="{link}" style="background-color:#2563eb;color:#ffffff;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:600;">Open project</a>
    </p>
    """
    html_body = _build_html_layout("New project in your initiative", body)
    text_body = (
        f"A new project, {project_name}, was added to the {initiative_name} initiative. View it at {link}."
    )
    await send_email(
        session,
        recipients=[user.email],
        subject=f"New project in {initiative_name}",
        html_body=html_body,
        text_body=text_body,
    )


async def send_task_assignment_digest_email(
    session: AsyncSession,
    user: User,
    assignments: Sequence[dict],
) -> None:
    if not assignments:
        return
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
    html_body = _build_html_layout("Task assignment summary", body)
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
    )


async def send_overdue_tasks_email(
    session: AsyncSession,
    user: User,
    tasks: Sequence[dict],
) -> None:
    if not tasks:
        return
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
    html_body = _build_html_layout("Overdue tasks reminder", body)
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
    )
