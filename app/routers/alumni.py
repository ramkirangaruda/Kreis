"""Alumni routes — School ERP."""

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates

from app.models.user import User
from app.models.student import Student
from app.services.institutions import list_institutions
from app.services.alumni import (
    list_alumni, get_alumni, create_alumni, update_alumni,
    get_alumni_stats, NotFoundError,
)

router = APIRouter()

_MANAGER = require_role(["KREIS_ADMIN", "PRINCIPAL"])

_FIELDS = [
    "full_name", "passed_class", "current_occupation", "employer",
    "higher_education_institution", "higher_education_course",
    "location_city", "location_state", "phone", "email",
    "linkedin_url", "notable_achievement",
]


def _to_int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _is_admin(u):
    return u.role.value == "KREIS_ADMIN"


async def _form_context(db, current_user):
    students, institutions = [], []
    if _is_admin(current_user):
        institutions = await list_institutions(db)
    inst = None if _is_admin(current_user) else current_user.institution_id
    q = select(Student).where(Student.is_active.is_(True)).order_by(Student.full_name)
    if inst:
        q = q.where(Student.institution_id == inst)
    students = (await db.execute(q)).scalars().all()
    return students, institutions


# ── List ───────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def alumni_list(
    request: Request,
    batch_year: str = "",
    occupation: str = "",
    search: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alumni = await list_alumni(
        db, current_user, batch_year=_to_int(batch_year),
        occupation=occupation or None, search=search,
    )
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/alumni_rows.html",
            {"request": request, "current_user": current_user, "alumni": alumni},
        )
    stats = await get_alumni_stats(db, current_user)
    return templates.TemplateResponse(
        "alumni/list.html",
        {
            "request": request, "current_user": current_user,
            "alumni": alumni, "stats": stats,
            "selected_batch_year": batch_year, "selected_occupation": occupation,
            "search": search,
        },
    )


# ── New / Create ───────────────────────────────────────────────

@router.get("/new", response_class=HTMLResponse)
async def new_alumni_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    students, institutions = await _form_context(db, current_user)
    return templates.TemplateResponse(
        "alumni/form.html",
        {
            "request": request, "current_user": current_user, "is_edit": False,
            "action_url": "/alumni", "values": {},
            "students": students, "institutions": institutions,
            "is_admin": _is_admin(current_user),
        },
    )


@router.post("/")
async def create_alumni_route(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    data = dict(form)
    try:
        alum = await create_alumni(
            db, data, current_user, ip=request.client.host if request.client else None
        )
        return RedirectResponse(f"/alumni/{alum.id}", status_code=303)
    except ValueError as exc:
        await db.rollback()
        await db.refresh(current_user)
        students, institutions = await _form_context(db, current_user)
        return templates.TemplateResponse(
            "alumni/form.html",
            {
                "request": request, "current_user": current_user, "is_edit": False,
                "action_url": "/alumni", "values": data, "error": str(exc),
                "students": students, "institutions": institutions,
                "is_admin": _is_admin(current_user),
            },
            status_code=422,
        )


# ── Detail ─────────────────────────────────────────────────────

@router.get("/{alumni_id}", response_class=HTMLResponse)
async def alumni_detail(
    alumni_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        alum = await get_alumni(db, alumni_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Alumni not found")
    return templates.TemplateResponse(
        "alumni/detail.html",
        {"request": request, "current_user": current_user, "alum": alum},
    )


# ── Edit / Update ──────────────────────────────────────────────

@router.get("/{alumni_id}/edit", response_class=HTMLResponse)
async def edit_alumni_page(
    alumni_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    try:
        alum = await get_alumni(db, alumni_id, current_user)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Alumni not found")
    students, institutions = await _form_context(db, current_user)
    values = {f: getattr(alum, f) or "" for f in _FIELDS}
    values["batch_year"] = alum.batch_year
    values["student_id"] = str(alum.student_id) if alum.student_id else ""
    return templates.TemplateResponse(
        "alumni/form.html",
        {
            "request": request, "current_user": current_user, "is_edit": True,
            "action_url": f"/alumni/{alumni_id}/edit", "values": values,
            "students": students, "institutions": institutions,
            "is_admin": _is_admin(current_user),
        },
    )


@router.post("/{alumni_id}/edit")
async def update_alumni_route(
    alumni_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_MANAGER),
):
    form = await request.form()
    if not validate_csrf_token(form.get("csrf_token", "")):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    data = dict(form)
    try:
        await update_alumni(
            db, alumni_id, data, current_user,
            ip=request.client.host if request.client else None,
        )
        return RedirectResponse(f"/alumni/{alumni_id}", status_code=303)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Alumni not found")
    except ValueError as exc:
        await db.rollback()
        await db.refresh(current_user)
        students, institutions = await _form_context(db, current_user)
        return templates.TemplateResponse(
            "alumni/form.html",
            {
                "request": request, "current_user": current_user, "is_edit": True,
                "action_url": f"/alumni/{alumni_id}/edit", "values": data, "error": str(exc),
                "students": students, "institutions": institutions,
                "is_admin": _is_admin(current_user),
            },
            status_code=422,
        )
