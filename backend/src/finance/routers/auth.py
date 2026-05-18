from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.dependencies import current_user
from finance.auth.sessions import COOKIE_NAME, MAX_AGE, create_session_token
from finance.db import get_session
from finance.models.user import User
from finance.schemas.user import UserCreate, UserRead
from finance.services import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/needs-setup")
async def needs_setup(session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    exists = await auth_service.user_exists(session)
    return {"needs_setup": not exists}


@router.post("/setup", response_model=UserRead, status_code=201)
async def setup(
    data: UserCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    if await auth_service.user_exists(session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User already exists",
        )
    user = await auth_service.create_user(session, data.username, data.password)
    _set_session_cookie(response, user.id)
    return user


@router.post("/login", response_model=UserRead)
async def login(
    data: UserCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    user = await auth_service.authenticate(session, data.username, data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    _set_session_cookie(response, user.id)
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


@router.get("/me", response_model=UserRead)
async def me(user: User = Depends(current_user)):
    return user


def _set_session_cookie(response: Response, user_id: int) -> None:
    token = create_session_token(user_id)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=MAX_AGE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=False,  # switched to True behind TLS reverse proxy
    )
