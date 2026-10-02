"""A vendor's own flow for making an app's vendor client.

An app's manifest may declare ``vendor.setup``: a flow at the vendor that
creates the client the app's connections use on this deployment, and answers
with its values. Initiative runs it from the operator's browser and writes the
answers into the registration's vendor values through the write the settings
form uses, so none is typed or copied.

``github_app_manifest`` is the one flow. GitHub creates a GitHub App from a
manifest the browser posts to it, sends the operator back with a code, and
exchanges that code once for the new app's id, slug, client id and secret,
webhook secret and private key.

* :func:`start` builds the manifest, the app's own declaration with the
  addresses Initiative already knows filled in, and a state for the operator's
  browser to carry to GitHub and back.
* :func:`complete` checks the state, exchanges the code, and writes each value
  to the vendor field the manifest names.

The state is an ``auth_challenges`` row naming the operator who started the
setup, answered by the registration it is for. It lasts an hour and the first
completion spends it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Optional
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status as http_status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.messages import AppServiceMessages
from app.models.platform.app_service_registration import AppServiceRegistration
from app.services.auth import challenges as challenge_service
from app.services.marketplace import registrations as registrations_service
from app.services.marketplace import vendor_values as vendor_values_service
from app.services.marketplace.service_apps import GITHUB_APP_MANIFEST
from app.services.safe_http import ResponseTooLargeError, request_public_target
from app.services.tenant import app_connection_flows as flows_service
from app.services.webhook_target_url import (
    WebhookTargetUrlError,
    WebhookTargetUrlPrivateError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "STATE_TTL",
    "VendorSetupStart",
    "complete",
    "redirect_url",
    "setup_kind",
    "start",
]

#: How long an operator has to confirm the app on GitHub and come back.
STATE_TTL = timedelta(hours=1)

GITHUB_URL = "https://github.com"
GITHUB_API_URL = "https://api.github.com"
#: What the conversion may take and answer with.
TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 64 * 1024

#: A GitHub account name: letters, digits and hyphens, at most 39.
_ORGANIZATION_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)
_MAX_ORGANIZATION = 39
#: What a code GitHub returns is made of.
_CODE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)
_MAX_CODE = 128

#: Injectable for tests: the transport the conversion uses.
http_transport: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class VendorSetupStart:
    """Where the operator's browser posts the manifest, and what it carries."""

    #: The page at GitHub that takes the manifest, without the state.
    action: str
    #: The manifest, as the JSON text the form field holds.
    manifest: str
    state: str


def setup_kind(definition: Mapping[str, Any] | None) -> Optional[str]:
    """The vendor setup flow a manifest declares, when it is one this build
    runs."""
    setup = ((definition or {}).get("vendor") or {}).get("setup")
    if isinstance(setup, dict) and setup.get("kind") == GITHUB_APP_MANIFEST:
        return GITHUB_APP_MANIFEST
    return None


def redirect_url(registration_id: int) -> str:
    """The settings page GitHub sends the operator back to with its code."""
    return (
        f"{settings.APP_URL.rstrip('/')}/settings/platform/integrations"
        f"/vendor-setup/{registration_id}"
    )


async def _setup_of(
    session: AsyncSession, row: AppServiceRegistration
) -> dict[str, Any]:
    definition = (
        await vendor_values_service.listing_definitions(session, [row.listing_uid])
    ).get(row.listing_uid or "")
    if setup_kind(definition) is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=AppServiceMessages.VENDOR_SETUP_UNAVAILABLE,
        )
    return (definition or {})["vendor"]["setup"]


def _organization(value: Optional[str]) -> Optional[str]:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if (
        len(cleaned) > _MAX_ORGANIZATION
        or any(char not in _ORGANIZATION_CHARS for char in cleaned)
        or cleaned.startswith("-")
    ):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=AppServiceMessages.VENDOR_SETUP_INVALID_ORGANIZATION,
        )
    return cleaned


