"""Attendance service layer — School ERP (students + faculty)."""

import io
import calendar as _cal
from datetime import date, datetime

from sqlalchemy import select, func, case
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from openpyxl import Workbook
from fastapi.responses import StreamingResponse

from app.models.student import Student, ClassSection, AcademicYear
from app.models.user import User, UserRole
from app.models.attendance import (
    StudentAttendance,
    StudentAttendanceStatus,
    FacultyAttendance,
    FacultyAttendanceStatus,
    LeaveType,
)
from app.services.audit import log_action


class NotFoundError(Exception):
    """Raised when an entity is missing or outside the caller's scope."""


# ── helpers ────────────────────────────────────────────────────

def _is_admin(user) -> bool:
    return user is not None and user.role.value == "KREIS_ADMIN"


def _enum_or_none(enum_cls, value):
    if not value:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return None


def _pct(present: int, late: int, total: int) -> float:
    return round((present + late) / total * 100, 1) if total else 0.0


async def _load_section(db, class_section_id, current_user):
    section = (
        await db.execute(
            select(ClassSection)
            .options(selectinload(ClassSection.institution))
            .where(ClassSection.id == class_section_id)
        )
    ).scalar_one_or_none()
    if not section:
        raise NotFoundError("Class section not found.")
    if current_user and not _is_admin(current_user) and section.institution_id != current_user.institution_id:
        raise NotFoundError("Class section not found.")
    return section


