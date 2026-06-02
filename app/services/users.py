import secrets
import string

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.models.institution import Institution
from app.core.security import hash_password
from app.services.audit import log_action


async def list_users(
    db: AsyncSession,
    role: str = "",
    institution_id: int | None = None
) -> list:
    query = select(User).order_by(User.full_name)

    if role:
        query = query.where(User.role == UserRole[role])
    if institution_id is not None:
        query = query.where(User.institution_id == institution_id)

    result = await db.execute(query)
    return result.scalars().all()


async def get_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def create_user(
    db: AsyncSession,
    data: dict,
    current_user,
    ip: str | None = None
) -> User:
    # Email uniqueness
    existing = await db.execute(
        select(User).where(User.email == data["email"].strip().lower())
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Email '{data['email']}' is already registered.")

    role = UserRole[data["role"]]

    # Non-admin roles must have an institution
    if role != UserRole.KREIS_ADMIN:
        if not data.get("institution_id"):
            raise ValueError("Institution is required for Principal and Staff roles.")
        inst = await db.get(Institution, int(data["institution_id"]))
        if not inst:
            raise ValueError("Selected institution does not exist.")

    user = User(
        email=data["email"].strip().lower(),
        hashed_password=hash_password(data["password"]),
        full_name=data["full_name"].strip(),
        role=role,
        institution_id=int(data["institution_id"]) if data.get("institution_id") else None,
        password_change_required=data.get("password_change_required", False)
    )
    db.add(user)
    await db.flush()

    await log_action(
        db=db,
        user_id=current_user.id,
        action="CREATE_USER",
        entity="User",
        entity_id=user.id,
        details={"email": user.email, "role": user.role.value},
        ip_address=ip
    )
    await db.commit()
    return user


async def update_user(
    db: AsyncSession,
    user_id: int,
    data: dict,
    current_user,
    ip: str | None = None
) -> User:
    user = await get_user(db, user_id)

    new_email = data["email"].strip().lower()
    if new_email != user.email:
        existing = await db.execute(
            select(User).where(User.email == new_email, User.id != user_id)
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Email '{new_email}' is already registered.")

    role = UserRole[data["role"]]
    if role != UserRole.KREIS_ADMIN and not data.get("institution_id"):
        raise ValueError("Institution is required for Principal and Staff roles.")

    user.email = new_email
    user.full_name = data["full_name"].strip()
    user.role = role
    user.institution_id = int(data["institution_id"]) if data.get("institution_id") else None

    await log_action(
        db=db,
        user_id=current_user.id,
        action="UPDATE_USER",
        entity="User",
        entity_id=user.id,
        details={"email": user.email, "role": user.role.value},
        ip_address=ip
    )
    await db.commit()
    return user


def _generate_temp_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def reset_password(
    db: AsyncSession,
    user_id: int,
    current_user,
    ip: str | None = None
) -> str:
    user = await get_user(db, user_id)
    temp = _generate_temp_password()

    user.hashed_password = hash_password(temp)
    user.password_change_required = True

    await log_action(
        db=db,
        user_id=current_user.id,
        action="RESET_PASSWORD",
        entity="User",
        entity_id=user.id,
        ip_address=ip
    )
    await db.commit()
    return temp


async def deactivate_user(
    db: AsyncSession,
    user_id: int,
    current_user,
    ip: str | None = None
):
    if user_id == current_user.id:
        raise ValueError("You cannot deactivate your own account.")

    user = await get_user(db, user_id)
    user.is_active = False

    await log_action(
        db=db,
        user_id=current_user.id,
        action="DEACTIVATE_USER",
        entity="User",
        entity_id=user.id,
        details={"email": user.email},
        ip_address=ip
    )
    await db.commit()
