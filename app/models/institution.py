from sqlalchemy.orm import relationship, Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy import String, Boolean, DateTime, func
from app.core.database import Base

from datetime import datetime


class Institution(Base):
    __tablename__ = "institutions"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    code: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False
    )

    district: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    address: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    users: Mapped[list["User"]] = relationship(
        back_populates="institution",
        lazy="selectin"
    )

    inventory: Mapped[list["InventoryItem"]] = relationship(
        back_populates="institution",
        lazy="selectin"
    )