from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import (
    String,
    Integer,
    ForeignKey,
    Enum,
    DateTime,
    func,
)

from app.core.database import Base

import enum
from datetime import datetime


class MovementType(enum.Enum):
    ISSUE = "ISSUE"
    RETURN = "RETURN"
    TRANSFER = "TRANSFER"
    RECEIPT = "RECEIPT"
    ADJUSTMENT = "ADJUSTMENT"


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    asset_id: Mapped[int] = mapped_column(
        ForeignKey("assets.id")
    )

    institution_id: Mapped[int] = mapped_column(
        ForeignKey("institutions.id")
    )

    quantity_total: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    quantity_available: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    low_stock_threshold: Mapped[int] = mapped_column(
        Integer,
        default=10
    )

    location: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )


class AssetMovement(Base):
    __tablename__ = "asset_movements"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    inventory_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id")
    )

    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType)
    )

    quantity: Mapped[int] = mapped_column(
        Integer
    )

    from_institution: Mapped[int | None] = mapped_column(
        nullable=True
    )

    to_institution: Mapped[int | None] = mapped_column(
        nullable=True
    )

    issued_to: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True
    )

    performed_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    notes: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )