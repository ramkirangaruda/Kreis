"""Background tasks (Celery)."""

import asyncio
from datetime import date, timedelta

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.ocr import extract_text_bhashini
from app.models.document import UploadedDocument, OcrStatus, AttendanceRollup
from app.models.student import Student
from app.models.attendance import StudentAttendance, StudentAttendanceStatus


def _new_session():
    """Throwaway NullPool engine + sessionmaker for use inside asyncio.run."""
    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        },
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@celery_app.task(name="app.tasks.process_ocr")
def process_ocr(document_id: int, file_path: str):
    """Extract OCR text for an uploaded document and update its record.

    Each task runs in its own event loop (asyncio.run), so it must NOT reuse
    the app's shared connection pool — those asyncpg connections are bound to
    a different loop. We build a throwaway NullPool engine per invocation and
    dispose it at the end.
    """

    async def run():
        engine, Session = _new_session()
        try:
            async with Session() as db:
                doc = await db.get(UploadedDocument, document_id)
                if not doc:
                    return

                doc.ocr_status = OcrStatus.PROCESSING
                await db.commit()

                text = await extract_text_bhashini(file_path)

                doc.ocr_text = text
                doc.ocr_status = (
                    OcrStatus.FAILED if text.startswith("[") else OcrStatus.DONE
                )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(run())


@celery_app.task(name="app.tasks.update_attendance_rollups")
def update_attendance_rollups(month: int | None = None, year: int | None = None):
    """Recalculate monthly attendance rollups.

    Defaults to the month containing yesterday (the "previous day"), recomputing
    the full month so the rollup always reflects every recorded day. Idempotent.
    """
    target = date.today() - timedelta(days=1)
    m = month or target.month
    y = year or target.year

    async def run():
        engine, Session = _new_session()
        try:
            async with Session() as db:
                present_c = func.sum(case(
                    (StudentAttendance.status == StudentAttendanceStatus.PRESENT, 1), else_=0))
                absent_c = func.sum(case(
                    (StudentAttendance.status == StudentAttendanceStatus.ABSENT, 1), else_=0))
                late_c = func.sum(case(
                    (StudentAttendance.status == StudentAttendanceStatus.LATE, 1), else_=0))
                total_c = func.count(StudentAttendance.id)

                rows = (await db.execute(
                    select(
                        Student.id, Student.institution_id,
                        total_c, present_c, absent_c, late_c,
                    )
                    .join(StudentAttendance, StudentAttendance.student_id == Student.id)
                    .where(
                        func.extract("month", StudentAttendance.date) == m,
                        func.extract("year", StudentAttendance.date) == y,
                    )
                    .group_by(Student.id, Student.institution_id)
                )).all()

                count = 0
                for sid, inst_id, total, present, absent, late in rows:
                    total = int(total or 0)
                    present = int(present or 0)
                    absent = int(absent or 0)
                    late = int(late or 0)
                    pct = round((present + late) / total * 100, 1) if total else 0.0

                    existing = (await db.execute(
                        select(AttendanceRollup).where(
                            AttendanceRollup.student_id == sid,
                            AttendanceRollup.month == m,
                            AttendanceRollup.year == y,
                        )
                    )).scalar_one_or_none()
                    if existing:
                        existing.institution_id = inst_id
                        existing.total_days = total
                        existing.present_days = present
                        existing.absent_days = absent
                        existing.late_days = late
                        existing.percentage = pct
                    else:
                        db.add(AttendanceRollup(
                            student_id=sid, institution_id=inst_id,
                            month=m, year=y, total_days=total,
                            present_days=present, absent_days=absent,
                            late_days=late, percentage=pct,
                        ))
                    count += 1
                await db.commit()
                return count
        finally:
            await engine.dispose()

    return asyncio.run(run())
