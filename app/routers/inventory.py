from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    status
)

from fastapi.responses import RedirectResponse

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role

from app.models.inventory import (
    InventoryItem,
    AssetMovement,
    MovementType
)

from app.models.user import UserRole


router = APIRouter()


@router.post("/issue")
async def issue_asset(
    inventory_item_id: int = Form(...),
    quantity: int = Form(...),
    issued_to: str = Form(...),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(
        require_role([
            UserRole.KREIS_ADMIN.value,
            UserRole.PRINCIPAL.value,
            UserRole.STAFF.value
        ])
    )
):
    item = await db.get(
        InventoryItem,
        inventory_item_id
    )

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Inventory item not found"
        )

    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    if item.quantity_available < quantity:
        raise HTTPException(
            status_code=400,
            detail="Insufficient stock"
        )

    item.quantity_available -= quantity

    movement = AssetMovement(
        inventory_item_id=inventory_item_id,
        movement_type=MovementType.ISSUE,
        quantity=quantity,
        issued_to=issued_to,
        performed_by_id=current_user.id,
        notes=notes
    )

    db.add(movement)

    await db.commit()

    return RedirectResponse(
        "/inventory",
        status_code=status.HTTP_302_FOUND
    )