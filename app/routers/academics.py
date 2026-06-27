"""Academics routes — exams, marks, competitive results, timetable."""

from datetime import date

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates

from app.models.user import User
from app.models.student import Student, ClassSection
from app.models.academic import ExamResult, ExamType, CompetitiveExamName, DayOfWeek

from app.services.students import list_class_sections
from app.services.academics import (
    list_exams, create_exam, get_exam_results, enter_exam_results,
    get_low_performers, create_competitive_result, list_competitive_results,
    get_timetable, save_timetable, get_marks_card,
    list_subjects_for_class, list_teachers, export_exam_results_excel,
    NotFoundError, PERIODS, DAYS,
)

router = APIRouter()

_MANAGER = require_role(["KREIS_ADMIN", "PRINCIPAL"])
_TEACHER = require_role(["KREIS_ADMIN", "PRINCIPAL", "TEACHER"])


def _scope(current_user):
    return None if current_user.role.value == "KREIS_ADMIN" else current_user.institution_id


def _to_int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _parse_date(v):
    try:
        return date.fromisoformat(v) if v else None
    except (ValueError, TypeError):
        return None


# ── Landing ────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def academics_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inst = _scope(current_user)
    exams = await list_exams(db, inst, current_user=current_user)
    today = date.today()
    upcoming = [e for e in exams if e.start_date >= today]
    low = await get_low_performers(db, inst, current_user=current_user)
    low_count = sum(len(v) for v in low.values())

    return templates.TemplateResponse(
        "academics/index.html",
        {
            "request": request, "current_user": current_user,
            "exams": exams, "upcoming_count": len(upcoming),
            "exam_count": len(exams), "low_count": low_count,
            "today": today,
        },
    )


# ── Exams ──────────────────────────────────────────────────────

@router.get("/exams/new", response_class=HTMLResponse)
async def new_exam_page(
    request: Request,
    current_user: User = Depends(_MANAGER),
):
    return templates.TemplateResponse(
        "academics/exam_form.html",
        {
            "request": request, "current_user": current_user,
            "exam_types": [t.value for t in ExamType], "values": {},
        },
    )


