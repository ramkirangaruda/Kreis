from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates
from app.models.user import User

from app.services.institutions import (
    list_institutions,
    get_all_districts,
    get_institution,
    get_institution_detail,
    create_institution,
    update_institution,
    deactivate_institution,
)

router = APIRouter()

_ADMIN = require_role(["KREIS_ADMIN"])


@router.get("/", response_class=HTMLResponse)
async def institutions_list(
    request: Request,
    search: str = "",
    district: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    institutions = await list_institutions(db, search=search, district=district)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/institution_table.html",
            {"request": request, "institutions": institutions, "current_user": current_user}
        )

    all_districts = await get_all_districts(db)
    return templates.TemplateResponse(
        "institutions/list.html",
        {
            "request": request,
            "institutions": institutions,
            "districts": all_districts,
            "current_user": current_user,
            "search": search,
            "district": district,
            "success": request.query_params.get("success", ""),
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_institution_page(
    request: Request,
    current_user: User = Depends(_ADMIN)
):
    return templates.TemplateResponse(
        "institutions/form.html",
        {"request": request, "current_user": current_user, "institution": None}
    )


@router.post("/", response_class=HTMLResponse)
async def create_institution_route(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    district: str = Form(...),
    address: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        inst = await create_institution(
            db,
            {"name": name, "code": code, "district": district, "address": address},
            current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse(
            f"/institutions?success=Institution+%27{inst.name}%27+created.",
            status_code=303
        )
    except ValueError as exc:
        await db.rollback()
        return templates.TemplateResponse(
            "institutions/form.html",
            {
                "request": request,
                "current_user": current_user,
                "institution": None,
                "error": str(exc),
                "form_data": {"name": name, "code": code, "district": district, "address": address}
            },
            status_code=422
        )


@router.get("/{inst_id}", response_class=HTMLResponse)
async def institution_detail(
    inst_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    ctx = await get_institution_detail(db, inst_id)
    return templates.TemplateResponse(
        "institutions/detail.html",
        {"request": request, "current_user": current_user, **ctx}
    )


@router.get("/{inst_id}/edit", response_class=HTMLResponse)
async def edit_institution_page(
    inst_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    inst = await get_institution(db, inst_id)
    return templates.TemplateResponse(
        "institutions/form.html",
        {"request": request, "current_user": current_user, "institution": inst}
    )


@router.post("/{inst_id}/edit", response_class=HTMLResponse)
async def update_institution_route(
    inst_id: int,
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    district: str = Form(...),
    address: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        inst = await update_institution(
            db,
            inst_id,
            {"name": name, "code": code, "district": district, "address": address},
            current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse(f"/institutions/{inst_id}", status_code=303)
    except ValueError as exc:
        await db.rollback()
        from app.models.institution import Institution
        placeholder = Institution(id=inst_id, name=name, code=code, district=district, address=address)
        return templates.TemplateResponse(
            "institutions/form.html",
            {
                "request": request,
                "current_user": current_user,
                "institution": placeholder,
                "error": str(exc)
            },
            status_code=422
        )


@router.post("/{inst_id}/deactivate")
async def deactivate_institution_route(
    inst_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await deactivate_institution(
        db, inst_id, current_user,
        ip=request.client.host if request.client else None
    )
    return RedirectResponse("/institutions?success=Institution+deactivated.", status_code=303)
