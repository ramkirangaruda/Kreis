from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.institution import Institution
from app.models.inventory import InventoryItem, AssetMovement, MovementType
from app.models.user import User, UserRole
from app.services.audit import log_action


async def get_movement_history(
    db: AsyncSession,
    current_user,
    institution_id: int | None = None,
    asset_id: int | None = None,
    movement_type: str | None = None,
    days: int = 30,
):
    """Return movement records (joined with asset / institution / performer),
    scoped to the current user's institution unless they are an admin."""
    query = (
        select(
            AssetMovement,
            Asset.name,
            Institution.name,
            User.full_name,
        )
        .join(InventoryItem, AssetMovement.inventory_item_id == InventoryItem.id)
        .join(Asset, InventoryItem.asset_id == Asset.id)
        .join(Institution, InventoryItem.institution_id == Institution.id)
        .join(User, AssetMovement.performed_by_id == User.id)
        .order_by(AssetMovement.created_at.desc())
    )

    if current_user.role != UserRole.KREIS_ADMIN:
        query = query.where(
            InventoryItem.institution_id == current_user.institution_id
        )
    elif institution_id:
        query = query.where(InventoryItem.institution_id == institution_id)

    if asset_id:
        query = query.where(InventoryItem.asset_id == asset_id)

    if movement_type:
        try:
            query = query.where(
                AssetMovement.movement_type == MovementType(movement_type)
            )
        except ValueError:
            pass

    if days and days > 0:
        # created_at is stored naive (UTC); compare against a naive cutoff.
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
        query = query.where(AssetMovement.created_at >= cutoff)

    result = await db.execute(query)
    return [
        {
            "movement_type": movement.movement_type.value,
            "asset": asset_name,
            "institution": inst_name,
            "performed_by": user_name,
            "quantity": movement.quantity,
            "notes": movement.notes,
            "issued_to": movement.issued_to,
            "created_at": movement.created_at,
        }
        for movement, asset_name, inst_name, user_name in result.all()
    ]


async def return_asset(
    db: AsyncSession,
    item_id: int,
    quantity: int,
    current_user,
    notes: str | None = None,
    ip_address: str | None = None
):
    item = await db.get(InventoryItem, item_id)

    if not item:
        raise ValueError(f"Inventory item {item_id} not found.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if item.quantity_available + quantity > item.quantity_total:
        raise ValueError(
            f"Return would exceed total stock. "
            f"Available: {item.quantity_available}, Total: {item.quantity_total}."
        )

    item.quantity_available += quantity
    db.add(AssetMovement(
        inventory_item_id=item_id,
        movement_type=MovementType.RETURN,
        quantity=quantity,
        performed_by_id=current_user.id,
        notes=notes
    ))
    await log_action(
        db=db,
        user_id=current_user.id,
        action="RETURN_ASSET",
        entity="InventoryItem",
        entity_id=item.id,
        details={"quantity": quantity},
        ip_address=ip_address
    )
    await db.commit()


async def transfer_asset(
    db: AsyncSession,
    from_item_id: int,
    to_institution_id: int,
    quantity: int,
    current_user,
    notes: str | None = None,
    ip_address: str | None = None
):
    source = await db.get(InventoryItem, from_item_id)

    if not source:
        raise ValueError(f"Source inventory item {from_item_id} not found.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if quantity > source.quantity_available:
        raise ValueError(
            f"Insufficient stock at source. Available: {source.quantity_available}."
        )

    source.quantity_available -= quantity
    db.add(AssetMovement(
        inventory_item_id=source.id,
        movement_type=MovementType.TRANSFER,
        quantity=quantity,
        from_institution=source.institution_id,
        to_institution=to_institution_id,
        performed_by_id=current_user.id,
        notes=notes
    ))

    dest_result = await db.execute(
        select(InventoryItem).where(
            InventoryItem.asset_id == source.asset_id,
            InventoryItem.institution_id == to_institution_id
        )
    )
    dest = dest_result.scalar_one_or_none()

    if dest is None:
        dest = InventoryItem(
            asset_id=source.asset_id,
            institution_id=to_institution_id,
            quantity_total=0,
            quantity_available=0,
            low_stock_threshold=source.low_stock_threshold
        )
        db.add(dest)
        await db.flush()

    dest.quantity_available += quantity
    dest.quantity_total += quantity

    db.add(AssetMovement(
        inventory_item_id=dest.id,
        movement_type=MovementType.RECEIPT,
        quantity=quantity,
        from_institution=source.institution_id,
        to_institution=to_institution_id,
        performed_by_id=current_user.id,
        notes=notes
    ))
    await log_action(
        db=db,
        user_id=current_user.id,
        action="TRANSFER_ASSET",
        entity="InventoryItem",
        entity_id=source.id,
        details={
            "quantity": quantity,
            "from_institution": source.institution_id,
            "to_institution": to_institution_id
        },
        ip_address=ip_address
    )
    await db.commit()
