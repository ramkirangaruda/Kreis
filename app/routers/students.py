"""Student routes — School ERP."""

from datetime import date

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates

from app.models.user import User
from app.models.student import Gender, CasteCategory

from app.services.students import (
    list_students,
    get_student,
    create_student,
    update_student,
    deactivate_student,
    get_student_stats,
    export_students_excel,
    list_class_sections,
    NotFoundError,
)

router = APIRouter()

_MANAGER = require_role(["KREIS_ADMIN", "PRINCIPAL"])

_DEMOGRAPHIC_FIELDS = [
    "caste_category", "caste", "religion",
    "father_name", "father_occupation", "father_phone",
    "mother_name", "mother_occupation", "mother_phone",
    "guardian_name", "guardian_phone", "annual_income",
    "address_village", "address_taluk", "address_district", "address_pin",
]


def _to_int(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _scope_institution(current_user) -> int | None:
    return None if current_user.role.value == "KREIS_ADMIN" else current_user.institution_id


# ── List ───────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def students_list(
    request: Request,
    class_section_id: str = "",
    gender: str = "",
    caste_category: str = "",
    search: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    students = await list_students(
        db,
        current_user,
        class_section_id=_to_int(class_section_id),
        gender=gender or None,
        caste_category=caste_category or None,
        search=search,
    )

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/student_table.html",
            {"request": request, "students": students, "current_user": current_user},
        )

    stats = await get_student_stats(db, institution_id=_scope_institution(current_user))
    class_sections = await list_class_sections(db, current_user)

    return templates.TemplateResponse(
        "students/list.html",
        {
            "request": request,
            "current_user": current_user,
            "students": students,
            "stats": stats,
            "class_sections": class_sections,
            "genders": [g.value for g in Gender],
            "castes": [c.value for c in CasteCategory],
            "selected_class_section_id": _to_int(class_section_id),
            "selected_gender": gender,
            "selected_caste": caste_category,
            "search": search,
        },
    )


# ── New form ───────────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_student_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    class_sections = await list_class_sections(db, current_user)
    return templates.TemplateResponse(
        "students/form.html",
        {
            "request": request,
            "current_user": current_user,
            "is_edit": False,
            "action_url": "/students/",
            "values": {},
            "class_sections": class_sections,
            "genders": [g.value for g in Gender],
            "castes": [c.value for c in CasteCategory],
        },
    )


# ── Export (must precede /{student_id}) ────────────────────────

