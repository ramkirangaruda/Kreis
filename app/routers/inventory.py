import json

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Request,
    Response,
    status
)

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.core.csrf import validate_csrf_token
from app.core.templates import templates

from app.models.asset import Asset, AssetCategory
from app.models.institution import Institution
from app.models.inventory import InventoryItem, AssetMovement, MovementType
from app.models.user import UserRole

from app.services.audit import log_action
from app.services.inventory import (
    get_movement_history,
    return_asset as svc_return,
    transfer_asset as svc_transfer,
)


router = APIRouter()


_ALL_ROLES = [
    UserRole.KREIS_ADMIN.value,
    UserRole.PRINCIPAL.value,
    UserRole.STAFF.value,
]

_TRANSFER_ROLES = [
    UserRole.KREIS_ADMIN.value,
    UserRole.PRINCIPAL.value,
]


def _is_admin(user) -> bool:
    return user.role.value == "KREIS_ADMIN"


async def _scoped_items(
    db: AsyncSession,
    current_user,
    category_id: int | None = None,
    institution_id: int | None = None,
    asset_name: str | None = None,
):
    """Return inventory items the user may see, with optional filters."""
    query = select(InventoryItem).options(
        selectinload(InventoryItem.asset).selectinload(Asset.category),
        selectinload(InventoryItem.institution),
    )

    if not _is_admin(current_user):
        query = query.where(
            InventoryItem.institution_id == current_user.institution_id
        )
    elif institution_id:
        query = query.where(InventoryItem.institution_id == institution_id)

    if category_id or asset_name:
        query = query.join(Asset, InventoryItem.asset_id == Asset.id)
        if category_id:
            query = query.where(Asset.category_id == category_id)
        if asset_name:
            query = query.where(Asset.name.ilike(f"%{asset_name}%"))

    query = query.order_by(InventoryItem.id)
    result = await db.execute(query)
    return result.scalars().all()


def _table_response(request, items, current_user, oob: bool = False, toast: str | None = None):
    resp = templates.TemplateResponse(
        "partials/inventory_table.html",
        {
            "request": request,
            "items": items,
            "current_user": current_user,
            "oob": oob,
        },
    )
    if toast:
        resp.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": toast, "type": "success"}}
        )
    return resp


@router.get("/")
async def inventory_page(
    request: Request,
    category_id: str | None = None,
    institution_id: str | None = None,
    asset_name: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    cat_id = int(category_id) if category_id else None
    inst_id = int(institution_id) if institution_id else None
    name_filter = asset_name.strip() if asset_name else None
    items = await _scoped_items(
        db, current_user, category_id=cat_id, institution_id=inst_id,
        asset_name=name_filter,
    )

    if request.headers.get("HX-Request"):
        return _table_response(request, items, current_user)

    categories = (
        await db.execute(select(AssetCategory).order_by(AssetCategory.code))
    ).scalars().all()

    institutions = []
    if _is_admin(current_user):
        institutions = (
            await db.execute(
                select(Institution)
                .where(Institution.is_active.is_(True))
                .order_by(Institution.name)
            )
        ).scalars().all()

    return templates.TemplateResponse(
        "inventory/index.html",
        {
            "request": request,
            "items": items,
            "current_user": current_user,
            "categories": categories,
            "institutions": institutions,
            "selected_category_id": cat_id,
            "selected_institution_id": inst_id,
            "selected_asset_name": name_filter,
        },
    )


# ── Movement history ──────────────────────────────────────────

@router.get("/movements")
async def movements_page(
    request: Request,
    institution_id: str | None = None,
    asset_id: str | None = None,
    movement_type: str = "",
    days: str = "30",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    inst_id = int(institution_id) if institution_id else None
    ast_id  = int(asset_id) if asset_id else None
    days_int = int(days) if days else 30
    movements = await get_movement_history(
        db,
        current_user,
        institution_id=inst_id,
        asset_id=ast_id,
        movement_type=movement_type or None,
        days=days_int,
    )

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/movement_table.html",
            {
                "request": request,
                "movements": movements,
                "current_user": current_user,
            },
        )

    institutions = []
    if _is_admin(current_user):
        institutions = (
            await db.execute(
                select(Institution)
                .where(Institution.is_active.is_(True))
                .order_by(Institution.name)
            )
        ).scalars().all()

    return templates.TemplateResponse(
        "inventory/movement_history.html",
        {
            "request": request,
            "movements": movements,
            "current_user": current_user,
            "institutions": institutions,
            "movement_types": [t.value for t in MovementType],
            "selected_type": movement_type,
            "selected_institution_id": inst_id,
            "selected_days": days_int,
        },
    )


# ── Modal form loaders ────────────────────────────────────────

@router.get("/{item_id}/issue-form")
async def issue_form(
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(_ALL_ROLES)),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    return templates.TemplateResponse(
        "partials/issue_form.html",
        {"request": request, "item": item, "current_user": current_user},
    )


@router.get("/{item_id}/return-form")
async def return_form(
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(_ALL_ROLES)),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    return templates.TemplateResponse(
        "partials/return_form.html",
        {"request": request, "item": item, "current_user": current_user},
    )


@router.get("/{item_id}/transfer-form")
async def transfer_form(
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(_TRANSFER_ROLES)),
):
    item = await db.get(InventoryItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    institutions = (
        await db.execute(
            select(Institution)
            .where(
                Institution.is_active.is_(True),
                Institution.id != item.institution_id,
            )
            .order_by(Institution.name)
        )
    ).scalars().all()

    return templates.TemplateResponse(
        "partials/transfer_form.html",
        {
            "request": request,
            "item": item,
            "institutions": institutions,
            "current_user": current_user,
        },
    )


# ── Mutations ─────────────────────────────────────────────────

@router.post("/issue")
async def issue_asset(
    request: Request,
    inventory_item_id: int = Form(...),
    quantity: int = Form(...),
    issued_to: str = Form(...),
    notes: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(_ALL_ROLES)),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    item = await db.get(InventoryItem, inventory_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")

    try:
        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")
        if quantity > item.quantity_available:
            raise ValueError(
                f"Insufficient stock. Available: {item.quantity_available}."
            )
    except ValueError as exc:
        return templates.TemplateResponse(
            "partials/issue_form.html",
            {
                "request": request,
                "item": item,
                "current_user": current_user,
                "error": str(exc),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    item.quantity_available -= quantity
    db.add(AssetMovement(
        inventory_item_id=inventory_item_id,
        movement_type=MovementType.ISSUE,
        quantity=quantity,
        issued_to=issued_to,
        performed_by_id=current_user.id,
        notes=notes or None,
    ))
    await log_action(
        db=db,
        user_id=current_user.id,
        action="ISSUE_ASSET",
        entity="InventoryItem",
        entity_id=item.id,
        details={"quantity": quantity, "issued_to": issued_to},
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()

    items = await _scoped_items(db, current_user)
    return _table_response(request, items, current_user, oob=True,
                           toast=f"Issued {quantity} item(s) to {issued_to}.")


@router.post("/return")
async def return_asset(
    request: Request,
    inventory_item_id: int = Form(...),
    quantity: int = Form(...),
    returned_by: str = Form(""),
    notes: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(_ALL_ROLES)),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    combined_notes = notes or None
    if returned_by:
        combined_notes = (
            f"Returned by {returned_by}"
            + (f" — {notes}" if notes else "")
        )

    try:
        await svc_return(
            db=db,
            item_id=inventory_item_id,
            quantity=quantity,
            notes=combined_notes,
            current_user=current_user,
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as exc:
        item = await db.get(InventoryItem, inventory_item_id)
        return templates.TemplateResponse(
            "partials/return_form.html",
            {
                "request": request,
                "item": item,
                "current_user": current_user,
                "error": str(exc),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    items = await _scoped_items(db, current_user)
    return _table_response(request, items, current_user, oob=True,
                           toast=f"Returned {quantity} item(s) successfully.")


@router.post("/transfer")
async def transfer_asset(
    request: Request,
    from_item_id: int = Form(...),
    to_institution_id: int = Form(...),
    quantity: int = Form(...),
    notes: str = Form(""),
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(_TRANSFER_ROLES)),
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    try:
        await svc_transfer(
            db=db,
            from_item_id=from_item_id,
            to_institution_id=to_institution_id,
            quantity=quantity,
            notes=notes or None,
            current_user=current_user,
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as exc:
        item = await db.get(InventoryItem, from_item_id)
        institutions = (
            await db.execute(
                select(Institution)
                .where(
                    Institution.is_active.is_(True),
                    Institution.id != (item.institution_id if item else 0),
                )
                .order_by(Institution.name)
            )
        ).scalars().all()
        return templates.TemplateResponse(
            "partials/transfer_form.html",
            {
                "request": request,
                "item": item,
                "institutions": institutions,
                "current_user": current_user,
                "error": str(exc),
            },
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    items = await _scoped_items(db, current_user)
    return _table_response(request, items, current_user, oob=True,
                           toast=f"Transferred {quantity} item(s) successfully.")
