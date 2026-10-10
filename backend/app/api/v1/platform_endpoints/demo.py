"""The demo deployment's public route: opening a demo link."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import SystemSessionDep
from app.api.v1.platform_endpoints.session_opening import open_session
from app.core import audit_context
from app.core.config import settings
from app.core.messages import DemoMessages
from app.demo import copies
from app.schemas.platform.demo import DemoRedeem, DemoRedemption
from app.services import captcha as captcha_service

router = APIRouter()


@router.post("/redeem", response_model=DemoRedemption)
async def redeem_demo_link(
    request: Request,
    response: Response,
    payload: DemoRedeem,
    session: SystemSessionDep,
) -> DemoRedemption:
    """Open a demo link: a new account in a new copy of the link's pitch,
    signed in for as long as the copy lasts. Answers 503 ``DEMO_BUSY`` when no
    copy is free, and 404 everywhere but the demo deployment."""
    if not settings.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DemoMessages.DEMO_LINK_NOT_FOUND,
        )
    await captcha_service.verify_or_raise(
        payload.captcha_token, remote_ip=audit_context.client_ip()
    )
    try:
        opened = await copies.redeem(session, payload.token)
    except copies.LinkNotLive:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=DemoMessages.DEMO_LINK_NOT_FOUND,
        )
    except copies.PoolBusy:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DemoMessages.DEMO_BUSY,
            headers={"Retry-After": "60"},
        )
    token = await open_session(
        request,
        response,
        session,
        user_id=opened.user_id,
        token_version=opened.token_version,
        amr=(),
        audit_detail={"method": "demo"},
        ends_by=opened.expires_at,
    )
    return DemoRedemption(
        **token.model_dump(),
        community_id=opened.guild_id,
        import_job_id=opened.import_job_id,
    )
