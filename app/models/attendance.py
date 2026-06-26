import enum
from datetime import date, datetime

from sqlalchemy import (
    Integer,
    Boolean,
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

class StudentAttendanceStatus(enum.Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    EXCUSED = "EXCUSED"


class FacultyAttendanceStatus(enum.Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    LATE = "LATE"
    ON_LEAVE = "ON_LEAVE"


class LeaveType(enum.Enum):
    CASUAL = "CASUAL"
    SICK = "SICK"
    EARNED = "EARNED"
    OTHER = "OTHER"


# ── 12. StudentAttendance ──────────────────────────────────────

class StudentAttendance(Base):
    __tablename__ = "student_attendance"
    __table_args__ = (
        UniqueConstraint("student_id", "date", name="uq_student_attendance_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[StudentAttendanceStatus] = mapped_column(
        Enum(StudentAttendanceStatus), nullable=False
    )
    marked_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    student: Mapped["Student"] = relationship(back_populates="attendance_records")
    class_section: Mapped["ClassSection"] = relationship()


# ── 13. FacultyAttendance ──────────────────────────────────────

class FacultyAttendance(Base):
    __tablename__ = "faculty_attendance"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_faculty_attendance_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[FacultyAttendanceStatus] = mapped_column(
        Enum(FacultyAttendanceStatus), nullable=False
    )
    leave_type: Mapped[LeaveType | None] = mapped_column(
        Enum(LeaveType), nullable=True
    )
    marked_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    scanner_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    institution: Mapped["Institution"] = relationship()