async def start(
    session: AsyncSession,
    registration_id: int,
    *,
    organization: Optional[str],
    actor_user_id: int,
) -> VendorSetupStart:
    """Build the manifest for the app's GitHub App, owned by ``organization``
    or by the operator's own account, and open the state that brings the
    operator back."""
    row = await registrations_service.get_registration(session, registration_id)
    setup = await _setup_of(session, row)
    owner = _organization(organization)
    action = (
        f"{GITHUB_URL}/organizations/{owner}/settings/apps/new"
        if owner
        else f"{GITHUB_URL}/settings/apps/new"
    )
    manifest = {
        **setup["app"],
        "redirect_url": redirect_url(row.id),
        "callback_urls": [flows_service.callback_url()],
        "setup_url": flows_service.setup_url(),
        "hook_attributes": {
            "url": flows_service.webhook_url(row.public_id),
            "active": True,
        },
    }
    issued = await challenge_service.create(
        session,
        user_id=actor_user_id,
        purpose=challenge_service.ChallengePurpose.app_vendor_setup,
        answer=str(row.id),
        ttl=STATE_TTL,
    )
    await session.commit()
    return VendorSetupStart(
        action=action, manifest=json.dumps(manifest), state=issued.value
    )


def _expired() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_400_BAD_REQUEST,
        detail=AppServiceMessages.VENDOR_SETUP_EXPIRED,
    )


def _failed() -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_502_BAD_GATEWAY,
        detail=AppServiceMessages.VENDOR_SETUP_FAILED,
    )


async def _spend_state(
    session: AsyncSession, *, registration_id: int, state: str, actor_user_id: int
) -> None:
    """Spend the state, and refuse one this operator did not open for this
    registration. Presenting it spends it either way."""
    challenge = await challenge_service.claim_attempt(
        session,
        value=state,
        purposes=[challenge_service.ChallengePurpose.app_vendor_setup],
    )
    spent = challenge is not None and await challenge_service.consume(
        session, challenge
    )
    await session.commit()
    if not (
        challenge is not None
        and spent
        and challenge.user_id == actor_user_id
        and challenge_service.answered_by(
            challenge, value=state, answer=str(registration_id)
        )
    ):
        raise _expired()


async def _convert(code: str) -> dict[str, Any]:
    """GitHub's answer for the code: the new app's values."""
    if not code or len(code) > _MAX_CODE or any(c not in _CODE_CHARS for c in code):
        raise _failed()
    url = f"{GITHUB_API_URL}/app-manifests/{quote(code, safe='')}/conversions"
    try:
        response = await request_public_target(
            "POST",
            url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=TIMEOUT_SECONDS,
            transport=http_transport,
            max_bytes=MAX_RESPONSE_BYTES,
        )
        body = response.json() if response.status_code < 400 else None
    except (
        httpx.HTTPError,
        ResponseTooLargeError,
        WebhookTargetUrlError,
        WebhookTargetUrlPrivateError,
        ValueError,
    ) as exc:
        logger.warning("app services: the GitHub App conversion failed (%s)", exc)
        raise _failed() from exc
    if not isinstance(body, dict):
        logger.warning(
            "app services: GitHub answered the conversion with %s",
            response.status_code,
        )
        raise _failed()
    return body


async def complete(
    session: AsyncSession,
    registration_id: int,
    *,
    code: str,
    state: str,
    actor_user_id: int,
) -> AppServiceRegistration:
    """Finish the setup GitHub sent the operator back from: exchange its code,
    and write each value GitHub answers with to the vendor field the manifest
    names. A value GitHub leaves out is left as it was."""
    await _spend_state(
        session,
        registration_id=registration_id,
        state=state,
        actor_user_id=actor_user_id,
    )
    row = await registrations_service.get_registration(session, registration_id)
    setup = await _setup_of(session, row)
    answer = await _convert(code)
    values: dict[str, Optional[str]] = {}
    for key, name in setup["values"].items():
        value = answer.get(name)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            if str(value).strip():
                values[key] = str(value)
    if not values:
        raise _failed()
    return await registrations_service.update_registration(
        session, registration_id, vendor_values=values, actor_user_id=actor_user_id
    )
