from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ── 19. Alumni ─────────────────────────────────────────────────

class Alumni(Base):
    __tablename__ = "alumni"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True
    )
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    batch_year: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_class: Mapped[str] = mapped_column(String(10), nullable=False)
    current_occupation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    higher_education_institution: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    higher_education_course: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    location_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location_state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notable_achievement: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    institution: Mapped["Institution"] = relationship()
    student: Mapped["Student"] = relationship()
