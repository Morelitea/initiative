from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from jose import JWTError, jwt
from sqlmodel import select

from app.api.deps import SessionDep
from app.core.config import settings
from app.models.user import User
from app.schemas.token import TokenPayload
from app.services.realtime import manager

router = APIRouter()


async def _user_from_token(token: str, session: SessionDep) -> User:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        token_data = TokenPayload(**payload)
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token") from exc

    if not token_data.sub:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token payload")

    statement = select(User).where(User.id == int(token_data.sub))
    result = await session.exec(statement)
    user = result.one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return user


@router.websocket("/updates")
async def websocket_updates(websocket: WebSocket, session: SessionDep, token: str = Query(...)):
    try:
        await _user_from_token(token, session)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive by awaiting incoming messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
