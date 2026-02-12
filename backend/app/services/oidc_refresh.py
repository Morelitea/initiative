from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.encryption import decrypt_token, encrypt_token
from app.db.session import AdminSessionLocal
from app.models.user import User
from app.services import app_settings as app_settings_service
from app.services.oidc_sync import extract_claim_values, sync_oidc_assignments

logger = logging.getLogger(__name__)

OIDC_SYNC_POLL_SECONDS = 300  # 5 minutes
_SYNC_INTERVAL = timedelta(minutes=15)


async def _fetch_oidc_metadata(issuer_url: str) -> dict:
    normalized = issuer_url.rstrip("/")
    well_known_suffix = "/.well-known/openid-configuration"
    if normalized.endswith(well_known_suffix):
        normalized = normalized[: -len(well_known_suffix)]
    discovery_url = f"{normalized}{well_known_suffix}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        return resp.json()


async def _refresh_and_sync_user(
    session: AsyncSession,
    user: User,
    *,
    token_endpoint: str,
    userinfo_endpoint: str,
    client_id: str,
    client_secret: str,
    claim_path: str,
) -> bool:
    """Refresh a single user's token and sync claims. Returns True on success."""
    try:
        refresh_token = decrypt_token(user.oidc_refresh_token_encrypted)
    except Exception:
        logger.warning("Failed to decrypt refresh token for user %s; clearing", user.email)
        user.oidc_refresh_token_encrypted = None
        session.add(user)
        await session.commit()
        return False

    token_payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.post(token_endpoint, data=token_payload)
            if token_resp.status_code in (400, 401):
                logger.warning(
                    "Refresh token revoked/expired for user %s (HTTP %d); clearing",
                    user.email,
                    token_resp.status_code,
                )
                user.oidc_refresh_token_encrypted = None
                session.add(user)
                await session.commit()
                return False
            token_resp.raise_for_status()
            token_data = token_resp.json()

            access_token = token_data.get("access_token")
            if not access_token:
                logger.warning("No access_token in refresh response for user %s", user.email)
                return False

            # Handle token rotation
            new_refresh = token_data.get("refresh_token")
            if new_refresh:
                user.oidc_refresh_token_encrypted = encrypt_token(new_refresh)

            # Fetch userinfo
            userinfo_resp = await client.get(
                userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_resp.raise_for_status()
            profile = userinfo_resp.json()
    except httpx.HTTPStatusError:
        logger.exception("HTTP error during OIDC refresh for user %s", user.email)
        return False
    except httpx.RequestError:
        logger.exception("Network error during OIDC refresh for user %s", user.email)
        return False

    # Decode id_token claims if present
    id_token_claims = None
    raw_id_token = token_data.get("id_token")
    if raw_id_token:
        try:
            import base64
            import json as _json

            parts = raw_id_token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1]
                payload_b64 += "=" * (-len(payload_b64) % 4)
                id_token_claims = _json.loads(base64.urlsafe_b64decode(payload_b64))
        except Exception:
            pass

    claim_values = extract_claim_values(profile, id_token_claims, claim_path)
    sync_result = await sync_oidc_assignments(
        session,
        user_id=user.id,
        claim_values=claim_values,
    )
    logger.info(
        "OIDC refresh sync for %s: +%d/~%d/-%d guilds, +%d/~%d/-%d initiatives",
        user.email,
        len(sync_result.guilds_added),
        len(sync_result.guilds_updated),
        len(sync_result.guilds_removed),
        len(sync_result.initiatives_added),
        len(sync_result.initiatives_updated),
        len(sync_result.initiatives_removed),
    )

    user.oidc_last_synced_at = datetime.now(timezone.utc)
    session.add(user)
    await session.commit()
    return True


async def process_oidc_refresh_sync() -> None:
    async with AdminSessionLocal() as session:
        app_settings = await app_settings_service.get_app_settings(session)

        if not app_settings.oidc_enabled:
            return
        claim_path = getattr(app_settings, "oidc_role_claim_path", None)
        if not claim_path:
            return
        if not (app_settings.oidc_issuer and app_settings.oidc_client_id and app_settings.oidc_client_secret):
            return

        try:
            metadata = await _fetch_oidc_metadata(app_settings.oidc_issuer)
        except Exception:
            logger.exception("Failed to fetch OIDC metadata for background sync")
            return

        token_endpoint = metadata.get("token_endpoint")
        userinfo_endpoint = metadata.get("userinfo_endpoint")
        if not token_endpoint or not userinfo_endpoint:
            logger.warning("OIDC metadata missing token/userinfo endpoint; skipping sync")
            return

        cutoff = datetime.now(timezone.utc) - _SYNC_INTERVAL
        stmt = select(User).where(
            User.oidc_refresh_token_encrypted.is_not(None),
            (User.oidc_last_synced_at < cutoff) | User.oidc_last_synced_at.is_(None),
        )
        result = await session.exec(stmt)
        users = result.all()

        if not users:
            logger.debug("oidc-refresh-sync: no users due for sync")
            return

        succeeded = 0
        revoked = 0
        for user in users:
            ok = await _refresh_and_sync_user(
                session,
                user,
                token_endpoint=token_endpoint,
                userinfo_endpoint=userinfo_endpoint,
                client_id=app_settings.oidc_client_id,
                client_secret=app_settings.oidc_client_secret,
                claim_path=claim_path,
            )
            if ok:
                succeeded += 1
            elif user.oidc_refresh_token_encrypted is None:
                revoked += 1

        logger.info(
            "OIDC refresh sync: processed %d users, %d succeeded, %d token(s) revoked",
            len(users),
            succeeded,
            revoked,
        )
