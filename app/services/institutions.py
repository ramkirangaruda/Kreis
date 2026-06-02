from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.models.institution import Institution
from app.models.inventory import InventoryItem, AssetMovement
from app.models.user import User
from app.models.asset import Asset, AssetCategory
from app.services.audit import log_action


async def list_institutions(
    db: AsyncSession,
    search: str = "",
    district: str = ""
) -> list:
    query = select(Institution).where(Institution.is_active == True)

    if search:
        query = query.where(Institution.name.ilike(f"%{search}%"))
    if district:
        query = query.where(Institution.district == district)

    result = await db.execute(query.order_by(Institution.name))
    return result.scalars().all()


async def get_all_districts(db: AsyncSession) -> list[str]:
    result = await db.execute(
        select(Institution.district)
        .where(Institution.is_active == True)
        .distinct()
        .order_by(Institution.district)
    )
    return [row[0] for row in result.all()]


async def get_institution(db: AsyncSession, inst_id: int) -> Institution:
    inst = await db.get(Institution, inst_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")
    return inst


async def get_institution_detail(db: AsyncSession, inst_id: int) -> dict:
    inst = await get_institution(db, inst_id)

    inv_result = await db.execute(
        select(InventoryItem)
        .options(
            selectinload(InventoryItem.asset).selectinload(Asset.category)
        )
        .where(InventoryItem.institution_id == inst_id)
    )
    inventory = inv_result.scalars().all()

    grouped: dict = {}
    for item in inventory:
        cat_name = (
            item.asset.category.name
            if item.asset and item.asset.category
            else "Uncategorized"
        )
        grouped.setdefault(cat_name, []).append(item)

    users_result = await db.execute(
        select(User)
        .where(User.institution_id == inst_id, User.is_active == True)
        .order_by(User.full_name)
    )
    users = users_result.scalars().all()

    movements_result = await db.execute(
        select(AssetMovement)
        .join(InventoryItem, AssetMovement.inventory_item_id == InventoryItem.id)
        .options(
            selectinload(AssetMovement.item).selectinload(InventoryItem.asset)
        )
        .where(InventoryItem.institution_id == inst_id)
        .order_by(AssetMovement.created_at.desc())
        .limit(10)
    )
    movements = movements_result.scalars().all()

    return {
        "institution": inst,
        "inventory_grouped": dict(sorted(grouped.items())),
        "users": users,
        "movements": movements,
    }


async def create_institution(
    db: AsyncSession,
    data: dict,
    current_user,
    ip: str | None = None
) -> Institution:
    code = data["code"].upper().strip()
    existing = await db.execute(
        select(Institution).where(Institution.code == code)
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Institution code '{code}' is already in use.")

    inst = Institution(
        name=data["name"].strip(),
        code=code,
        district=data["district"].strip(),
        address=data["address"].strip()
    )
    db.add(inst)
    await db.flush()

    await log_action(
        db=db,
        user_id=current_user.id,
        action="CREATE_INSTITUTION",
        entity="Institution",
        entity_id=inst.id,
        details={"name": inst.name, "code": inst.code},
        ip_address=ip
    )
    await db.commit()
    return inst


async def update_institution(
    db: AsyncSession,
    inst_id: int,
    data: dict,
    current_user,
    ip: str | None = None
) -> Institution:
    inst = await get_institution(db, inst_id)
    code = data["code"].upper().strip()

    if code != inst.code:
        existing = await db.execute(
            select(Institution).where(
                Institution.code == code,
                Institution.id != inst_id
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Institution code '{code}' is already in use.")

    inst.name = data["name"].strip()
    inst.code = code
    inst.district = data["district"].strip()
    inst.address = data["address"].strip()

    await log_action(
        db=db,
        user_id=current_user.id,
        action="UPDATE_INSTITUTION",
        entity="Institution",
        entity_id=inst.id,
        details={"name": inst.name, "code": inst.code},
        ip_address=ip
    )
    await db.commit()
    return inst


async def deactivate_institution(
    db: AsyncSession,
    inst_id: int,
    current_user,
    ip: str | None = None
):
    inst = await get_institution(db, inst_id)
    inst.is_active = False

    await log_action(
        db=db,
        user_id=current_user.id,
        action="DEACTIVATE_INSTITUTION",
        entity="Institution",
        entity_id=inst.id,
        details={"name": inst.name},
        ip_address=ip
    )
    await db.commit()
