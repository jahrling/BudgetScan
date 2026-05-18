from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance.auth.passwords import hash_password, verify_password
from finance.models.user import User


async def user_exists(session: AsyncSession) -> bool:
    result = await session.execute(select(func.count(User.id)))
    return result.scalar_one() > 0


async def create_user(session: AsyncSession, username: str, password: str) -> User:
    user = User(username=username, password_hash=hash_password(password))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, username: str, password: str) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user