@router.post("/exams")
async def create_exam_route(
    request: Request,
    name: str = Form(...),
    exam_type: str = Form(...),
    start_date: str = Form(...),
    end_date: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    sd, ed = _parse_date(start_date), _parse_date(end_date)
    error = None
    if not sd or not ed:
        error = "Valid start and end dates are required."
    else:
        try:
            exam = await create_exam(
                db,
                {"name": name, "exam_type": exam_type, "start_date": sd, "end_date": ed},
                current_user, ip=request.client.host if request.client else None,
            )
            return RedirectResponse(f"/academics/exams/{exam.id}/results", status_code=303)
        except ValueError as exc:
            await db.rollback()
            await db.refresh(current_user)
            error = str(exc)

    return templates.TemplateResponse(
        "academics/exam_form.html",
        {
            "request": request, "current_user": current_user,
            "exam_types": [t.value for t in ExamType],
            "values": {"name": name, "exam_type": exam_type,
                       "start_date": start_date, "end_date": end_date},
            "error": error,
        },
        status_code=422,
    )


@router.get("/exams/{exam_id}/results", response_class=HTMLResponse)
async def exam_results(
    exam_id: int,
    request: Request,
    class_section_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        data = await get_exam_results(db, exam_id, _to_int(class_section_id), current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Exam not found")

    class_sections = await list_class_sections(db, current_user)
    ctx = {
        "request": request, "current_user": current_user,
        "class_sections": class_sections,
        "selected_class_section_id": _to_int(class_section_id),
        **data,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/results_table.html", ctx)
    return templates.TemplateResponse("academics/results.html", ctx)


@router.get("/exams/{exam_id}/results/export")
async def export_results(
    exam_id: int,
    class_section_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        return await export_exam_results_excel(
            db, exam_id, _to_int(class_section_id), current_user
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Exam not found")


@router.get("/exams/{exam_id}/enter-results", response_class=HTMLResponse)
async def enter_results_page(
    exam_id: int,
    request: Request,
    class_section_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_TEACHER),
):
    try:
        from app.services.academics import _load_exam
        exam = await _load_exam(db, exam_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Exam not found")

    class_sections = await list_class_sections(db, current_user)
    cs_id = _to_int(class_section_id)

    students, subjects, existing = [], [], {}
    if cs_id:
        students = (await db.execute(
            select(Student).where(Student.class_section_id == cs_id, Student.is_active.is_(True))
            .order_by(Student.full_name)
        )).scalars().all()
        subjects = await list_subjects_for_class(db, cs_id)
        rows = (await db.execute(
            select(ExamResult).where(ExamResult.exam_id == exam_id)
        )).scalars().all()
        existing = {(r.student_id, r.subject_id): r for r in rows}

    return templates.TemplateResponse(
        "academics/marks_entry.html",
        {
            "request": request, "current_user": current_user, "exam": exam,
            "class_sections": class_sections, "selected_class_section_id": cs_id,
            "students": students, "subjects": subjects, "existing": existing,
        },
    )


@router.post("/exams/{exam_id}/enter-results")
async def submit_results(
    exam_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_TEACHER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    cs_id = _to_int(form.get("class_section_id"))
    subject_ids = [int(s) for s in form.getlist("subject_id")]
    student_ids = [int(s) for s in form.getlist("student_id")]
    max_by_subject = {sid: (form.get(f"max_{sid}") or 0) for sid in subject_ids}

    results = []
    for st in student_ids:
        for sub in subject_ids:
            absent = form.get(f"absent_{st}_{sub}") is not None
            marks = form.get(f"marks_{st}_{sub}", "")
            if not absent and marks == "":
                continue
            results.append({
                "student_id": st, "subject_id": sub,
                "marks_obtained": marks or 0, "max_marks": max_by_subject.get(sub, 0),
                "is_absent": absent,
            })

    try:
        await enter_exam_results(
            db, exam_id, results, current_user,
            ip=request.client.host if request.client else None,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Exam not found")

    url = f"/academics/exams/{exam_id}/results"
    if cs_id:
        url += f"?class_section_id={cs_id}"
    return RedirectResponse(url, status_code=303)


# ── Marks card ─────────────────────────────────────────────────

@router.get("/students/{student_id}/marks-card", response_class=HTMLResponse)
async def marks_card(
    student_id: int,
    request: Request,
    exam_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        data = await get_marks_card(db, student_id, exam_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Not found")
    return templates.TemplateResponse(
        "academics/marks_card.html",
        {"request": request, "current_user": current_user, **data},
    )


# ── Low performers ─────────────────────────────────────────────

@router.get("/low-performers", response_class=HTMLResponse)
async def low_performers(
    request: Request,
    exam_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    inst = _scope(current_user)
    grouped = await get_low_performers(
        db, inst, exam_id=_to_int(exam_id), current_user=current_user
    )
    exams = await list_exams(db, inst, current_user=current_user)
    total = sum(len(v) for v in grouped.values())
    return templates.TemplateResponse(
        "academics/low_performers.html",
        {
            "request": request, "current_user": current_user,
            "grouped": grouped, "exams": exams,
            "selected_exam_id": _to_int(exam_id), "total": total,
        },
    )


# ── Competitive ────────────────────────────────────────────────

@router.get("/competitive", response_class=HTMLResponse)
async def competitive(
    request: Request,
    exam_name: str = "",
    year: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    inst = _scope(current_user)
    results = await list_competitive_results(db, inst, exam_name or None, _to_int(year))
    students = []
    if current_user.role.value in ["KREIS_ADMIN", "PRINCIPAL"]:
        q = select(Student).where(Student.is_active.is_(True)).order_by(Student.full_name)
        if inst:
            q = q.where(Student.institution_id == inst)
        students = (await db.execute(q)).scalars().all()
    return templates.TemplateResponse(
        "academics/competitive.html",
        {
            "request": request, "current_user": current_user,
            "results": results, "students": students,
            "exam_names": [e.value for e in CompetitiveExamName],
            "selected_exam_name": exam_name, "selected_year": year,
            "can_manage": current_user.role.value in ["KREIS_ADMIN", "PRINCIPAL"],
        },
    )


@router.post("/competitive")
async def add_competitive(
    request: Request,
    student_id: int = Form(...),
    exam_name: str = Form(...),
    exam_year: int = Form(...),
    roll_number: str = Form(""),
    rank: str = Form(""),
    score: str = Form(""),
    qualified: str = Form(""),
    notes: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await create_competitive_result(
            db,
            {
                "student_id": student_id, "exam_name": exam_name, "exam_year": exam_year,
                "roll_number": roll_number, "rank": rank, "score": score,
                "qualified": bool(qualified), "notes": notes,
            },
            current_user, ip=request.client.host if request.client else None,
        )
    except ValueError as exc:
        return RedirectResponse(f"/academics/competitive?error={exc}", status_code=303)
    return RedirectResponse("/academics/competitive", status_code=303)


# ── Timetable ──────────────────────────────────────────────────

@router.get("/timetable/{class_section_id}", response_class=HTMLResponse)
async def timetable_view(
    class_section_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    section = await db.get(ClassSection, class_section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Class section not found")
    grid = await get_timetable(db, class_section_id)
    return templates.TemplateResponse(
        "academics/timetable.html",
        {
            "request": request, "current_user": current_user, "section": section,
            "grid": grid, "periods": PERIODS, "days": [d.value for d in DAYS],
            "edit": False,
        },
    )


@router.get("/timetable/{class_section_id}/edit", response_class=HTMLResponse)
async def timetable_edit(
    class_section_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    section = await db.get(ClassSection, class_section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Class section not found")
    grid = await get_timetable(db, class_section_id)
    subjects = await list_subjects_for_class(db, class_section_id)
    teachers = await list_teachers(db, section.institution_id)
    return templates.TemplateResponse(
        "academics/timetable.html",
        {
            "request": request, "current_user": current_user, "section": section,
            "grid": grid, "periods": PERIODS, "days": [d.value for d in DAYS],
            "subjects": subjects, "teachers": teachers, "edit": True,
        },
    )


@router.post("/timetable/{class_section_id}")
async def timetable_save(
    class_section_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    slots = []
    for day in [d.value for d in DAYS]:
        for period in PERIODS:
            subj = form.get(f"slot_{day}_{period}_subject", "")
            teach = form.get(f"slot_{day}_{period}_teacher", "")
            if subj or teach:
                slots.append({
                    "day_of_week": day, "period_number": period,
                    "subject_id": _to_int(subj), "teacher_id": _to_int(teach),
                })

    try:
        await save_timetable(
            db, class_section_id, slots, current_user,
            ip=request.client.host if request.client else None,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Class section not found")
    except ValueError as exc:
        return RedirectResponse(
            f"/academics/timetable/{class_section_id}/edit?error={exc}", status_code=303
        )

    return RedirectResponse(f"/academics/timetable/{class_section_id}", status_code=303)
