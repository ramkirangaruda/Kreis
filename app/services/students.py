"""Student service layer — School ERP.

Business logic for the Students module: listing/filtering, detail aggregation
(demographics, academics, attendance, health), create/update/deactivate,
dashboard stats, class promotion, and Excel export.
"""

import io
from datetime import date, datetime, timedelta

from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from openpyxl import Workbook
from fastapi.responses import StreamingResponse

from app.models.student import (
    Student,
    StudentDemographics,
    ClassSection,
    AcademicYear,
    Gender,
    CasteCategory,
)
from app.models.attendance import StudentAttendance, StudentAttendanceStatus
from app.models.academic import ExamResult, CompetitiveExamResult
from app.services.audit import log_action


class NotFoundError(Exception):
    """Raised when a student does not exist or is outside the caller's scope."""


# ── helpers ────────────────────────────────────────────────────

def _is_admin(user) -> bool:
    return user.role.value == "KREIS_ADMIN"


def _enum_or_none(enum_cls, value):
    if not value:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _check_scope(student: Student, current_user) -> None:
    if not _is_admin(current_user) and student.institution_id != current_user.institution_id:
        raise NotFoundError("Student not found.")


# ── 1. list ────────────────────────────────────────────────────

async def list_students(
    db: AsyncSession,
    current_user,
    class_section_id: int | None = None,
    gender: str | None = None,
    caste_category: str | None = None,
    search: str = "",
    academic_year_id: int | None = None,
):
    query = (
        select(Student)
        .options(
            selectinload(Student.demographics),
            selectinload(Student.class_section),
        )
        .where(Student.is_active.is_(True))
    )

    if not _is_admin(current_user):
        query = query.where(Student.institution_id == current_user.institution_id)

    if class_section_id:
        query = query.where(Student.class_section_id == class_section_id)
    if academic_year_id:
        query = query.where(Student.academic_year_id == academic_year_id)

    g = _enum_or_none(Gender, gender)
    if g:
        query = query.where(Student.gender == g)

    if caste_category:
        cc = _enum_or_none(CasteCategory, caste_category)
        if cc:
            query = (
                query.join(
                    StudentDemographics,
                    StudentDemographics.student_id == Student.id,
                )
                .where(StudentDemographics.caste_category == cc)
            )

    if search:
        term = f"%{search.strip()}%"
        query = query.where(
            or_(
                Student.full_name.ilike(term),
                Student.admission_number.ilike(term),
            )
        )

    query = query.order_by(Student.full_name)
    result = await db.execute(query)
    return result.scalars().all()


# ── 2. detail ──────────────────────────────────────────────────

