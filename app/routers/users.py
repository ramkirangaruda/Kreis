from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates
from app.models.user import User, UserRole
from app.services.users import (
    list_users,
    get_user,
    create_user,
    update_user,
    reset_password,
    deactivate_user,
    reactivate_user,
)
from app.services.institutions import list_institutions

router = APIRouter()

_ADMIN = require_role(["KREIS_ADMIN"])


@router.get("/", response_class=HTMLResponse)
async def users_list(
    request: Request,
    role: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    users = await list_users(db, role=role)
    return templates.TemplateResponse(
        "users/list.html",
        {
            "request": request,
            "users": users,
            "current_user": current_user,
            "roles": [r.value for r in UserRole],
            "selected_role": role,
            "success": request.query_params.get("success", ""),
        }
    )


@router.get("/institution-field", response_class=HTMLResponse)
async def institution_field(
    role: str = "",
    selected_id: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if role == "KREIS_ADMIN":
        return HTMLResponse('<div id="institution-field"></div>')

    institutions = await list_institutions(db)
    sel = int(selected_id) if selected_id.strip().isdigit() else None

    options = '<option value="">Select institution</option>' + "".join(
        f'<option value="{i.id}" {"selected" if sel and i.id == sel else ""}>'
        f"{i.name}</option>"
        for i in institutions
    )
    html = (
        '<div class="mb-3" id="institution-field">'
        '<label class="form-label required">Institution</label>'
        f'<select name="institution_id" class="form-select" required>{options}</select>'
        "</div>"
    )
    return HTMLResponse(html)


@router.get("/new", response_class=HTMLResponse)
async def new_user_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    institutions = await list_institutions(db)
    return templates.TemplateResponse(
        "users/form.html",
        {
            "request": request,
            "current_user": current_user,
            "edit_user": None,
            "institutions": institutions,
            "roles": [r.value for r in UserRole],
        }
    )


@router.post("/", response_class=HTMLResponse)
async def create_user_route(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    institution_id: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        user = await create_user(
            db,
            {
                "full_name": full_name,
                "email": email,
                "password": password,
                "role": role,
                "institution_id": institution_id or None,
                "password_change_required": True,
            },
            current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse(
            f"/users?success=User+'{user.full_name}'+created.",
            status_code=303
        )
    except ValueError as exc:
        await db.rollback()
        institutions = await list_institutions(db)
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "current_user": current_user,
                "edit_user": None,
                "institutions": institutions,
                "roles": [r.value for r in UserRole],
                "error": str(exc),
                "form_data": {
                    "full_name": full_name, "email": email,
                    "role": role, "institution_id": institution_id
                },
            },
            status_code=422
        )


@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_page(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    edit_user = await get_user(db, user_id)
    institutions = await list_institutions(db)
    return templates.TemplateResponse(
        "users/form.html",
        {
            "request": request,
            "current_user": current_user,
            "edit_user": edit_user,
            "institutions": institutions,
            "roles": [r.value for r in UserRole],
        }
    )


@router.post("/{user_id}/edit", response_class=HTMLResponse)
async def update_user_route(
    user_id: int,
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    role: str = Form(...),
    institution_id: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await update_user(
            db,
            user_id,
            {
                "full_name": full_name,
                "email": email,
                "role": role,
                "institution_id": institution_id or None,
            },
            current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse(f"/users?success=User+updated.", status_code=303)
    except ValueError as exc:
        await db.rollback()
        edit_user = await get_user(db, user_id)
        institutions = await list_institutions(db)
        return templates.TemplateResponse(
            "users/form.html",
            {
                "request": request,
                "current_user": current_user,
                "edit_user": edit_user,
                "institutions": institutions,
                "roles": [r.value for r in UserRole],
                "error": str(exc),
            },
            status_code=422
        )


@router.post("/{user_id}/reset-password", response_class=HTMLResponse)
async def reset_password_route(
    user_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    temp_password = await reset_password(
        db, user_id, current_user,
        ip=request.client.host if request.client else None
    )
    target_user = await get_user(db, user_id)
    return templates.TemplateResponse(
        "users/reset_confirm.html",
        {
            "request": request,
            "current_user": current_user,
            "target_user": target_user,
            "temp_password": temp_password,
        }
    )


@router.post("/{user_id}/deactivate")
async def deactivate_user_route(
    user_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await deactivate_user(
            db, user_id, current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse("/users?success=User+deactivated.", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/users?error={str(exc)}", status_code=303
        )


@router.post("/{user_id}/reactivate")
async def reactivate_user_route(
    user_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await reactivate_user(
        db, user_id, current_user,
        ip=request.client.host if request.client else None
    )
    return RedirectResponse("/users?success=User+reactivated.", status_code=303)
