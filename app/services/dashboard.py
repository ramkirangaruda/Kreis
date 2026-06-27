"""Dashboard statistics service.

The headline figures are gathered concurrently with asyncio.gather(). A
SQLAlchemy AsyncSession is *not* safe for concurrent use, so each gathered
coroutine opens its own short-lived session from AsyncSessionLocal — every
session draws an independent connection from the engine pool, which lets the
queries genuinely run in parallel.
"""

import asyncio
from datetime import datetime, timedelta, timezone, date

from sqlalchemy import select, func, case, or_
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.asset import Asset, AssetCategory
from app.models.institution import Institution
from app.models.inventory import InventoryItem, AssetMovement, MovementType
from app.models.user import User
from app.models.student import Student, ClassSection, AcademicYear
from app.models.attendance import StudentAttendance, StudentAttendanceStatus
from app.models.academic import Exam, ExamResult
from app.models.document import Circular, CircularAcknowledgement
from app.models.audit_log import AuditLog


async def _count_active_institutions(is_admin: bool) -> int:
    if not is_admin:
        # A principal / staff member only ever sees their own institution.
        return 1
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count(Institution.id)).where(
                Institution.is_active.is_(True)
            )
        )
        return result.scalar() or 0


async def _total_quantity(is_admin: bool, institution_id: int | None) -> int:
    async with AsyncSessionLocal() as db:
        query = select(func.coalesce(func.sum(InventoryItem.quantity_total), 0))
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return result.scalar() or 0


async def _low_stock_items(is_admin: bool, institution_id: int | None):
    async with AsyncSessionLocal() as db:
        query = (
            select(InventoryItem)
            .options(
                selectinload(InventoryItem.asset),
                selectinload(InventoryItem.institution),
            )
            .where(
                InventoryItem.quantity_available
                <= InventoryItem.low_stock_threshold
            )
            .order_by(InventoryItem.quantity_available.asc())
        )
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return list(result.scalars().all())


async def _pending_transfers(is_admin: bool, institution_id: int | None) -> int:
    """Count TRANSFER movements in the last 7 days that have no matching
    RECEIPT — i.e. stock that left a school but was never received."""
    async with AsyncSessionLocal() as db:
        # created_at is stored naive (UTC); compare against a naive cutoff.
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

        transfers_q = select(AssetMovement).where(
            AssetMovement.movement_type == MovementType.TRANSFER,
            AssetMovement.created_at >= cutoff,
        )
        receipts_q = select(AssetMovement).where(
            AssetMovement.movement_type == MovementType.RECEIPT,
            AssetMovement.created_at >= cutoff,
        )
        if not is_admin:
            transfers_q = transfers_q.where(
                AssetMovement.from_institution == institution_id
            )

        transfers = (await db.execute(transfers_q)).scalars().all()
        receipts = (await db.execute(receipts_q)).scalars().all()

        receipt_keys = {
            (r.from_institution, r.to_institution, r.quantity)
            for r in receipts
        }
        return sum(
            1
            for t in transfers
            if (t.from_institution, t.to_institution, t.quantity)
            not in receipt_keys
        )


async def _category_breakdown(is_admin: bool, institution_id: int | None):
    async with AsyncSessionLocal() as db:
        query = (
            select(
                AssetCategory.name,
                func.coalesce(func.sum(InventoryItem.quantity_total), 0),
                func.count(InventoryItem.id),
            )
            .select_from(AssetCategory)
            .join(Asset, Asset.category_id == AssetCategory.id)
            .join(InventoryItem, InventoryItem.asset_id == Asset.id)
            .group_by(AssetCategory.id, AssetCategory.name)
            .order_by(AssetCategory.code)
        )
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return [
            {"name": name, "total": int(total), "items": int(items)}
            for name, total, items in result.all()
        ]


async def _recent_movements(is_admin: bool, institution_id: int | None):
    async with AsyncSessionLocal() as db:
        query = (
            select(
                AssetMovement,
                Asset.name,
                Institution.name,
                User.full_name,
            )
            .join(
                InventoryItem,
                AssetMovement.inventory_item_id == InventoryItem.id,
            )
            .join(Asset, InventoryItem.asset_id == Asset.id)
            .join(Institution, InventoryItem.institution_id == Institution.id)
            .join(User, AssetMovement.performed_by_id == User.id)
            .order_by(AssetMovement.created_at.desc())
            .limit(10)
        )
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return [
            {
                "movement_type": movement.movement_type.value,
                "asset": asset_name,
                "institution": inst_name,
                "performed_by": user_name,
                "quantity": movement.quantity,
                "created_at": movement.created_at,
            }
            for movement, asset_name, inst_name, user_name in result.all()
        ]


# ── School ERP dashboard figures ───────────────────────────────

async def _count_students(is_admin, institution_id) -> int:
    async with AsyncSessionLocal() as db:
        q = select(func.count(Student.id)).where(Student.is_active.is_(True))
        if not is_admin:
            q = q.where(Student.institution_id == institution_id)
        return (await db.execute(q)).scalar() or 0


async def _today_attendance_rate(is_admin, institution_id) -> float:
    async with AsyncSessionLocal() as db:
        today = date.today()
        present_c = func.sum(case(
            (StudentAttendance.status.in_(
                [StudentAttendanceStatus.PRESENT, StudentAttendanceStatus.LATE]), 1),
            else_=0,
        ))
        total_c = func.count(StudentAttendance.id)
        q = (
            select(present_c, total_c)
            .join(Student, Student.id == StudentAttendance.student_id)
            .where(StudentAttendance.date == today)
        )
        if not is_admin:
            q = q.where(Student.institution_id == institution_id)
        present, total = (await db.execute(q)).one()
        present, total = int(present or 0), int(total or 0)
        return round(present / total * 100, 1) if total else 0.0


