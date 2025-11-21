import hashlib
import hmac
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User, UserRole
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserRead
from app.services import app_settings as app_settings_service

router = APIRouter()

STATE_TTL_SECONDS = 600
_oidc_metadata_cache: dict[str, dict[str, Any]] = {}


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserCreate, session: SessionDep) -> User:
    statement = select(User).where(User.email == user_in.email)
    existing = await session.exec(statement)
    if existing.one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    app_settings = await app_settings_service.get_or_create_app_settings(session)

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        role=UserRole.member,
        is_active=app_settings_service.is_email_auto_approved(user_in.email, app_settings),
    )

    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:  # pragma: no cover
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to create user") from exc

    await session.refresh(user)
    return user


@router.post("/token", response_model=Token)
async def login_access_token(
    session: SessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Token:
    statement = select(User).where(User.email == form_data.username)
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect email or password")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token)


def _generate_state() -> str:
    timestamp = str(int(time.time()))
    signature = hmac.new(settings.SECRET_KEY.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"


def _validate_state(value: str | None) -> bool:
    if not value:
        return False
    try:
        ts_str, signature = value.split(".", 1)
    except ValueError:
        return False
    expected = hmac.new(settings.SECRET_KEY.encode(), ts_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    return int(time.time()) - ts <= STATE_TTL_SECONDS


def _backend_redirect_uri() -> str:
    base = settings.APP_URL.rstrip("/")
    return f"{base}{settings.API_V1_STR}/auth/oidc/callback"


def _frontend_redirect_uri() -> str:
    base = settings.APP_URL.rstrip("/")
    return f"{base}/oidc/callback"


async def _fetch_oidc_metadata(discovery_url: str) -> dict[str, Any]:
    if discovery_url in _oidc_metadata_cache:
        return _oidc_metadata_cache[discovery_url]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(discovery_url)
        resp.raise_for_status()
        metadata = resp.json()
    _oidc_metadata_cache[discovery_url] = metadata
    return metadata


async def _get_oidc_runtime_config(session: SessionDep) -> tuple[Any, dict[str, Any]]:
    app_settings = await app_settings_service.get_or_create_app_settings(session)
    if not (
        app_settings.oidc_enabled
        and app_settings.oidc_discovery_url
        and app_settings.oidc_client_id
        and app_settings.oidc_client_secret
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OIDC is not enabled")

    metadata = await _fetch_oidc_metadata(app_settings.oidc_discovery_url)
    required = ["authorization_endpoint", "token_endpoint"]
    for key in required:
        if key not in metadata:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="OIDC metadata incomplete")
    return app_settings, metadata


@router.get("/oidc/status")
async def oidc_status(request: Request, session: SessionDep) -> dict[str, Any]:
    app_settings = await app_settings_service.get_or_create_app_settings(session)
    enabled = bool(
        app_settings.oidc_enabled
        and app_settings.oidc_discovery_url
        and app_settings.oidc_client_id
        and app_settings.oidc_client_secret
    )
    login_url = None
    provider_name = None
    if enabled:
        login_url = f"{settings.API_V1_STR}/auth/oidc/login"
        provider_name = app_settings.oidc_provider_name
    return {"enabled": enabled, "login_url": login_url, "provider_name": provider_name}


@router.get("/oidc/login")
async def oidc_login(session: SessionDep) -> RedirectResponse:
    app_settings, metadata = await _get_oidc_runtime_config(session)
    state = _generate_state()
    params = {
        "client_id": app_settings.oidc_client_id,
        "response_type": "code",
        "scope": " ".join(app_settings.oidc_scopes or ["openid"]),
        "redirect_uri": _backend_redirect_uri(),
        "state": state,
    }
    authorize_url = f"{metadata['authorization_endpoint']}?{urlencode(params)}"
    return RedirectResponse(authorize_url)


@router.get("/oidc/callback")
async def oidc_callback(
    session: SessionDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing authorization code")
    if not _validate_state(state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter")

    app_settings, metadata = await _get_oidc_runtime_config(session)
    token_payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _backend_redirect_uri(),
        "client_id": app_settings.oidc_client_id,
        "client_secret": app_settings.oidc_client_secret,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        token_resp = await client.post(metadata["token_endpoint"], data=token_payload)
        try:
            token_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OIDC token request failed") from exc
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OIDC token missing access_token")

        userinfo_endpoint = metadata.get("userinfo_endpoint")
        if not userinfo_endpoint:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OIDC userinfo endpoint missing")
        userinfo_resp = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        try:
            userinfo_resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OIDC userinfo request failed") from exc
        profile = userinfo_resp.json()

    email = profile.get("email")
    if not email:
        sub = profile.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OIDC profile missing subject")
        email = f"{sub}@oidc.local"
    full_name = profile.get("name") or profile.get("preferred_username") or email

    statement = select(User).where(User.email == email)
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user:
        random_password = secrets.token_urlsafe(32)
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=get_password_hash(random_password),
            role=UserRole.member,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    else:
        if not user.is_active:
            user.is_active = True
            session.add(user)
            await session.commit()
            await session.refresh(user)

    app_token = create_access_token(subject=str(user.id))

    redirect_params = {"token": app_token}
    redirect_url = f"{_frontend_redirect_uri()}?{urlencode(redirect_params)}"
    return RedirectResponse(redirect_url)
