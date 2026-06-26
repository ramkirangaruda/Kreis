import enum
from datetime import date, time

from sqlalchemy import (
    String,
    Integer,
    Float,
    Boolean,
    Text,
    Date,
    Time,
    Enum,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ── Enums ──────────────────────────────────────────────────────

class ExamType(enum.Enum):
    UNIT_TEST = "UNIT_TEST"
    MID_TERM = "MID_TERM"
    ANNUAL = "ANNUAL"
    BOARD = "BOARD"
    OTHER = "OTHER"


class CompetitiveExamName(enum.Enum):
    CET = "CET"
    JEE_MAINS = "JEE_MAINS"
    JEE_ADVANCED = "JEE_ADVANCED"
    NEET = "NEET"
    OTHER = "OTHER"


class DayOfWeek(enum.Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"


# ── 7. Subject ─────────────────────────────────────────────────

class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    class_section_id: Mapped[int | None] = mapped_column(
        ForeignKey("class_sections.id"), nullable=True
    )

    institution: Mapped["Institution"] = relationship()
    class_section: Mapped["ClassSection"] = relationship()


# ── 8. Exam ────────────────────────────────────────────────────

class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    exam_type: Mapped[ExamType] = mapped_column(Enum(ExamType), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    institution: Mapped["Institution"] = relationship()
    academic_year: Mapped["AcademicYear"] = relationship()
    results: Mapped[list["ExamResult"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


# ── 9. ExamResult ──────────────────────────────────────────────

class ExamResult(Base):
    __tablename__ = "exam_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    marks_obtained: Mapped[float] = mapped_column(Float, nullable=False)
    max_marks: Mapped[float] = mapped_column(Float, nullable=False)
    is_absent: Mapped[bool] = mapped_column(Boolean, default=False)
    grade: Mapped[str | None] = mapped_column(String(5), nullable=True)
    uploaded_paper_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="exam_results")
    exam: Mapped["Exam"] = relationship(back_populates="results")
    subject: Mapped["Subject"] = relationship()


# ── 10. CompetitiveExamResult ──────────────────────────────────

class CompetitiveExamResult(Base):
    __tablename__ = "competitive_exam_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    exam_name: Mapped[CompetitiveExamName] = mapped_column(
        Enum(CompetitiveExamName), nullable=False
    )
    exam_year: Mapped[int] = mapped_column(Integer, nullable=False)
    roll_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    student: Mapped["Student"] = relationship(back_populates="competitive_results")


# ── 11. TimetableSlot ──────────────────────────────────────────

class TimetableSlot(Base):
    __tablename__ = "timetable_slots"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"))
    day_of_week: Mapped[DayOfWeek] = mapped_column(Enum(DayOfWeek), nullable=False)
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_id: Mapped[int | None] = mapped_column(
        ForeignKey("subjects.id"), nullable=True
    )
    teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    class_section: Mapped["ClassSection"] = relationship()
    subject: Mapped["Subject"] = relationship()
    teacher: Mapped["User"] = relationship(foreign_keys=[teacher_id])
