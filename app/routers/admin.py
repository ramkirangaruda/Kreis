"""Admin-only routes: scanner registry and cross-school analytics."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates

from app.models.user import User
from app.models.document import ScannerDevice
from app.services.institutions import list_institutions
from app.services.analytics import get_cross_school_analytics

router = APIRouter()

_ADMIN = require_role(["KREIS_ADMIN"])

ONLINE_WINDOW = timedelta(minutes=5)


@router.get("/scanners", response_class=HTMLResponse)
async def scanners_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    devices = (await db.execute(
        select(ScannerDevice)
        .options(selectinload(ScannerDevice.institution))
        .order_by(ScannerDevice.device_id)
    )).scalars().all()

    now = datetime.utcnow()
    rows = [
        {
            "device": d,
            "online": d.last_seen is not None and (now - d.last_seen) < ONLINE_WINDOW,
        }
        for d in devices
    ]
    institutions = await list_institutions(db)
    return templates.TemplateResponse(
        "admin/scanners.html",
        {
            "request": request, "current_user": current_user,
            "rows": rows, "institutions": institutions,
            "success": request.query_params.get("success", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/scanners")
async def register_scanner(
    request: Request,
    device_id: str = Form(...),
    institution_id: int = Form(...),
    location: str = Form(...),
    device_type: str = Form(...),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    exists = (await db.execute(
        select(ScannerDevice.id).where(ScannerDevice.device_id == device_id.strip())
    )).scalar_one_or_none()
    if exists:
        return RedirectResponse(
            "/admin/scanners?error=Device+ID+already+registered", status_code=303
        )

    db.add(ScannerDevice(
        device_id=device_id.strip(),
        institution_id=institution_id,
        location=location.strip(),
        device_type=device_type.strip(),
    ))
    await db.commit()
    return RedirectResponse("/admin/scanners?success=Scanner+registered", status_code=303)


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_ADMIN),
):
    data = await get_cross_school_analytics(db)
    return templates.TemplateResponse(
        "admin/analytics.html",
        {"request": request, "current_user": current_user, **data},
    )
