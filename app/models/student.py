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

class Gender(enum.Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class CasteCategory(enum.Enum):
    SC = "SC"
    ST = "ST"
    OBC = "OBC"
    GENERAL = "GENERAL"
    EWS = "EWS"


# ── 1. AcademicYear ────────────────────────────────────────────

class AcademicYear(Base):
    __tablename__ = "academic_years"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)

    institution: Mapped["Institution"] = relationship(
        back_populates="academic_years"
    )


# ── 2. ClassSection ────────────────────────────────────────────

class ClassSection(Base):
    __tablename__ = "class_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id"))
    grade: Mapped[str] = mapped_column(String(10), nullable=False)
    section: Mapped[str] = mapped_column(String(10), nullable=False)
    class_teacher_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    institution: Mapped["Institution"] = relationship(
        back_populates="class_sections"
    )
    academic_year: Mapped["AcademicYear"] = relationship()
    class_teacher: Mapped["User"] = relationship(foreign_keys=[class_teacher_id])


# ── 3. Student ─────────────────────────────────────────────────

class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "admission_number",
            name="uq_student_admission_per_institution",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    admission_number: Mapped[str] = mapped_column(String(50), nullable=False)
    institution_id: Mapped[int] = mapped_column(ForeignKey("institutions.id"))
    class_section_id: Mapped[int] = mapped_column(ForeignKey("class_sections.id"))
    academic_year_id: Mapped[int] = mapped_column(ForeignKey("academic_years.id"))
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[Gender] = mapped_column(Enum(Gender), nullable=False)
    aadhar_number: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True
    )
    sats_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_residential: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )

    institution: Mapped["Institution"] = relationship(back_populates="students")
    class_section: Mapped["ClassSection"] = relationship()
    academic_year: Mapped["AcademicYear"] = relationship()

    demographics: Mapped["StudentDemographics"] = relationship(
        back_populates="student", uselist=False, cascade="all, delete-orphan"
    )
    health_records: Mapped[list["StudentHealthRecord"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    sick_bay_visits: Mapped[list["SickBayVisit"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    attendance_records: Mapped[list["StudentAttendance"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    exam_results: Mapped[list["ExamResult"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    competitive_results: Mapped[list["CompetitiveExamResult"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


# ── 4. StudentDemographics ─────────────────────────────────────

class StudentDemographics(Base):
    __tablename__ = "student_demographics"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id"), unique=True
    )
    caste_category: Mapped[CasteCategory] = mapped_column(
        Enum(CasteCategory), nullable=False
    )
    caste: Mapped[str | None] = mapped_column(String(100), nullable=True)
    religion: Mapped[str | None] = mapped_column(String(100), nullable=True)

    father_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    father_occupation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    father_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    mother_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mother_occupation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mother_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    guardian_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    guardian_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    annual_income: Mapped[int | None] = mapped_column(Integer, nullable=True)

    address_village: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_taluk: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_district: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_pin: Mapped[str | None] = mapped_column(String(10), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="demographics")


# ── 5. StudentHealthRecord ─────────────────────────────────────

class StudentHealthRecord(Base):
    __tablename__ = "student_health_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    recorded_date: Mapped[date] = mapped_column(Date, nullable=False)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    blood_group: Mapped[str | None] = mapped_column(String(10), nullable=True)
    vision_left: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vision_right: Mapped[str | None] = mapped_column(String(20), nullable=True)
    allergies: Mapped[str | None] = mapped_column(Text, nullable=True)
    chronic_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    student: Mapped["Student"] = relationship(back_populates="health_records")


# ── 6. SickBayVisit ────────────────────────────────────────────

class SickBayVisit(Base):
    __tablename__ = "sick_bay_visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    treatment: Mapped[str | None] = mapped_column(Text, nullable=True)
    referred_to_hospital: Mapped[bool] = mapped_column(Boolean, default=False)
    hospital_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    student: Mapped["Student"] = relationship(back_populates="sick_bay_visits")
