import enum
from datetime import date, datetime

from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    Text,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────

class CircularCategory(enum.Enum):
    ACADEMIC = "ACADEMIC"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    FINANCIAL = "FINANCIAL"
    SPORTS = "SPORTS"
    HEALTH = "HEALTH"
    EXAM = "EXAM"
    OTHER = "OTHER"


class Urgency(enum.Enum):
    URGENT = "URGENT"
    NORMAL = "NORMAL"
    FOR_INFORMATION = "FOR_INFORMATION"


class RecipientType(enum.Enum):
    ALL_STAFF = "ALL_STAFF"
    ALL_STUDENTS = "ALL_STUDENTS"
    SPECIFIC_CLASS = "SPECIFIC_CLASS"
    INDIVIDUAL = "INDIVIDUAL"


class DocType(enum.Enum):
    HEALTH_RECORD = "HEALTH_RECORD"
    BILL = "BILL"
    EXAM_PAPER = "EXAM_PAPER"
    ADMISSION_FORM = "ADMISSION_FORM"
    OTHER = "OTHER"


class OcrStatus(enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DONE = "DONE"
    FAILED = "FAILED"


class BillType(enum.Enum):
    ELECTRICITY = "ELECTRICITY"
    WATER = "WATER"
    OTHER = "OTHER"


# ── 14. Circular ───────────────────────────────────────────────

class Circular(Base):
    __tablename__ = "circulars"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int | None] = mapped_column(
        ForeignKey("institutions.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[CircularCategory] = mapped_column(
        Enum(CircularCategory), nullable=False
    )
    urgency: Mapped[Urgency] = mapped_column(Enum(Urgency), nullable=False)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    institution: Mapped["Institution"] = relationship()
    acknowledgements: Mapped[list["CircularAcknowledgement"]] = relationship(
        back_populates="circular", cascade="all, delete-orphan"
    )


# ── 15. CircularAcknowledgement ────────────────────────────────

class CircularAcknowledgement(Base):
    __tablename__ = "circular_acknowledgements"

    id: Mapped[int] = mapped_column(primary_key=True)
    circular_id: Mapped[int] = mapped_column(ForeignKey("circulars.id"))
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    acknowledged_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    circular: Mapped["Circular"] = relationship(back_populates="acknowledgements")
    institution: Mapped["Institution"] = relationship()


# ── 16. Memo ───────────────────────────────────────────────────

class Memo(Base):
    __tablename__ = "memos"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_type: Mapped[RecipientType] = mapped_column(
        Enum(RecipientType), nullable=False
    )
    recipient_class_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_sections.id"), nullable=True
    )
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    sender: Mapped["User"] = relationship(foreign_keys=[sender_id])
    institution: Mapped["Institution"] = relationship()
    recipient_class: Mapped["ClassSection"] = relationship()
    recipient_user: Mapped["User"] = relationship(foreign_keys=[recipient_user_id])


# ── 17. UploadedDocument ───────────────────────────────────────

class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[DocType] = mapped_column(Enum(DocType), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_status: Mapped[OcrStatus] = mapped_column(
        Enum(OcrStatus), default=OcrStatus.PENDING, nullable=False
    )
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True
    )
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    institution: Mapped["Institution"] = relationship()
    student: Mapped["Student"] = relationship()


# ── 18. UtilityBill ────────────────────────────────────────────

class UtilityBill(Base):
    __tablename__ = "utility_bills"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    bill_type: Mapped[BillType] = mapped_column(Enum(BillType), nullable=False)
    bill_month: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    uploaded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    institution: Mapped["Institution"] = relationship()


# ── Phase 3: face scanner device registry ──────────────────────

class ScannerDevice(Base):
    __tablename__ = "scanner_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(50), unique=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    location: Mapped[str] = mapped_column(String(100))
    device_type: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    institution: Mapped["Institution"] = relationship()


# ── Phase 3: monthly attendance rollup (fast dashboard queries) ─

class AttendanceRollup(Base):
    __tablename__ = "attendance_rollups"
    __table_args__ = (
        UniqueConstraint("student_id", "month", "year", name="uq_rollup_student_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    month: Mapped[int] = mapped_column(Integer)
    year: Mapped[int] = mapped_column(Integer)
    total_days: Mapped[int] = mapped_column(Integer, default=0)
    present_days: Mapped[int] = mapped_column(Integer, default=0)
    absent_days: Mapped[int] = mapped_column(Integer, default=0)
    late_days: Mapped[int] = mapped_column(Integer, default=0)
    percentage: Mapped[float] = mapped_column(Float, default=0.0)