async def _current_ay(db, institution_id):
    return (
        await db.execute(
            select(AcademicYear).where(
                AcademicYear.institution_id == institution_id,
                AcademicYear.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()


# ── 1. class attendance sheet ──────────────────────────────────

async def get_class_attendance_sheet(db, class_section_id, day, current_user):
    section = await _load_section(db, class_section_id, current_user)

    students = (await db.execute(
        select(Student)
        .where(Student.class_section_id == class_section_id, Student.is_active.is_(True))
        .order_by(Student.full_name)
    )).scalars().all()

    existing = (await db.execute(
        select(StudentAttendance).where(
            StudentAttendance.class_section_id == class_section_id,
            StudentAttendance.date == day,
        )
    )).scalars().all()
    status_by_student = {a.student_id: a.status.value for a in existing}

    rows = [
        {"student": s, "status": status_by_student.get(s.id)}
        for s in students
    ]
    return {
        "section": section,
        "date": day,
        "rows": rows,
        "already_marked": len(existing) > 0,
    }


# ── 2. mark student attendance ─────────────────────────────────

async def mark_student_attendance(db, records, class_section_id, day, current_user, ip=None):
    section = await _load_section(db, class_section_id, current_user)

    valid_ids = set((await db.execute(
        select(Student.id).where(
            Student.class_section_id == class_section_id,
            Student.is_active.is_(True),
        )
    )).scalars().all())

    existing = (await db.execute(
        select(StudentAttendance).where(
            StudentAttendance.class_section_id == class_section_id,
            StudentAttendance.date == day,
        )
    )).scalars().all()
    existing_by_student = {a.student_id: a for a in existing}

    count = 0
    for rec in records:
        sid = int(rec["student_id"])
        if sid not in valid_ids:
            continue
        status = _enum_or_none(StudentAttendanceStatus, rec.get("status"))
        if status is None:
            continue
        row = existing_by_student.get(sid)
        if row:
            row.status = status
            row.marked_by_id = current_user.id
        else:
            db.add(StudentAttendance(
                student_id=sid,
                class_section_id=class_section_id,
                date=day,
                status=status,
                marked_by_id=current_user.id,
            ))
        count += 1

    await log_action(
        db=db,
        user_id=current_user.id,
        action="MARK_STUDENT_ATTENDANCE",
        entity="ClassSection",
        entity_id=class_section_id,
        details={"date": day.isoformat(), "records": count},
        ip_address=ip,
    )
    await db.commit()
    return count


# ── 3. student attendance summary ──────────────────────────────

async def get_student_attendance_summary(db, student_id, academic_year_id, current_user):
    student = (await db.execute(
        select(Student).where(Student.id == student_id)
    )).scalar_one_or_none()
    if not student:
        raise NotFoundError("Student not found.")
    if not _is_admin(current_user) and student.institution_id != current_user.institution_id:
        raise NotFoundError("Student not found.")

    ay = None
    if academic_year_id:
        ay = await db.get(AcademicYear, academic_year_id)
    if ay is None:
        ay = await _current_ay(db, student.institution_id)

    q = select(StudentAttendance).where(StudentAttendance.student_id == student_id)
    if ay:
        q = q.where(
            StudentAttendance.date >= ay.start_date,
            StudentAttendance.date <= ay.end_date,
        )
    records = (await db.execute(q)).scalars().all()

    total = len(records)
    present = sum(1 for r in records if r.status == StudentAttendanceStatus.PRESENT)
    absent = sum(1 for r in records if r.status == StudentAttendanceStatus.ABSENT)
    late = sum(1 for r in records if r.status == StudentAttendanceStatus.LATE)
    excused = sum(1 for r in records if r.status == StudentAttendanceStatus.EXCUSED)
    percentage = _pct(present, late, total)

    monthly: dict = {}
    for r in records:
        key = r.date.strftime("%Y-%m")
        m = monthly.setdefault(
            key, {"month": key, "total": 0, "present": 0, "absent": 0, "late": 0, "excused": 0}
        )
        m["total"] += 1
        if r.status == StudentAttendanceStatus.PRESENT:
            m["present"] += 1
        elif r.status == StudentAttendanceStatus.ABSENT:
            m["absent"] += 1
        elif r.status == StudentAttendanceStatus.LATE:
            m["late"] += 1
        elif r.status == StudentAttendanceStatus.EXCUSED:
            m["excused"] += 1
    for m in monthly.values():
        m["percentage"] = _pct(m["present"], m["late"], m["total"])
    monthly_list = [monthly[k] for k in sorted(monthly)]

    # Current-month calendar grid (day -> status).
    today = date.today()
    dim = _cal.monthrange(today.year, today.month)[1]
    day_status = {r.date: r.status.value for r in records}
    cal_grid = [
        {
            "date": date(today.year, today.month, d),
            "status": day_status.get(date(today.year, today.month, d)),
        }
        for d in range(1, dim + 1)
    ]

    return {
        "student": student,
        "academic_year": ay,
        "total": total,
        "present": present,
        "absent": absent,
        "late": late,
        "excused": excused,
        "percentage": percentage,
        "below_75": total > 0 and percentage < 75,
        "monthly": monthly_list,
        "calendar": cal_grid,
        "calendar_label": today.strftime("%B %Y"),
    }


# ── 4. class attendance summary (date range) ───────────────────

async def get_class_attendance_summary(db, class_section_id, date_from, date_to, current_user=None):
    section = await _load_section(db, class_section_id, current_user)

    present_c = func.sum(case((StudentAttendance.status == StudentAttendanceStatus.PRESENT, 1), else_=0))
    absent_c = func.sum(case((StudentAttendance.status == StudentAttendanceStatus.ABSENT, 1), else_=0))
    late_c = func.sum(case((StudentAttendance.status == StudentAttendanceStatus.LATE, 1), else_=0))

    q = (
        select(
            Student.id, Student.full_name, Student.admission_number,
            func.count(StudentAttendance.id), present_c, absent_c, late_c,
        )
        .select_from(Student)
        .outerjoin(
            StudentAttendance,
            (StudentAttendance.student_id == Student.id)
            & (StudentAttendance.date >= date_from)
            & (StudentAttendance.date <= date_to),
        )
        .where(Student.class_section_id == class_section_id, Student.is_active.is_(True))
        .group_by(Student.id, Student.full_name, Student.admission_number)
        .order_by(Student.full_name)
    )
    rows = (await db.execute(q)).all()

    result = []
    for sid, name, adm, total, present, absent, late in rows:
        total = int(total or 0)
        present = int(present or 0)
        absent = int(absent or 0)
        late = int(late or 0)
        pct = _pct(present, late, total)
        result.append({
            "student_id": sid,
            "full_name": name,
            "admission_number": adm,
            "total": total,
            "present": present,
            "absent": absent,
            "late": late,
            "percentage": pct,
            "below_75": total > 0 and pct < 75,
        })

    return {
        "section": section,
        "date_from": date_from,
        "date_to": date_to,
        "rows": result,
        "below_75": [r for r in result if r["below_75"]],
    }


# ── 5. mark faculty attendance ─────────────────────────────────

async def mark_faculty_attendance(db, records, institution_id, day, current_user, ip=None):
    if not _is_admin(current_user) and institution_id != current_user.institution_id:
        raise NotFoundError("Institution not found.")

    valid_ids = set((await db.execute(
        select(User.id).where(
            User.institution_id == institution_id,
            User.role == UserRole.TEACHER,
            User.is_active.is_(True),
        )
    )).scalars().all())

    existing = (await db.execute(
        select(FacultyAttendance).where(
            FacultyAttendance.institution_id == institution_id,
            FacultyAttendance.date == day,
        )
    )).scalars().all()
    existing_by_user = {a.user_id: a for a in existing}

    count = 0
    for rec in records:
        uid = int(rec["user_id"])
        if uid not in valid_ids:
            continue
        status = _enum_or_none(FacultyAttendanceStatus, rec.get("status"))
        if status is None:
            continue
        leave_type = None
        if status == FacultyAttendanceStatus.ON_LEAVE:
            leave_type = _enum_or_none(LeaveType, rec.get("leave_type")) or LeaveType.OTHER

        row = existing_by_user.get(uid)
        if row:
            row.status = status
            row.leave_type = leave_type
            row.marked_by_id = current_user.id
        else:
            db.add(FacultyAttendance(
                user_id=uid,
                institution_id=institution_id,
                date=day,
                status=status,
                leave_type=leave_type,
                marked_by_id=current_user.id,
            ))
        count += 1

    await log_action(
        db=db,
        user_id=current_user.id,
        action="MARK_FACULTY_ATTENDANCE",
        entity="Institution",
        entity_id=institution_id,
        details={"date": day.isoformat(), "records": count},
        ip_address=ip,
    )
    await db.commit()
    return count


async def get_faculty_sheet(db, institution_id, day, current_user):
    """Teachers at an institution with their attendance for a given day."""
    if not _is_admin(current_user) and institution_id != current_user.institution_id:
        raise NotFoundError("Institution not found.")

    teachers = (await db.execute(
        select(User).where(
            User.institution_id == institution_id,
            User.role == UserRole.TEACHER,
            User.is_active.is_(True),
        ).order_by(User.full_name)
    )).scalars().all()

    existing = (await db.execute(
        select(FacultyAttendance).where(
            FacultyAttendance.institution_id == institution_id,
            FacultyAttendance.date == day,
        )
    )).scalars().all()
    by_user = {a.user_id: a for a in existing}

    rows = [
        {
            "teacher": t,
            "status": by_user[t.id].status.value if t.id in by_user else None,
            "leave_type": (
                by_user[t.id].leave_type.value
                if t.id in by_user and by_user[t.id].leave_type else None
            ),
        }
        for t in teachers
    ]
    return {"date": day, "rows": rows, "leave_types": [l.value for l in LeaveType]}


# ── 6. faculty attendance summary ──────────────────────────────

async def get_faculty_attendance_summary(db, user_id, month, year, current_user):
    teacher = await db.get(User, user_id)
    if not teacher:
        raise NotFoundError("Teacher not found.")
    if not _is_admin(current_user) and teacher.institution_id != current_user.institution_id:
        raise NotFoundError("Teacher not found.")

    days_in_month = _cal.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    records = (await db.execute(
        select(FacultyAttendance).where(
            FacultyAttendance.user_id == user_id,
            FacultyAttendance.date >= start,
            FacultyAttendance.date <= end,
        )
    )).scalars().all()

    present = sum(1 for r in records if r.status == FacultyAttendanceStatus.PRESENT)
    absent = sum(1 for r in records if r.status == FacultyAttendanceStatus.ABSENT)
    late = sum(1 for r in records if r.status == FacultyAttendanceStatus.LATE)
    on_leave = sum(1 for r in records if r.status == FacultyAttendanceStatus.ON_LEAVE)

    return {
        "teacher": teacher,
        "month": month,
        "year": year,
        "present": present,
        "absent": absent,
        "late": late,
        "on_leave": on_leave,
        "total_marked": len(records),
    }


# ── 7. low attendance students ─────────────────────────────────

async def get_low_attendance_students(db, institution_id, threshold=75, current_user=None):
    if institution_id is None and current_user and not _is_admin(current_user):
        institution_id = current_user.institution_id

    present_c = func.sum(case((StudentAttendance.status == StudentAttendanceStatus.PRESENT, 1), else_=0))
    late_c = func.sum(case((StudentAttendance.status == StudentAttendanceStatus.LATE, 1), else_=0))
    total_c = func.count(StudentAttendance.id)

    q = (
        select(
            Student.id, Student.full_name, Student.admission_number,
            ClassSection.grade, ClassSection.section,
            total_c, present_c, late_c,
        )
        .select_from(Student)
        .join(ClassSection, ClassSection.id == Student.class_section_id)
        .join(StudentAttendance, StudentAttendance.student_id == Student.id)
        .where(Student.is_active.is_(True))
        .group_by(
            Student.id, Student.full_name, Student.admission_number,
            ClassSection.grade, ClassSection.section,
        )
        .having(total_c > 0)
        .order_by(ClassSection.grade, ClassSection.section, Student.full_name)
    )
    if institution_id:
        q = q.where(Student.institution_id == institution_id)

    rows = (await db.execute(q)).all()
    out = []
    for sid, name, adm, grade, section, total, present, late in rows:
        total = int(total or 0)
        pct = _pct(int(present or 0), int(late or 0), total)
        if pct < threshold:
            out.append({
                "student_id": sid,
                "full_name": name,
                "admission_number": adm,
                "grade": grade,
                "section": section,
                "class_label": f"{grade} - {section}",
                "percentage": pct,
                "total": total,
            })
    return out


# ── landing page data ──────────────────────────────────────────

async def list_sections_with_status(db, current_user, day):
    """Class sections (scoped) with student counts and whether today is marked."""
    q = (
        select(ClassSection)
        .options(selectinload(ClassSection.institution))
        .order_by(ClassSection.grade, ClassSection.section)
    )
    if not _is_admin(current_user):
        q = q.where(ClassSection.institution_id == current_user.institution_id)
    sections = (await db.execute(q)).scalars().all()

    counts = dict((await db.execute(
        select(Student.class_section_id, func.count(Student.id))
        .where(Student.is_active.is_(True))
        .group_by(Student.class_section_id)
    )).all())

    marked = set((await db.execute(
        select(StudentAttendance.class_section_id)
        .where(StudentAttendance.date == day)
        .distinct()
    )).scalars().all())

    return [
        {
            "section": s,
            "student_count": int(counts.get(s.id, 0)),
            "marked_today": s.id in marked,
        }
        for s in sections
    ]


# ── Excel export (class × month) ───────────────────────────────

_CHAR = {"PRESENT": "P", "ABSENT": "A", "LATE": "L", "EXCUSED": "E"}


async def export_class_month_excel(db, class_section_id, month, year, current_user):
    section = await _load_section(db, class_section_id, current_user)
    days_in_month = _cal.monthrange(year, month)[1]
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    students = (await db.execute(
        select(Student)
        .where(Student.class_section_id == class_section_id, Student.is_active.is_(True))
        .order_by(Student.full_name)
    )).scalars().all()

    records = (await db.execute(
        select(StudentAttendance).where(
            StudentAttendance.class_section_id == class_section_id,
            StudentAttendance.date >= start,
            StudentAttendance.date <= end,
        )
    )).scalars().all()
    grid = {(r.student_id, r.date.day): _CHAR.get(r.status.value, "") for r in records}

    wb = Workbook()
    ws = wb.active
    ws.title = f"{section.grade}-{section.section} {year}-{month:02d}"
    header = ["Admission No", "Name"] + [str(d) for d in range(1, days_in_month + 1)]
    ws.append(header)
    for s in students:
        row = [s.admission_number, s.full_name]
        row += [grid.get((s.id, d), "") for d in range(1, days_in_month + 1)]
        ws.append(row)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    fname = f"attendance_{section.grade}{section.section}_{year}_{month:02d}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )
