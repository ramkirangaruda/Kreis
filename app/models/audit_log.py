from datetime import datetime

from sqlalchemy import (
    String,
    ForeignKey,
    DateTime,
    Text,
    func
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship
)

from app.core.database import Base


class AuditLog(Base):

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    entity: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    entity_id: Mapped[int] = mapped_column(
        nullable=False
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True
    )

    details: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now()
    )

    user: Mapped["User"] = relationship(
        back_populates="audit_logs",
        lazy="selectin"
    )