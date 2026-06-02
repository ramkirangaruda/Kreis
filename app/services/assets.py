from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.models.asset import Asset, AssetCategory
from app.models.inventory import InventoryItem
from app.services.audit import log_action


async def list_categories(db: AsyncSession) -> list:
    result = await db.execute(
        select(AssetCategory).order_by(AssetCategory.code)
    )
    return result.scalars().all()


async def list_assets(
    db: AsyncSession,
    category_id: int | None = None,
    search: str = ""
) -> list:
    query = (
        select(Asset)
        .options(selectinload(Asset.category))
        .order_by(Asset.name)
    )

    if category_id:
        query = query.where(Asset.category_id == category_id)
    if search:
        query = query.where(Asset.name.ilike(f"%{search}%"))

    result = await db.execute(query)
    return result.scalars().all()


async def get_asset(db: AsyncSession, asset_id: int) -> Asset:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


async def create_asset(
    db: AsyncSession,
    data: dict,
    current_user,
    ip: str | None = None
) -> Asset:
    # Unique name within category
    existing = await db.execute(
        select(Asset).where(
            Asset.name == data["name"].strip(),
            Asset.category_id == int(data["category_id"])
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(
            f"An asset named '{data['name']}' already exists in this category."
        )

    asset = Asset(
        category_id=int(data["category_id"]),
        name=data["name"].strip(),
        unit=data["unit"].strip(),
        description=data.get("description", "").strip() or None
    )
    db.add(asset)
    await db.flush()

    await log_action(
        db=db,
        user_id=current_user.id,
        action="CREATE_ASSET",
        entity="Asset",
        entity_id=asset.id,
        details={"name": asset.name, "category_id": asset.category_id},
        ip_address=ip
    )
    await db.commit()
    return asset


async def update_asset(
    db: AsyncSession,
    asset_id: int,
    data: dict,
    current_user,
    ip: str | None = None
) -> Asset:
    asset = await get_asset(db, asset_id)
    new_name = data["name"].strip()
    new_cat = int(data["category_id"])

    if new_name != asset.name or new_cat != asset.category_id:
        existing = await db.execute(
            select(Asset).where(
                Asset.name == new_name,
                Asset.category_id == new_cat,
                Asset.id != asset_id
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(
                f"An asset named '{new_name}' already exists in this category."
            )

    asset.name = new_name
    asset.category_id = new_cat
    asset.unit = data["unit"].strip()
    asset.description = data.get("description", "").strip() or None

    await log_action(
        db=db,
        user_id=current_user.id,
        action="UPDATE_ASSET",
        entity="Asset",
        entity_id=asset.id,
        details={"name": asset.name},
        ip_address=ip
    )
    await db.commit()
    return asset


async def deactivate_asset(
    db: AsyncSession,
    asset_id: int,
    current_user,
    ip: str | None = None
):
    asset = await get_asset(db, asset_id)

    # Block if active inventory with stock exists
    inv_result = await db.execute(
        select(func.count(InventoryItem.id)).where(
            InventoryItem.asset_id == asset_id,
            InventoryItem.quantity_total > 0
        )
    )
    if inv_result.scalar() > 0:
        raise ValueError(
            "Cannot deactivate an asset that has active inventory. "
            "Transfer or write off stock first."
        )

    asset.is_active = False

    await log_action(
        db=db,
        user_id=current_user.id,
        action="DEACTIVATE_ASSET",
        entity="Asset",
        entity_id=asset.id,
        details={"name": asset.name},
        ip_address=ip
    )
    await db.commit()
