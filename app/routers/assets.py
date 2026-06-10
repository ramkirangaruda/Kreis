from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates
from app.models.user import User
from app.services.assets import (
    list_categories,
    list_assets,
    get_asset,
    create_asset,
    update_asset,
    deactivate_asset,
    reactivate_asset,
)

router = APIRouter()

_ADMIN = require_role(["KREIS_ADMIN"])


@router.get("/", response_class=HTMLResponse)
async def assets_list(
    request: Request,
    category_id: str | None = None,
    search: str = "",
    show_inactive: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    cat_id = int(category_id) if category_id else None
    include_inactive = bool(show_inactive)
    categories = await list_categories(db)
    assets = await list_assets(db, category_id=cat_id, search=search, show_inactive=include_inactive)

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/asset_table.html",
            {"request": request, "assets": assets, "current_user": current_user}
        )

    return templates.TemplateResponse(
        "assets/list.html",
        {
            "request": request,
            "categories": categories,
            "assets": assets,
            "current_user": current_user,
            "selected_category_id": cat_id,
            "search": search,
            "show_inactive": include_inactive,
            "success": request.query_params.get("success", ""),
            "error": request.query_params.get("error", ""),
        }
    )


@router.get("/new", response_class=HTMLResponse)
async def new_asset_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    categories = await list_categories(db)
    return templates.TemplateResponse(
        "assets/form.html",
        {
            "request": request,
            "current_user": current_user,
            "asset": None,
            "categories": categories
        }
    )


@router.post("/", response_class=HTMLResponse)
async def create_asset_route(
    request: Request,
    name: str = Form(...),
    category_id: str = Form(...),
    unit: str = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        asset = await create_asset(
            db,
            {"name": name, "category_id": category_id, "unit": unit, "description": description},
            current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse(
            f"/assets?success=Asset+'{asset.name}'+created.", status_code=303
        )
    except ValueError as exc:
        await db.rollback()
        categories = await list_categories(db)
        return templates.TemplateResponse(
            "assets/form.html",
            {
                "request": request,
                "current_user": current_user,
                "asset": None,
                "categories": categories,
                "error": str(exc),
                "form_data": {"name": name, "category_id": category_id, "unit": unit, "description": description}
            },
            status_code=422
        )


@router.get("/{asset_id}/edit", response_class=HTMLResponse)
async def edit_asset_page(
    asset_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    asset = await get_asset(db, asset_id)
    categories = await list_categories(db)
    return templates.TemplateResponse(
        "assets/form.html",
        {
            "request": request,
            "current_user": current_user,
            "asset": asset,
            "categories": categories
        }
    )


@router.post("/{asset_id}/edit", response_class=HTMLResponse)
async def update_asset_route(
    asset_id: int,
    request: Request,
    name: str = Form(...),
    category_id: str = Form(...),
    unit: str = Form(...),
    description: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await update_asset(
            db,
            asset_id,
            {"name": name, "category_id": category_id, "unit": unit, "description": description},
            current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse("/assets?success=Asset+updated.", status_code=303)
    except ValueError as exc:
        await db.rollback()
        asset = await get_asset(db, asset_id)
        categories = await list_categories(db)
        return templates.TemplateResponse(
            "assets/form.html",
            {
                "request": request,
                "current_user": current_user,
                "asset": asset,
                "categories": categories,
                "error": str(exc)
            },
            status_code=422
        )


@router.post("/{asset_id}/deactivate")
async def deactivate_asset_route(
    asset_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        await deactivate_asset(
            db, asset_id, current_user,
            ip=request.client.host if request.client else None
        )
        return RedirectResponse("/assets?success=Asset+deactivated.", status_code=303)
    except ValueError as exc:
        return RedirectResponse(f"/assets?error={str(exc)}", status_code=303)


@router.post("/{asset_id}/reactivate")
async def reactivate_asset_route(
    asset_id: int,
    request: Request,
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    await reactivate_asset(
        db, asset_id, current_user,
        ip=request.client.host if request.client else None
    )
    return RedirectResponse("/assets?success=Asset+reactivated.", status_code=303)
