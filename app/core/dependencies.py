from fastapi import Depends, HTTPException, status, Cookie

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User


async def get_current_user(
    access_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db)
) -> User:

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"}
        )

    payload = decode_token(access_token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"}
        )

    result = await db.execute(
        select(User).where(User.id == int(payload["sub"]))
    )

    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={"Location": "/login"}
        )

    return user


def require_role(roles: list[str]):

    async def checker(
        current_user: User = Depends(get_current_user)
    ):

        if current_user.role.value not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied"
            )

        return current_user

    return checker