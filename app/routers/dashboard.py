from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    stats = {
        "total_schools": 0,
        "total_assets": 0,
        "low_stock_items": 0
    }

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": current_user,
            "stats": stats
        }
    )


@router.get("/dashboard/partials/schools")
async def schools_partial(
    request: Request,
    district: str = "",
    category: str = "",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    schools = []

    return templates.TemplateResponse(
        "partials/school_table.html",
        {
            "request": request,
            "schools": schools
        }
    )