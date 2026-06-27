"""Academics service layer — exams, marks, competitive results, timetable."""

import io
from datetime import datetime, timedelta, time

from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from openpyxl import Workbook
from fastapi.responses import StreamingResponse

from app.models.student import Student, ClassSection, AcademicYear
from app.models.user import User, UserRole
from app.models.academic import (
    Subject,
    Exam,
    ExamResult,
    CompetitiveExamResult,
    TimetableSlot,
    ExamType,
    CompetitiveExamName,
    DayOfWeek,
)
from app.services.audit import log_action


class NotFoundError(Exception):
    """Raised when an entity is missing or outside the caller's scope."""


PERIODS = list(range(1, 9))            # periods 1..8
DAYS = [d for d in DayOfWeek]          # Mon..Sat


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


def _pct(obtained, maximum) -> float:
    return round(obtained / maximum * 100, 1) if maximum else 0.0


def grade_for(pct: float) -> str:
    if pct >= 90:
        return "A+"
    if pct >= 75:
        return "A"
    if pct >= 60:
        return "B"
    if pct >= 45:
        return "C"
    if pct >= 35:
        return "D"
    return "F"


def _period_times(period: int) -> tuple[time, time]:
    base = datetime(2000, 1, 1, 9, 0)
    start = base + timedelta(minutes=45 * (period - 1))
    end = start + timedelta(minutes=45)
    return start.time(), end.time()


async def _load_exam(db, exam_id, current_user):
    exam = (await db.execute(
        select(Exam).options(selectinload(Exam.academic_year)).where(Exam.id == exam_id)
    )).scalar_one_or_none()
    if not exam:
        raise NotFoundError("Exam not found.")
    if current_user and not _is_admin(current_user) and exam.institution_id != current_user.institution_id:
        raise NotFoundError("Exam not found.")
    return exam


async def _current_ay(db, institution_id):
    return (await db.execute(
        select(AcademicYear).where(
            AcademicYear.institution_id == institution_id,
            AcademicYear.is_current.is_(True),
        )
    )).scalar_one_or_none()


async def list_subjects_for_class(db, class_section_id):
    """Subjects for a class: those assigned to it plus school-wide ones."""
    section = await db.get(ClassSection, class_section_id)
    if not section:
        return []
    return (await db.execute(
        select(Subject)
        .where(
            Subject.institution_id == section.institution_id,
            or_(
                Subject.class_section_id == class_section_id,
                Subject.class_section_id.is_(None),
            ),
        )
        .order_by(Subject.name)
    )).scalars().all()


# ── 1/2. exams ─────────────────────────────────────────────────

async def list_exams(db, institution_id, academic_year_id=None, current_user=None):
    q = select(Exam).order_by(Exam.start_date.desc())
    if institution_id:
        q = q.where(Exam.institution_id == institution_id)
    if academic_year_id:
        q = q.where(Exam.academic_year_id == academic_year_id)
    return (await db.execute(q)).scalars().all()


async def create_exam(db, data, current_user, ip=None):
    institution_id = data.get("institution_id") or current_user.institution_id
    if not institution_id:
        raise ValueError("An institution is required to create an exam.")
    if not _is_admin(current_user) and institution_id != current_user.institution_id:
        raise ValueError("You cannot create exams for another institution.")

    academic_year_id = data.get("academic_year_id")
    if not academic_year_id:
        ay = await _current_ay(db, institution_id)
        if not ay:
            raise ValueError("No current academic year set for this institution.")
        academic_year_id = ay.id

    exam_type = _enum_or_none(ExamType, data.get("exam_type"))
    if exam_type is None:
        raise ValueError("A valid exam type is required.")

    exam = Exam(
        institution_id=institution_id,
        academic_year_id=academic_year_id,
        name=data["name"].strip(),
        exam_type=exam_type,
        start_date=data["start_date"],
        end_date=data["end_date"],
    )
    db.add(exam)
    await db.flush()
    await log_action(
        db=db, user_id=current_user.id, action="CREATE_EXAM",
        entity="Exam", entity_id=exam.id,
        details={"name": exam.name, "type": exam_type.value}, ip_address=ip,
    )
    await db.commit()
    return exam


# ── 3. exam results (with rank) ────────────────────────────────

