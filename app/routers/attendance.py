"""Attendance routes — School ERP (students + faculty)."""

from datetime import date

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates

from app.models.user import User
from app.models.student import ClassSection
from app.models.attendance import StudentAttendanceStatus, FacultyAttendanceStatus

from app.services.attendance import (
    get_class_attendance_sheet,
    mark_student_attendance,
    get_student_attendance_summary,
    get_class_attendance_summary,
    mark_faculty_attendance,
    get_faculty_sheet,
    get_low_attendance_students,
    list_sections_with_status,
    export_class_month_excel,
    NotFoundError,
)

router = APIRouter()

_TEACHER = require_role(["KREIS_ADMIN", "PRINCIPAL", "TEACHER"])
_MANAGER = require_role(["KREIS_ADMIN", "PRINCIPAL"])


def _today() -> date:
    return date.today()


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value) if value else _today()
    except (ValueError, TypeError):
        return _today()


def _to_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except (ValueError, TypeError):
        return None


# ── Landing ────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def attendance_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = _today()
    sections = await list_sections_with_status(db, current_user, today)
    return templates.TemplateResponse(
        "attendance/index.html",
        {
            "request": request,
            "current_user": current_user,
            "sections": sections,
            "today": today,
        },
    )


# ── Mark student attendance ────────────────────────────────────

@router.get("/mark", response_class=HTMLResponse)
async def mark_sheet(
    request: Request,
    class_section_id: int,
    date: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_TEACHER),
):
    day = _parse_date(date)
    try:
        ctx = await get_class_attendance_sheet(db, class_section_id, day, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Class section not found")

    template = (
        "partials/attendance_sheet.html"
        if request.headers.get("HX-Request")
        else "attendance/mark.html"
    )
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "current_user": current_user,
            "statuses": [s.value for s in StudentAttendanceStatus],
            **ctx,
        },
    )


@router.post("/mark")
async def submit_attendance(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_TEACHER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    class_section_id = _to_int(form.get("class_section_id"))
    day = _parse_date(form.get("date", ""))
    if not class_section_id:
        raise HTTPException(status_code=400, detail="class_section_id required")

    records = []
    for key, value in form.items():
        if key.startswith("student_") and key.endswith("_status") and value:
            sid = key[len("student_"):-len("_status")]
            records.append({"student_id": sid, "status": value})

    try:
        await mark_student_attendance(
            db, records, class_section_id, day, current_user,
            ip=request.client.host if request.client else None,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Class section not found")

    return RedirectResponse(
        f"/attendance/mark?class_section_id={class_section_id}&date={day.isoformat()}"
        "&saved=1",
        status_code=303,
    )


# ── Student detail ─────────────────────────────────────────────

@router.get("/student/{student_id}", response_class=HTMLResponse)
async def student_attendance_detail(
    student_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        summary = await get_student_attendance_summary(db, student_id, None, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Student not found")
    return templates.TemplateResponse(
        "attendance/student_detail.html",
        {"request": request, "current_user": current_user, **summary},
    )


# ── Class report ───────────────────────────────────────────────

@router.get("/class/{class_section_id}", response_class=HTMLResponse)
async def class_report(
    class_section_id: int,
    request: Request,
    date_from: str = "",
    date_to: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_TEACHER),
):
    today = _today()
    d_from = _parse_date(date_from) if date_from else today.replace(day=1)
    d_to = _parse_date(date_to) if date_to else today

    try:
        ctx = await get_class_attendance_summary(
            db, class_section_id, d_from, d_to, current_user
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Class section not found")

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/class_report_table.html",
            {"request": request, "current_user": current_user, **ctx},
        )
    return templates.TemplateResponse(
        "attendance/class_report.html",
        {"request": request, "current_user": current_user, **ctx},
    )


# ── Faculty attendance ─────────────────────────────────────────

@router.get("/faculty", response_class=HTMLResponse)
async def faculty_page(
    request: Request,
    date: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    day = _parse_date(date)
    institution_id = current_user.institution_id
    if current_user.role.value == "KREIS_ADMIN":
        institution_id = _to_int(request.query_params.get("institution_id")) or institution_id
    if not institution_id:
        # Admin without a chosen institution: nothing to show.
        return templates.TemplateResponse(
            "attendance/faculty.html",
            {
                "request": request, "current_user": current_user,
                "date": day, "rows": [], "leave_types": [],
                "no_institution": True,
            },
        )

    try:
        ctx = await get_faculty_sheet(db, institution_id, day, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Institution not found")

    return templates.TemplateResponse(
        "attendance/faculty.html",
        {
            "request": request,
            "current_user": current_user,
            "institution_id": institution_id,
            "statuses": [s.value for s in FacultyAttendanceStatus],
            **ctx,
        },
    )


@router.post("/faculty/mark")
async def submit_faculty(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    institution_id = _to_int(form.get("institution_id")) or current_user.institution_id
    day = _parse_date(form.get("date", ""))
    if not institution_id:
        raise HTTPException(status_code=400, detail="institution_id required")

    records = []
    for key, value in form.items():
        if key.startswith("teacher_") and key.endswith("_status") and value:
            uid = key[len("teacher_"):-len("_status")]
            records.append({
                "user_id": uid,
                "status": value,
                "leave_type": form.get(f"teacher_{uid}_leave", ""),
            })

    try:
        await mark_faculty_attendance(
            db, records, institution_id, day, current_user,
            ip=request.client.host if request.client else None,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Institution not found")

    return RedirectResponse(
        f"/attendance/faculty?date={day.isoformat()}&saved=1", status_code=303
    )


# ── Low attendance alert ───────────────────────────────────────

@router.get("/low-alert", response_class=HTMLResponse)
async def low_alert(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    institution_id = None if current_user.role.value == "KREIS_ADMIN" else current_user.institution_id
    students = await get_low_attendance_students(
        db, institution_id, threshold=75, current_user=current_user
    )

    grouped: dict = {}
    for s in students:
        grouped.setdefault(s["class_label"], []).append(s)

    return templates.TemplateResponse(
        "attendance/low_alert.html",
        {
            "request": request,
            "current_user": current_user,
            "grouped": dict(sorted(grouped.items())),
            "total": len(students),
        },
    )


# ── Export ─────────────────────────────────────────────────────

@router.get("/export")
async def export_attendance(
    class_section_id: int,
    month: int,
    year: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    try:
        return await export_class_month_excel(
            db, class_section_id, month, year, current_user
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Class section not found")
