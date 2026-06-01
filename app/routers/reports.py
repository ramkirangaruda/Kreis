from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user

from app.models.inventory import InventoryItem

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/stock")
async def stock_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    result = await db.execute(
        select(InventoryItem)
    )

    inventory_items = result.scalars().all()

    return templates.TemplateResponse(
        "reports/stock.html",
        {
            "request": request,
            "data": inventory_items,
            "current_user": current_user
        }
    )