async def get_exam_results(db, exam_id, class_section_id=None, current_user=None):
    exam = await _load_exam(db, exam_id, current_user)

    q = (
        select(ExamResult, Student, Subject)
        .join(Student, Student.id == ExamResult.student_id)
        .join(Subject, Subject.id == ExamResult.subject_id)
        .where(ExamResult.exam_id == exam_id)
    )
    if class_section_id:
        q = q.where(Student.class_section_id == class_section_id)
    rows = (await db.execute(q)).all()

    subjects: dict = {}
    students: dict = {}
    for res, student, subject in rows:
        subjects.setdefault(subject.id, subject.name)
        s = students.setdefault(student.id, {
            "student": student, "marks": {}, "total_obtained": 0.0, "total_max": 0.0,
        })
        pct = _pct(res.marks_obtained, res.max_marks)
        s["marks"][subject.id] = {
            "obtained": res.marks_obtained,
            "max": res.max_marks,
            "percentage": pct,
            "grade": res.grade or grade_for(pct),
            "is_absent": res.is_absent,
            "is_pass": (not res.is_absent) and pct >= 35,
        }
        if not res.is_absent:
            s["total_obtained"] += res.marks_obtained
            s["total_max"] += res.max_marks

    subject_list = [{"id": sid, "name": name} for sid, name in
                    sorted(subjects.items(), key=lambda kv: kv[1])]

    student_rows = list(students.values())
    for s in student_rows:
        s["percentage"] = _pct(s["total_obtained"], s["total_max"])
    student_rows.sort(key=lambda r: r["total_obtained"], reverse=True)

    # standard competition ranking on total_obtained
    rank = 0
    prev = None
    for i, s in enumerate(student_rows, start=1):
        if prev is None or s["total_obtained"] != prev:
            rank = i
            prev = s["total_obtained"]
        s["rank"] = rank

    student_rows.sort(key=lambda r: r["student"].full_name)
    return {
        "exam": exam,
        "subjects": subject_list,
        "rows": student_rows,
        "class_section_id": class_section_id,
    }


# ── 4. enter results ───────────────────────────────────────────

async def enter_exam_results(db, exam_id, results, current_user, ip=None):
    exam = await _load_exam(db, exam_id, current_user)

    existing = (await db.execute(
        select(ExamResult).where(ExamResult.exam_id == exam_id)
    )).scalars().all()
    by_key = {(r.student_id, r.subject_id): r for r in existing}

    count = 0
    for rec in results:
        sid = int(rec["student_id"])
        subj = int(rec["subject_id"])
        is_absent = bool(rec.get("is_absent"))
        max_marks = float(rec.get("max_marks") or 0)
        obtained = 0.0 if is_absent else float(rec.get("marks_obtained") or 0)
        pct = _pct(obtained, max_marks)
        grade = "AB" if is_absent else grade_for(pct)

        row = by_key.get((sid, subj))
        if row:
            row.marks_obtained = obtained
            row.max_marks = max_marks
            row.is_absent = is_absent
            row.grade = grade
        else:
            db.add(ExamResult(
                student_id=sid, exam_id=exam_id, subject_id=subj,
                marks_obtained=obtained, max_marks=max_marks,
                is_absent=is_absent, grade=grade,
            ))
        count += 1

    await log_action(
        db=db, user_id=current_user.id, action="ENTER_EXAM_RESULTS",
        entity="Exam", entity_id=exam_id, details={"records": count}, ip_address=ip,
    )
    await db.commit()
    return count


# ── 5. low performers ──────────────────────────────────────────

async def get_low_performers(db, institution_id, exam_id=None, threshold=35, current_user=None):
    if institution_id is None and current_user and not _is_admin(current_user):
        institution_id = current_user.institution_id

    q = (
        select(ExamResult, Student, Subject, ClassSection, Exam)
        .join(Student, Student.id == ExamResult.student_id)
        .join(Subject, Subject.id == ExamResult.subject_id)
        .join(ClassSection, ClassSection.id == Student.class_section_id)
        .join(Exam, Exam.id == ExamResult.exam_id)
        .where(ExamResult.is_absent.is_(False))
    )
    if institution_id:
        q = q.where(Student.institution_id == institution_id)
    if exam_id:
        q = q.where(ExamResult.exam_id == exam_id)

    rows = (await db.execute(q)).all()

    by_student: dict = {}
    for res, student, subject, section, exam in rows:
        pct = _pct(res.marks_obtained, res.max_marks)
        if pct >= threshold:
            continue
        entry = by_student.setdefault(student.id, {
            "student": student,
            "class_label": f"{section.grade} - {section.section}",
            "grade": section.grade,
            "section": section.section,
            "flagged": [],
        })
        entry["flagged"].append({
            "subject": subject.name,
            "exam": exam.name,
            "obtained": res.marks_obtained,
            "max": res.max_marks,
            "percentage": pct,
        })

    grouped: dict = {}
    for entry in by_student.values():
        grouped.setdefault(entry["class_label"], []).append(entry)
    for items in grouped.values():
        items.sort(key=lambda e: e["student"].full_name)
    return dict(sorted(grouped.items()))


# ── 6/7. competitive results ───────────────────────────────────

async def create_competitive_result(db, data, current_user, ip=None):
    student = await db.get(Student, int(data["student_id"]))
    if not student:
        raise ValueError("Student not found.")
    if not _is_admin(current_user) and student.institution_id != current_user.institution_id:
        raise ValueError("Student is outside your institution.")

    exam_name = _enum_or_none(CompetitiveExamName, data.get("exam_name"))
    if exam_name is None:
        raise ValueError("A valid exam is required.")

    def _int(v):
        try:
            return int(v) if v not in (None, "") else None
        except (ValueError, TypeError):
            return None

    def _float(v):
        try:
            return float(v) if v not in (None, "") else None
        except (ValueError, TypeError):
            return None

    result = CompetitiveExamResult(
        student_id=student.id,
        exam_name=exam_name,
        exam_year=int(data["exam_year"]),
        roll_number=(data.get("roll_number") or "").strip() or None,
        rank=_int(data.get("rank")),
        score=_float(data.get("score")),
        qualified=bool(data.get("qualified")),
        notes=(data.get("notes") or "").strip() or None,
    )
    db.add(result)
    await db.flush()
    await log_action(
        db=db, user_id=current_user.id, action="CREATE_COMPETITIVE_RESULT",
        entity="CompetitiveExamResult", entity_id=result.id,
        details={"exam": exam_name.value, "student_id": student.id}, ip_address=ip,
    )
    await db.commit()
    return result


async def list_competitive_results(db, institution_id=None, exam_name=None, year=None):
    q = (
        select(CompetitiveExamResult, Student)
        .join(Student, Student.id == CompetitiveExamResult.student_id)
        .order_by(CompetitiveExamResult.exam_year.desc(), CompetitiveExamResult.rank)
    )
    if institution_id:
        q = q.where(Student.institution_id == institution_id)
    en = _enum_or_none(CompetitiveExamName, exam_name)
    if en:
        q = q.where(CompetitiveExamResult.exam_name == en)
    if year:
        q = q.where(CompetitiveExamResult.exam_year == int(year))
    rows = (await db.execute(q)).all()
    return [{"result": r, "student": s} for r, s in rows]


# ── 8/9. timetable ─────────────────────────────────────────────

async def get_timetable(db, class_section_id):
    slots = (await db.execute(
        select(TimetableSlot)
        .options(selectinload(TimetableSlot.subject), selectinload(TimetableSlot.teacher))
        .where(TimetableSlot.class_section_id == class_section_id)
    )).scalars().all()
    grid = {(s.day_of_week.value, s.period_number): s for s in slots}
    return grid


async def save_timetable(db, class_section_id, slots, current_user, ip=None):
    section = await db.get(ClassSection, class_section_id)
    if not section:
        raise NotFoundError("Class section not found.")
    if not _is_admin(current_user) and section.institution_id != current_user.institution_id:
        raise NotFoundError("Class section not found.")

    # Cross-class double-booking check: a teacher cannot be in two class
    # sections at the same day + period.
    for slot in slots:
        teacher_id = slot.get("teacher_id")
        if not teacher_id:
            continue
        day = _enum_or_none(DayOfWeek, slot["day_of_week"])
        clash = (await db.execute(
            select(TimetableSlot, ClassSection)
            .join(ClassSection, ClassSection.id == TimetableSlot.class_section_id)
            .where(
                TimetableSlot.teacher_id == int(teacher_id),
                TimetableSlot.day_of_week == day,
                TimetableSlot.period_number == int(slot["period_number"]),
                TimetableSlot.class_section_id != class_section_id,
            )
        )).first()
        if clash:
            other = clash[1]
            raise ValueError(
                f"Teacher already booked for {day.value.capitalize()} period "
                f"{slot['period_number']} in class {other.grade}-{other.section}."
            )

    # Replace all slots for this class section.
    await db.execute(
        TimetableSlot.__table__.delete().where(
            TimetableSlot.class_section_id == class_section_id
        )
    )

    count = 0
    for slot in slots:
        subject_id = slot.get("subject_id")
        teacher_id = slot.get("teacher_id")
        if not subject_id and not teacher_id:
            continue
        day = _enum_or_none(DayOfWeek, slot["day_of_week"])
        period = int(slot["period_number"])
        start, end = _period_times(period)
        db.add(TimetableSlot(
            class_section_id=class_section_id,
            day_of_week=day,
            period_number=period,
            subject_id=int(subject_id) if subject_id else None,
            teacher_id=int(teacher_id) if teacher_id else None,
            start_time=start,
            end_time=end,
        ))
        count += 1

    await log_action(
        db=db, user_id=current_user.id, action="SAVE_TIMETABLE",
        entity="ClassSection", entity_id=class_section_id,
        details={"slots": count}, ip_address=ip,
    )
    await db.commit()
    return count


# ── 10. marks card ─────────────────────────────────────────────

async def get_marks_card(db, student_id, exam_id, current_user=None):
    student = (await db.execute(
        select(Student)
        .options(
            selectinload(Student.institution),
            selectinload(Student.class_section),
        )
        .where(Student.id == student_id)
    )).scalar_one_or_none()
    if not student:
        raise NotFoundError("Student not found.")
    if current_user and not _is_admin(current_user) and student.institution_id != current_user.institution_id:
        raise NotFoundError("Student not found.")

    data = await get_exam_results(db, exam_id, student.class_section_id, current_user)
    exam = data["exam"]
    subjects = data["subjects"]

    my_row = next((r for r in data["rows"] if r["student"].id == student_id), None)

    lines = []
    total_obtained = 0.0
    total_max = 0.0
    if my_row:
        for subj in subjects:
            m = my_row["marks"].get(subj["id"])
            if not m:
                continue
            lines.append({
                "subject": subj["name"],
                "max": m["max"],
                "obtained": m["obtained"],
                "grade": m["grade"],
                "is_absent": m["is_absent"],
            })
            if not m["is_absent"]:
                total_obtained += m["obtained"]
                total_max += m["max"]

    percentage = _pct(total_obtained, total_max)
    return {
        "student": student,
        "exam": exam,
        "lines": lines,
        "total_obtained": total_obtained,
        "total_max": total_max,
        "percentage": percentage,
        "overall_grade": grade_for(percentage),
        "rank": my_row["rank"] if my_row else None,
        "class_size": len(data["rows"]),
    }


# ── results Excel export ───────────────────────────────────────

async def export_exam_results_excel(db, exam_id, class_section_id=None, current_user=None):
    data = await get_exam_results(db, exam_id, class_section_id, current_user)
    exam = data["exam"]
    subjects = data["subjects"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    header = ["Admission No", "Student"] + [s["name"] for s in subjects] + ["Total", "%", "Rank"]
    ws.append(header)
    for r in data["rows"]:
        row = [r["student"].admission_number, r["student"].full_name]
        for s in subjects:
            m = r["marks"].get(s["id"])
            if not m:
                row.append("")
            elif m["is_absent"]:
                row.append("AB")
            else:
                row.append(f'{int(m["obtained"])}/{int(m["max"])}')
        row += [int(r["total_obtained"]), r["percentage"], r["rank"]]
        ws.append(row)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    fname = f"results_{exam.name.replace(' ', '_')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ── teacher list (for timetable / forms) ───────────────────────

async def list_teachers(db, institution_id):
    if not institution_id:
        return []
    return (await db.execute(
        select(User).where(
            User.institution_id == institution_id,
            User.role == UserRole.TEACHER,
            User.is_active.is_(True),
        ).order_by(User.full_name)
    )).scalars().all()