async def _low_attendance_count(is_admin, institution_id) -> int:
    async with AsyncSessionLocal() as db:
        present_c = func.sum(case((StudentAttendance.status == StudentAttendanceStatus.PRESENT, 1), else_=0))
        late_c = func.sum(case((StudentAttendance.status == StudentAttendanceStatus.LATE, 1), else_=0))
        total_c = func.count(StudentAttendance.id)
        q = (
            select(total_c, present_c, late_c)
            .select_from(Student)
            .join(StudentAttendance, StudentAttendance.student_id == Student.id)
            .where(Student.is_active.is_(True))
            .group_by(Student.id)
            .having(total_c > 0)
        )
        if not is_admin:
            q = q.where(Student.institution_id == institution_id)
        rows = (await db.execute(q)).all()
        return sum(
            1 for total, present, late in rows
            if (int(present or 0) + int(late or 0)) / int(total) * 100 < 75
        )


async def _low_performers_count(is_admin, institution_id) -> int:
    async with AsyncSessionLocal() as db:
        exam_q = select(Exam).order_by(Exam.start_date.desc())
        if not is_admin:
            exam_q = exam_q.where(Exam.institution_id == institution_id)
        latest = (await db.execute(exam_q.limit(1))).scalar_one_or_none()
        if not latest:
            return 0
        rows = (await db.execute(
            select(ExamResult.student_id, ExamResult.marks_obtained, ExamResult.max_marks)
            .where(ExamResult.exam_id == latest.id, ExamResult.is_absent.is_(False))
        )).all()
        flagged = {
            sid for sid, obtained, mx in rows
            if mx and (obtained / mx * 100) < 35
        }
        return len(flagged)


async def _pending_circulars_count(is_admin, institution_id) -> int:
    if is_admin or institution_id is None:
        return 0
    async with AsyncSessionLocal() as db:
        visible = set((await db.execute(
            select(Circular.id).where(or_(
                Circular.institution_id == institution_id,
                Circular.institution_id.is_(None),
            ))
        )).scalars().all())
        acked = set((await db.execute(
            select(CircularAcknowledgement.circular_id).where(
                CircularAcknowledgement.institution_id == institution_id
            )
        )).scalars().all())
        return len(visible - acked)


async def _upcoming_exams(is_admin, institution_id):
    async with AsyncSessionLocal() as db:
        today = date.today()
        q = select(Exam).where(Exam.start_date >= today).order_by(Exam.start_date).limit(3)
        if not is_admin:
            q = q.where(Exam.institution_id == institution_id)
        exams = (await db.execute(q)).scalars().all()
        return [
            {"name": e.name, "exam_type": e.exam_type.value, "start_date": e.start_date}
            for e in exams
        ]


async def _recent_activity(is_admin, institution_id):
    """Unified recent-activity feed sourced from the audit log."""
    async with AsyncSessionLocal() as db:
        q = (
            select(AuditLog, User.full_name)
            .join(User, User.id == AuditLog.user_id)
            .order_by(AuditLog.created_at.desc())
            .limit(12)
        )
        if not is_admin:
            q = q.where(User.institution_id == institution_id)
        rows = (await db.execute(q)).all()
        return [
            {
                "action": log.action,
                "entity": log.entity,
                "performed_by": name,
                "created_at": log.created_at,
            }
            for log, name in rows
        ]


async def get_dashboard_stats(db, current_user) -> dict:
    """Aggregate dashboard figures, scoped to the current user's role.

    `db` is accepted for interface consistency; the concurrent queries use
    their own sessions (see module docstring).
    """
    is_admin = current_user.role.value == "KREIS_ADMIN"
    institution_id = current_user.institution_id

    (
        total_institutions,
        total_assets,
        low_stock_items,
        pending_transfers,
        category_breakdown,
        recent_movements,
        total_students,
        today_attendance_rate,
        low_attendance_count,
        low_performers_count,
        pending_circulars_count,
        upcoming_exams,
        recent_activity,
    ) = await asyncio.gather(
        _count_active_institutions(is_admin),
        _total_quantity(is_admin, institution_id),
        _low_stock_items(is_admin, institution_id),
        _pending_transfers(is_admin, institution_id),
        _category_breakdown(is_admin, institution_id),
        _recent_movements(is_admin, institution_id),
        _count_students(is_admin, institution_id),
        _today_attendance_rate(is_admin, institution_id),
        _low_attendance_count(is_admin, institution_id),
        _low_performers_count(is_admin, institution_id),
        _pending_circulars_count(is_admin, institution_id),
        _upcoming_exams(is_admin, institution_id),
        _recent_activity(is_admin, institution_id),
    )

    grand_total = sum(row["total"] for row in category_breakdown)
    for row in category_breakdown:
        row["percentage"] = (
            round(row["total"] / grand_total * 100, 1) if grand_total else 0.0
        )

    return {
        "total_institutions": total_institutions,
        "total_assets": total_assets,
        "low_stock_count": len(low_stock_items),
        "low_stock_items": low_stock_items,
        "pending_transfers": pending_transfers,
        "category_breakdown": category_breakdown,
        "recent_movements": recent_movements,
        # ── School ERP ──
        "total_students": total_students,
        "today_attendance_rate": today_attendance_rate,
        "low_attendance_count": low_attendance_count,
        "low_performers_count": low_performers_count,
        "pending_circulars_count": pending_circulars_count,
        "upcoming_exams": upcoming_exams,
        "recent_activity": recent_activity,
    }
