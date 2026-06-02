
from fastapi import APIRouter, Depends, Request

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.templates import templates

from app.models.inventory import InventoryItem
from app.models.user import UserRole

from app.services.reports import generate_excel_report
from app.services.audit import get_audit_logs, list_audit_filters


router = APIRouter()

_ADMIN = require_role([UserRole.KREIS_ADMIN.value])


@router.get("/stock")
async def stock_report(
    request: Request,
    format: str = "html",

    db: AsyncSession = Depends(get_db),

    current_user=Depends(get_current_user)
):

    query = select(InventoryItem).options(
        selectinload(InventoryItem.asset),
        selectinload(InventoryItem.institution)
    )

    if current_user.role != UserRole.KREIS_ADMIN:
        query = query.where(
            InventoryItem.institution_id == current_user.institution_id
        )

    result = await db.execute(query)

    inventory_items = result.scalars().all()

    data = []

    for item in inventory_items:

        data.append({

            "institution": (
                item.institution.name
                if item.institution
                else "N/A"
            ),

            "asset": (
                item.asset.name
                if item.asset
                else "N/A"
            ),

            "category": (
                item.asset.category.name
                if item.asset and item.asset.category
                else "N/A"
            ),

            "total": item.quantity_total,

            "available": item.quantity_available,

            "status": (
                "Low Stock"
                if item.quantity_available
                <= item.low_stock_threshold
                else "Normal"
            )
        })

    # Excel export
    if format == "xlsx":
        return generate_excel_report(data)

    # HTML page
    return templates.TemplateResponse(
        "reports/stock.html",
        {
            "request": request,
            "data": data,
            "current_user": current_user
        }
    )


@router.get("/audit")
async def audit_log(
    request: Request,
    user_id: int | None = None,
    action: str = "",
    entity: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_ADMIN),
):
    result = await get_audit_logs(
        db,
        user_id=user_id,
        action=action or None,
        entity=entity or None,
        date_from=date_from or None,
        date_to=date_to or None,
        page=page,
        per_page=50,
    )

    filters = await list_audit_filters(db)

    return templates.TemplateResponse(
        "reports/audit.html",
        {
            "request": request,
            "current_user": current_user,
            "logs": result["logs"],
            "total": result["total"],
            "page": result["page"],
            "pages": result["pages"],
            "actions": filters["actions"],
            "entities": filters["entities"],
            "selected_action": action,
            "selected_entity": entity,
            "selected_user_id": user_id,
            "date_from": date_from,
            "date_to": date_to,
        },
    )
