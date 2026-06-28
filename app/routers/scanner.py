"""Face-scanner webhook API.

Pure JSON API (no templates, no JWT). The scanner device authenticates with a
shared API key and posts a recognition event; we record attendance for the
matched student or teacher.
"""

from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings

from app.models.institution import Institution
from app.models.user import User, UserRole
from app.models.student import Student, ClassSection
from app.models.attendance import (
    StudentAttendance, StudentAttendanceStatus,
    FacultyAttendance, FacultyAttendanceStatus,
)
from app.models.document import ScannerDevice

router = APIRouter()


class ScannerEvent(BaseModel):
    api_key: str
    device_id: str
    person_id: str
    person_type: str
    timestamp: str
    institution_code: str


@router.get("/test")
async def scanner_test():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


def _status_for_time(t: time):
    """Before 9am ⇒ present, otherwise late."""
    return t < time(9, 0)


@router.post("/attendance")
async def scanner_attendance(
    event: ScannerEvent,
    db: AsyncSession = Depends(get_db),
):
    if event.api_key != settings.scanner_api_key:
        raise HTTPException(status_code=401, detail="Invalid scanner API key")

    inst = (await db.execute(
        select(Institution).where(Institution.code == event.institution_code)
    )).scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")

    try:
        ts = datetime.fromisoformat(event.timestamp)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid timestamp")
    the_date = ts.date()
    before_nine = _status_for_time(ts.time())

    # Touch the device's last_seen on every recognized ping.
    device = (await db.execute(
        select(ScannerDevice).where(ScannerDevice.device_id == event.device_id)
    )).scalar_one_or_none()
    if device:
        device.last_seen = datetime.utcnow()

    person_type = event.person_type.upper()

    if person_type == "STUDENT":
        student = (await db.execute(
            select(Student).where(
                Student.admission_number == event.person_id,
                Student.institution_id == inst.id,
            )
        )).scalar_one_or_none()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found")

        status = (
            StudentAttendanceStatus.PRESENT if before_nine
            else StudentAttendanceStatus.LATE
        )
        marker = await _marker_user(db, inst.id)
        existing = (await db.execute(
            select(StudentAttendance).where(
                StudentAttendance.student_id == student.id,
                StudentAttendance.date == the_date,
            )
        )).scalar_one_or_none()
        if existing:
            existing.status = status
            existing.marked_by_id = marker
        else:
            db.add(StudentAttendance(
                student_id=student.id,
                class_section_id=student.class_section_id,
                date=the_date,
                status=status,
                marked_by_id=marker,
            ))
        await db.commit()
        return {"success": True, "person_name": student.full_name, "status": status.value}

    elif person_type == "FACULTY":
        teacher = (await db.execute(
            select(User).where(
                User.institution_id == inst.id,
                User.role == UserRole.TEACHER,
                User.email == event.person_id,
            )
        )).scalar_one_or_none()
        # Fallback: numeric person_id matching the user id.
        if not teacher and event.person_id.isdigit():
            teacher = (await db.execute(
                select(User).where(
                    User.id == int(event.person_id),
                    User.institution_id == inst.id,
                    User.role == UserRole.TEACHER,
                )
            )).scalar_one_or_none()
        if not teacher:
            raise HTTPException(status_code=404, detail="Teacher not found")

        status = (
            FacultyAttendanceStatus.PRESENT if before_nine
            else FacultyAttendanceStatus.LATE
        )
        existing = (await db.execute(
            select(FacultyAttendance).where(
                FacultyAttendance.user_id == teacher.id,
                FacultyAttendance.date == the_date,
            )
        )).scalar_one_or_none()
        if existing:
            existing.status = status
            existing.scanner_verified = True
        else:
            db.add(FacultyAttendance(
                user_id=teacher.id,
                institution_id=inst.id,
                date=the_date,
                status=status,
                scanner_verified=True,
            ))
        await db.commit()
        return {"success": True, "person_name": teacher.full_name, "status": status.value}

    raise HTTPException(status_code=400, detail="Invalid person_type")


async def _marker_user(db, institution_id: int) -> int:
    """Attribute scanner-marked student attendance to the school principal,
    falling back to a KREIS admin (the marked_by_id column is NOT NULL)."""
    principal = (await db.execute(
        select(User.id).where(
            User.institution_id == institution_id,
            User.role == UserRole.PRINCIPAL,
        ).limit(1)
    )).scalar_one_or_none()
    if principal:
        return principal
    admin = (await db.execute(
        select(User.id).where(User.role == UserRole.KREIS_ADMIN).limit(1)
    )).scalar_one_or_none()
    return admin
