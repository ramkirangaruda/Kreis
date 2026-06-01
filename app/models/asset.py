from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String,
    Boolean,
    ForeignKey,
)

from app.core.database import Base


class AssetCategory(Base):
    __tablename__ = "asset_categories"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    code: Mapped[str] = mapped_column(
        String(1),
        unique=True,
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    category_id: Mapped[int] = mapped_column(
        ForeignKey("asset_categories.id")
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    unit: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True
    )