@router.get("/export")
async def export_students(
    class_section_id: str = "",
    gender: str = "",
    caste_category: str = "",
    search: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    return await export_students_excel(
        db,
        current_user,
        class_section_id=_to_int(class_section_id),
        gender=gender or None,
        caste_category=caste_category or None,
        search=search,
    )


# ── Create ─────────────────────────────────────────────────────

@router.post("/", response_class=HTMLResponse)
async def create_student_route(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    student_data, demographics_data = _extract(form)

    error = None
    dob = _parse_date(form.get("date_of_birth", ""))
    if dob is None:
        error = "A valid date of birth is required."
    else:
        student_data["date_of_birth"] = dob
        try:
            student = await create_student(
                db, student_data, demographics_data, current_user,
                ip=request.client.host if request.client else None,
            )
            return RedirectResponse(f"/students/{student.id}", status_code=303)
        except ValueError as exc:
            await db.rollback()
            # rollback expires session objects; reload current_user so the
            # error template (which extends base.html) can read its attributes.
            await db.refresh(current_user)
            error = str(exc)

    class_sections = await list_class_sections(db, current_user)
    return templates.TemplateResponse(
        "students/form.html",
        {
            "request": request,
            "current_user": current_user,
            "is_edit": False,
            "action_url": "/students/",
            "values": dict(form),
            "class_sections": class_sections,
            "genders": [g.value for g in Gender],
            "castes": [c.value for c in CasteCategory],
            "error": error,
        },
        status_code=422,
    )


# ── Detail ─────────────────────────────────────────────────────

@router.get("/{student_id}", response_class=HTMLResponse)
async def student_detail(
    student_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        ctx = await get_student(db, student_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Student not found")

    return templates.TemplateResponse(
        "students/detail.html",
        {"request": request, "current_user": current_user, **ctx},
    )


# ── Edit form ──────────────────────────────────────────────────

@router.get("/{student_id}/edit", response_class=HTMLResponse)
async def edit_student_page(
    student_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    try:
        ctx = await get_student(db, student_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Student not found")

    student = ctx["student"]
    demo = student.demographics
    values = {
        "full_name": student.full_name,
        "admission_number": student.admission_number,
        "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else "",
        "gender": student.gender.value if student.gender else "",
        "aadhar_number": student.aadhar_number or "",
        "sats_id": student.sats_id or "",
        "class_section_id": str(student.class_section_id),
        "is_residential": "1" if student.is_residential else "",
        "caste_category": demo.caste_category.value if demo and demo.caste_category else "",
    }
    if demo:
        for f in _DEMOGRAPHIC_FIELDS:
            if f == "caste_category":
                continue
            values[f] = getattr(demo, f) if getattr(demo, f) is not None else ""

    class_sections = await list_class_sections(db, current_user)
    return templates.TemplateResponse(
        "students/form.html",
        {
            "request": request,
            "current_user": current_user,
            "is_edit": True,
            "action_url": f"/students/{student_id}/edit",
            "values": values,
            "class_sections": class_sections,
            "genders": [g.value for g in Gender],
            "castes": [c.value for c in CasteCategory],
        },
    )


# ── Update ─────────────────────────────────────────────────────

@router.post("/{student_id}/edit", response_class=HTMLResponse)
async def update_student_route(
    student_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    student_data, demographics_data = _extract(form)

    error = None
    dob = _parse_date(form.get("date_of_birth", ""))
    if dob is None:
        error = "A valid date of birth is required."
    else:
        student_data["date_of_birth"] = dob
        try:
            await update_student(
                db, student_id, student_data, demographics_data, current_user,
                ip=request.client.host if request.client else None,
            )
            return RedirectResponse(f"/students/{student_id}", status_code=303)
        except NotFoundError:
            raise HTTPException(status_code=404, detail="Student not found")
        except ValueError as exc:
            await db.rollback()
            # rollback expires session objects; reload current_user so the
            # error template (which extends base.html) can read its attributes.
            await db.refresh(current_user)
            error = str(exc)

    class_sections = await list_class_sections(db, current_user)
    return templates.TemplateResponse(
        "students/form.html",
        {
            "request": request,
            "current_user": current_user,
            "is_edit": True,
            "action_url": f"/students/{student_id}/edit",
            "values": dict(form),
            "class_sections": class_sections,
            "genders": [g.value for g in Gender],
            "castes": [c.value for c in CasteCategory],
            "error": error,
        },
        status_code=422,
    )


# ── Deactivate ─────────────────────────────────────────────────

@router.post("/{student_id}/deactivate")
async def deactivate_student_route(
    student_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await deactivate_student(
            db, student_id, current_user,
            ip=request.client.host if request.client else None,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Student not found")
    return RedirectResponse("/students?success=Student+deactivated.", status_code=303)


# ── helpers ────────────────────────────────────────────────────

def _parse_date(value: str):
    try:
        return date.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


def _extract(form) -> tuple[dict, dict]:
    student_data = {
        "full_name": form.get("full_name", ""),
        "admission_number": form.get("admission_number", ""),
        "gender": form.get("gender", ""),
        "aadhar_number": form.get("aadhar_number", ""),
        "sats_id": form.get("sats_id", ""),
        "class_section_id": form.get("class_section_id", ""),
        "is_residential": bool(form.get("is_residential")),
    }
    demographics_data = {f: form.get(f, "") for f in _DEMOGRAPHIC_FIELDS}
    return student_data, demographics_data