async def get_student(db: AsyncSession, student_id: int, current_user) -> dict:
    result = await db.execute(
        select(Student)
        .options(
            selectinload(Student.demographics),
            selectinload(Student.class_section).selectinload(ClassSection.academic_year),
            selectinload(Student.institution),
            selectinload(Student.health_records),
            selectinload(Student.sick_bay_visits),
            selectinload(Student.exam_results).selectinload(ExamResult.subject),
            selectinload(Student.exam_results).selectinload(ExamResult.exam),
            selectinload(Student.competitive_results),
        )
        .where(Student.id == student_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise NotFoundError("Student not found.")
    _check_scope(student, current_user)

    attendance = await _attendance_summary(db, student)

    # Recent exam results first (by exam start date, then id).
    exam_results = sorted(
        student.exam_results,
        key=lambda r: (r.exam.start_date if r.exam else date.min, r.id),
        reverse=True,
    )

    return {
        "student": student,
        "attendance": attendance,
        "exam_results": exam_results,
        "competitive_results": sorted(
            student.competitive_results,
            key=lambda r: (r.exam_year, r.id),
            reverse=True,
        ),
        "health_records": sorted(
            student.health_records,
            key=lambda r: (r.recorded_date, r.id),
            reverse=True,
        ),
        "sick_bay_visits": sorted(
            student.sick_bay_visits,
            key=lambda r: (r.visit_date, r.id),
            reverse=True,
        ),
    }


async def _attendance_summary(db: AsyncSession, student: Student) -> dict:
    """Attendance percentage for the current academic year + a last-30-day grid."""
    # Current academic year for this institution (date window for the %).
    cur_ay = (
        await db.execute(
            select(AcademicYear).where(
                AcademicYear.institution_id == student.institution_id,
                AcademicYear.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()

    base = select(StudentAttendance).where(
        StudentAttendance.student_id == student.id
    )
    if cur_ay:
        base = base.where(
            StudentAttendance.date >= cur_ay.start_date,
            StudentAttendance.date <= cur_ay.end_date,
        )

    records = (await db.execute(base)).scalars().all()
    total = len(records)
    present = sum(1 for r in records if r.status == StudentAttendanceStatus.PRESENT)
    late = sum(1 for r in records if r.status == StudentAttendanceStatus.LATE)
    absent = sum(1 for r in records if r.status == StudentAttendanceStatus.ABSENT)
    excused = sum(1 for r in records if r.status == StudentAttendanceStatus.EXCUSED)
    percentage = round((present + late) / total * 100, 1) if total else 0.0

    # Last 30 calendar days grid.
    today = date.today()
    window_start = today - timedelta(days=29)
    recent = (
        await db.execute(
            select(StudentAttendance).where(
                StudentAttendance.student_id == student.id,
                StudentAttendance.date >= window_start,
                StudentAttendance.date <= today,
            )
        )
    ).scalars().all()
    by_day = {r.date: r.status.value for r in recent}
    calendar = [
        {
            "date": window_start + timedelta(days=i),
            "status": by_day.get(window_start + timedelta(days=i)),
        }
        for i in range(30)
    ]

    return {
        "total": total,
        "present": present,
        "late": late,
        "absent": absent,
        "excused": excused,
        "percentage": percentage,
        "calendar": calendar,
    }


# ── 3. create ──────────────────────────────────────────────────

async def create_student(
    db: AsyncSession,
    student_data: dict,
    demographics_data: dict,
    current_user,
    ip: str | None = None,
) -> Student:
    section = await db.get(ClassSection, int(student_data["class_section_id"]))
    if not section:
        raise ValueError("Selected class section does not exist.")
    if not _is_admin(current_user) and section.institution_id != current_user.institution_id:
        raise ValueError("You cannot add students to another institution.")

    admission_number = student_data["admission_number"].strip()
    dup = await db.execute(
        select(Student.id).where(
            Student.institution_id == section.institution_id,
            Student.admission_number == admission_number,
        )
    )
    if dup.scalar_one_or_none():
        raise ValueError(
            f"Admission number '{admission_number}' is already used in this institution."
        )

    aadhar = (student_data.get("aadhar_number") or "").strip() or None
    if aadhar:
        a_dup = await db.execute(
            select(Student.id).where(Student.aadhar_number == aadhar)
        )
        if a_dup.scalar_one_or_none():
            raise ValueError(f"Aadhar number '{aadhar}' is already registered.")

    gender = _enum_or_none(Gender, student_data.get("gender"))
    if gender is None:
        raise ValueError("A valid gender is required.")

    caste_category = _enum_or_none(
        CasteCategory, demographics_data.get("caste_category")
    )
    if caste_category is None:
        raise ValueError("A valid caste category is required.")

    student = Student(
        admission_number=admission_number,
        institution_id=section.institution_id,
        class_section_id=section.id,
        academic_year_id=section.academic_year_id,
        full_name=student_data["full_name"].strip(),
        date_of_birth=student_data["date_of_birth"],
        gender=gender,
        aadhar_number=aadhar,
        sats_id=(student_data.get("sats_id") or "").strip() or None,
        photo_url=(student_data.get("photo_url") or "").strip() or None,
        is_residential=bool(student_data.get("is_residential", True)),
    )
    db.add(student)
    await db.flush()

    demographics = StudentDemographics(
        student_id=student.id,
        caste_category=caste_category,
        **_clean_demographics(demographics_data),
    )
    db.add(demographics)

    await log_action(
        db=db,
        user_id=current_user.id,
        action="CREATE_STUDENT",
        entity="Student",
        entity_id=student.id,
        details={
            "admission_number": student.admission_number,
            "full_name": student.full_name,
        },
        ip_address=ip,
    )
    await db.commit()
    return student


# ── 4. update ──────────────────────────────────────────────────

async def update_student(
    db: AsyncSession,
    student_id: int,
    student_data: dict,
    demographics_data: dict,
    current_user,
    ip: str | None = None,
) -> Student:
    result = await db.execute(
        select(Student)
        .options(selectinload(Student.demographics))
        .where(Student.id == student_id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise NotFoundError("Student not found.")
    _check_scope(student, current_user)

    admission_number = student_data["admission_number"].strip()
    if admission_number != student.admission_number:
        dup = await db.execute(
            select(Student.id).where(
                Student.institution_id == student.institution_id,
                Student.admission_number == admission_number,
                Student.id != student.id,
            )
        )
        if dup.scalar_one_or_none():
            raise ValueError(
                f"Admission number '{admission_number}' is already used in this institution."
            )

    aadhar = (student_data.get("aadhar_number") or "").strip() or None
    if aadhar and aadhar != student.aadhar_number:
        a_dup = await db.execute(
            select(Student.id).where(
                Student.aadhar_number == aadhar, Student.id != student.id
            )
        )
        if a_dup.scalar_one_or_none():
            raise ValueError(f"Aadhar number '{aadhar}' is already registered.")

    gender = _enum_or_none(Gender, student_data.get("gender"))
    if gender is None:
        raise ValueError("A valid gender is required.")

    if student_data.get("class_section_id"):
        section = await db.get(ClassSection, int(student_data["class_section_id"]))
        if not section:
            raise ValueError("Selected class section does not exist.")
        if not _is_admin(current_user) and section.institution_id != current_user.institution_id:
            raise ValueError("Invalid class section for this institution.")
        student.class_section_id = section.id
        student.academic_year_id = section.academic_year_id

    student.admission_number = admission_number
    student.full_name = student_data["full_name"].strip()
    student.date_of_birth = student_data["date_of_birth"]
    student.gender = gender
    student.aadhar_number = aadhar
    student.sats_id = (student_data.get("sats_id") or "").strip() or None
    if "is_residential" in student_data:
        student.is_residential = bool(student_data["is_residential"])

    caste_category = _enum_or_none(
        CasteCategory, demographics_data.get("caste_category")
    )
    cleaned = _clean_demographics(demographics_data)
    demo = student.demographics
    if demo is None:
        demo = StudentDemographics(
            student_id=student.id,
            caste_category=caste_category or CasteCategory.GENERAL,
            **cleaned,
        )
        db.add(demo)
    else:
        if caste_category is not None:
            demo.caste_category = caste_category
        for key, value in cleaned.items():
            setattr(demo, key, value)

    await log_action(
        db=db,
        user_id=current_user.id,
        action="UPDATE_STUDENT",
        entity="Student",
        entity_id=student.id,
        details={"admission_number": student.admission_number},
        ip_address=ip,
    )
    await db.commit()
    return student


def _clean_demographics(data: dict) -> dict:
    """Whitelist + normalize demographics fields (excludes caste_category)."""
    text_fields = [
        "caste", "religion",
        "father_name", "father_occupation", "father_phone",
        "mother_name", "mother_occupation", "mother_phone",
        "guardian_name", "guardian_phone",
        "address_village", "address_taluk", "address_district", "address_pin",
    ]
    out: dict = {}
    for f in text_fields:
        val = (data.get(f) or "").strip()
        out[f] = val or None

    income = data.get("annual_income")
    if income not in (None, ""):
        try:
            out["annual_income"] = int(income)
        except (ValueError, TypeError):
            out["annual_income"] = None
    else:
        out["annual_income"] = None
    return out


# ── 5. deactivate ──────────────────────────────────────────────

async def deactivate_student(
    db: AsyncSession, student_id: int, current_user, ip: str | None = None
):
    student = await db.get(Student, student_id)
    if not student:
        raise NotFoundError("Student not found.")
    _check_scope(student, current_user)

    student.is_active = False
    await log_action(
        db=db,
        user_id=current_user.id,
        action="DEACTIVATE_STUDENT",
        entity="Student",
        entity_id=student.id,
        details={"admission_number": student.admission_number},
        ip_address=ip,
    )
    await db.commit()


# ── 6. stats ───────────────────────────────────────────────────

async def get_student_stats(db: AsyncSession, institution_id: int | None = None) -> dict:
    def scope(q):
        if institution_id:
            return q.where(Student.institution_id == institution_id)
        return q

    total = (await db.execute(
        scope(select(func.count(Student.id)).where(Student.is_active.is_(True)))
    )).scalar() or 0

    gender_rows = (await db.execute(
        scope(
            select(Student.gender, func.count(Student.id))
            .where(Student.is_active.is_(True))
            .group_by(Student.gender)
        )
    )).all()
    gender_counts = {g.value: 0 for g in Gender}
    for g, n in gender_rows:
        gender_counts[g.value] = n

    caste_rows = (await db.execute(
        scope(
            select(StudentDemographics.caste_category, func.count(Student.id))
            .join(Student, Student.id == StudentDemographics.student_id)
            .where(Student.is_active.is_(True))
            .group_by(StudentDemographics.caste_category)
        )
    )).all()
    caste_counts = {c.value: 0 for c in CasteCategory}
    for c, n in caste_rows:
        caste_counts[c.value] = n

    grade_rows = (await db.execute(
        scope(
            select(ClassSection.grade, func.count(Student.id))
            .join(Student, Student.class_section_id == ClassSection.id)
            .where(Student.is_active.is_(True))
            .group_by(ClassSection.grade)
        )
    )).all()
    by_grade = [{"grade": grade, "count": n} for grade, n in grade_rows]
    by_grade.sort(key=lambda r: (len(r["grade"]), r["grade"]))

    return {
        "total": total,
        "male": gender_counts.get("MALE", 0),
        "female": gender_counts.get("FEMALE", 0),
        "other": gender_counts.get("OTHER", 0),
        "caste": caste_counts,
        "by_grade": by_grade,
    }


# ── 7. promote_class ───────────────────────────────────────────

async def promote_class(
    db: AsyncSession,
    from_section_id: int,
    to_section_id: int,
    current_user,
    ip: str | None = None,
) -> int:
    from_section = await db.get(ClassSection, from_section_id)
    to_section = await db.get(ClassSection, to_section_id)
    if not from_section or not to_section:
        raise ValueError("Both class sections must exist.")

    if not _is_admin(current_user):
        if (
            from_section.institution_id != current_user.institution_id
            or to_section.institution_id != current_user.institution_id
        ):
            raise ValueError("Class sections must belong to your institution.")

    students = (await db.execute(
        select(Student).where(
            Student.class_section_id == from_section_id,
            Student.is_active.is_(True),
        )
    )).scalars().all()

    for student in students:
        student.class_section_id = to_section.id
        student.academic_year_id = to_section.academic_year_id
        await log_action(
            db=db,
            user_id=current_user.id,
            action="PROMOTE_STUDENT",
            entity="Student",
            entity_id=student.id,
            details={
                "from_section": from_section_id,
                "to_section": to_section_id,
            },
            ip_address=ip,
        )

    await db.commit()
    return len(students)


# ── Excel export ───────────────────────────────────────────────

async def export_students_excel(
    db: AsyncSession,
    current_user,
    class_section_id: int | None = None,
    gender: str | None = None,
    caste_category: str | None = None,
    search: str = "",
) -> StreamingResponse:
    students = await list_students(
        db,
        current_user,
        class_section_id=class_section_id,
        gender=gender,
        caste_category=caste_category,
        search=search,
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Students"
    ws.append([
        "Admission No", "Name", "Gender", "Caste Category",
        "Class", "Section", "Father Name", "Father Phone", "District",
    ])

    for s in students:
        demo = s.demographics
        section = s.class_section
        ws.append([
            s.admission_number,
            s.full_name,
            s.gender.value if s.gender else "",
            demo.caste_category.value if demo and demo.caste_category else "",
            section.grade if section else "",
            section.section if section else "",
            demo.father_name if demo else "",
            demo.father_phone if demo else "",
            demo.address_district if demo else "",
        ])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": "attachment; filename=students.xlsx"},
    )


# ── form support ───────────────────────────────────────────────

async def list_class_sections(db: AsyncSession, current_user):
    """Class sections the caller may assign students to (for form dropdowns)."""
    query = (
        select(ClassSection)
        .options(selectinload(ClassSection.institution))
        .order_by(ClassSection.grade, ClassSection.section)
    )
    if not _is_admin(current_user):
        query = query.where(ClassSection.institution_id == current_user.institution_id)
    return (await db.execute(query)).scalars().all()
