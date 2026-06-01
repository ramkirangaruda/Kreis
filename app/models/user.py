from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, Enum, DateTime, func
from app.core.database import Base

import enum
from datetime import datetime


class UserRole(enum.Enum):
    KREIS_ADMIN = "KREIS_ADMIN"
    PRINCIPAL = "PRINCIPAL"
    STAFF = "STAFF"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        nullable=False
    )

    institution_id: Mapped[int | None] = mapped_column(
        nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )