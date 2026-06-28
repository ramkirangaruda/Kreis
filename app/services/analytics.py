"""Cross-school analytics for KREIS admins."""

from datetime import date

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.institution import Institution
from app.models.student import Student, StudentDemographics, ClassSection, CasteCategory
from app.models.attendance import StudentAttendance, StudentAttendanceStatus
from app.models.academic import Exam, ExamResult, CompetitiveExamResult
from app.models.inventory import InventoryItem
from app.models.document import Circular, CircularAcknowledgement, AttendanceRollup


def _pct(num, den):
    return round(num / den * 100, 1) if den else 0.0


async def get_cross_school_analytics(db: AsyncSession) -> dict:
    today = date.today()

    institutions = (await db.execute(
        select(Institution).where(Institution.is_active.is_(True)).order_by(Institution.name)
    )).scalars().all()

    # ── Today's attendance rate per institution ──
    present_c = func.sum(case(
        (StudentAttendance.status.in_(
            [StudentAttendanceStatus.PRESENT, StudentAttendanceStatus.LATE]), 1), else_=0))
    total_c = func.count(StudentAttendance.id)
    today_rows = dict()
    rows = (await db.execute(
        select(Student.institution_id, present_c, total_c)
        .join(StudentAttendance, StudentAttendance.student_id == Student.id)
        .where(StudentAttendance.date == today)
        .group_by(Student.institution_id)
    )).all()
    for inst_id, pres, tot in rows:
        today_rows[inst_id] = _pct(int(pres or 0), int(tot or 0))

    # ── Monthly average from rollups (current month) ──
    monthly = dict()
    mrows = (await db.execute(
        select(AttendanceRollup.institution_id, func.avg(AttendanceRollup.percentage))
        .where(AttendanceRollup.month == today.month, AttendanceRollup.year == today.year)
        .group_by(AttendanceRollup.institution_id)
    )).all()
    for inst_id, avg in mrows:
        monthly[inst_id] = round(float(avg), 1) if avg is not None else 0.0

    # ── Student totals + caste breakdown ──
    caste_rows = (await db.execute(
        select(Student.institution_id, StudentDemographics.caste_category, func.count(Student.id))
        .join(StudentDemographics, StudentDemographics.student_id == Student.id)
        .where(Student.is_active.is_(True))
        .group_by(Student.institution_id, StudentDemographics.caste_category)
    )).all()
    caste_by_inst = {}
    total_by_inst = {}
    for inst_id, cc, n in caste_rows:
        caste_by_inst.setdefault(inst_id, {c.value: 0 for c in CasteCategory})
        caste_by_inst[inst_id][cc.value] = n
        total_by_inst[inst_id] = total_by_inst.get(inst_id, 0) + n

    # ── Low-stock counts per institution ──
    low_rows = (await db.execute(
        select(InventoryItem.institution_id, func.count(InventoryItem.id))
        .where(InventoryItem.quantity_available <= InventoryItem.low_stock_threshold)
        .group_by(InventoryItem.institution_id)
    )).all()
    low_by_inst = {inst_id: n for inst_id, n in low_rows}

    # ── Academic: average % in each school's most recent exam ──
    academics = {}
    for inst in institutions:
        latest = (await db.execute(
            select(Exam).where(Exam.institution_id == inst.id)
            .order_by(Exam.start_date.desc()).limit(1)
        )).scalar_one_or_none()
        if not latest:
            academics[inst.id] = {"exam": "—", "avg_pct": None}
            continue
        avg = (await db.execute(
            select(func.avg(ExamResult.marks_obtained / ExamResult.max_marks * 100))
            .where(ExamResult.exam_id == latest.id, ExamResult.is_absent.is_(False))
        )).scalar()
        academics[inst.id] = {
            "exam": latest.name,
            "avg_pct": round(float(avg), 1) if avg is not None else None,
        }

    # ── Competitive qualification by school × exam × year ──
    comp_rows = (await db.execute(
        select(
            Student.institution_id, CompetitiveExamResult.exam_name,
            CompetitiveExamResult.exam_year,
            func.count(CompetitiveExamResult.id),
            func.sum(case((CompetitiveExamResult.qualified.is_(True), 1), else_=0)),
        )
        .join(Student, Student.id == CompetitiveExamResult.student_id)
        .group_by(Student.institution_id, CompetitiveExamResult.exam_name, CompetitiveExamResult.exam_year)
        .order_by(CompetitiveExamResult.exam_year.desc())
    )).all()
    comp_by_inst = {}
    for inst_id, ename, yr, total, qual in comp_rows:
        comp_by_inst.setdefault(inst_id, []).append({
            "exam": ename.value, "year": yr,
            "qualified": int(qual or 0), "total": int(total or 0),
            "rate": _pct(int(qual or 0), int(total or 0)),
        })

    # ── Circular acknowledgement: last 3 circulars ──
    last_circulars = (await db.execute(
        select(Circular).order_by(Circular.created_at.desc()).limit(3)
    )).scalars().all()
    circ_ids = [c.id for c in last_circulars]
    acked_pairs = set()
    if circ_ids:
        acked_pairs = set((await db.execute(
            select(CircularAcknowledgement.circular_id, CircularAcknowledgement.institution_id)
            .where(CircularAcknowledgement.circular_id.in_(circ_ids))
        )).all())

    # ── Assemble per-school view ──
    schools = []
    for inst in institutions:
        pending = [
            c.title for c in last_circulars
            if c.institution_id in (None, inst.id) and (c.id, inst.id) not in acked_pairs
        ]
        schools.append({
            "id": inst.id, "name": inst.name, "code": inst.code,
            "today_rate": today_rows.get(inst.id, 0.0),
            "monthly_avg": monthly.get(inst.id, 0.0),
            "student_total": total_by_inst.get(inst.id, 0),
            "caste": caste_by_inst.get(inst.id, {c.value: 0 for c in CasteCategory}),
            "low_stock": low_by_inst.get(inst.id, 0),
            "academics": academics.get(inst.id, {"exam": "—", "avg_pct": None}),
            "competitive": comp_by_inst.get(inst.id, []),
            "pending_circulars": pending,
        })

    return {
        "schools": schools,
        "last_circulars": [{"id": c.id, "title": c.title} for c in last_circulars],
        "castes": [c.value for c in CasteCategory],
    }
