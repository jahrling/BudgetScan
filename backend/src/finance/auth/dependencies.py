from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.sessions import read_session_token
from finance.db import get_session
from finance.models.user import User


async def current_user(
    session: AsyncSession = Depends(get_session),
    session_cookie: str | None = Cookie(None, alias="session"),
) -> User:
    if session_cookie is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user_id = read_session_token(session_cookie)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
