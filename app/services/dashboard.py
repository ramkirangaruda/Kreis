"""Dashboard statistics service.

The headline figures are gathered concurrently with asyncio.gather(). A
SQLAlchemy AsyncSession is *not* safe for concurrent use, so each gathered
coroutine opens its own short-lived session from AsyncSessionLocal — every
session draws an independent connection from the engine pool, which lets the
queries genuinely run in parallel.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.core.database import AsyncSessionLocal
from app.models.asset import Asset, AssetCategory
from app.models.institution import Institution
from app.models.inventory import InventoryItem, AssetMovement, MovementType
from app.models.user import User


async def _count_active_institutions(is_admin: bool) -> int:
    if not is_admin:
        # A principal / staff member only ever sees their own institution.
        return 1
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count(Institution.id)).where(
                Institution.is_active.is_(True)
            )
        )
        return result.scalar() or 0


async def _total_quantity(is_admin: bool, institution_id: int | None) -> int:
    async with AsyncSessionLocal() as db:
        query = select(func.coalesce(func.sum(InventoryItem.quantity_total), 0))
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return result.scalar() or 0


async def _low_stock_items(is_admin: bool, institution_id: int | None):
    async with AsyncSessionLocal() as db:
        query = (
            select(InventoryItem)
            .options(
                selectinload(InventoryItem.asset),
                selectinload(InventoryItem.institution),
            )
            .where(
                InventoryItem.quantity_available
                <= InventoryItem.low_stock_threshold
            )
            .order_by(InventoryItem.quantity_available.asc())
        )
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return list(result.scalars().all())


async def _pending_transfers(is_admin: bool, institution_id: int | None) -> int:
    """Count TRANSFER movements in the last 7 days that have no matching
    RECEIPT — i.e. stock that left a school but was never received."""
    async with AsyncSessionLocal() as db:
        # created_at is stored naive (UTC); compare against a naive cutoff.
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

        transfers_q = select(AssetMovement).where(
            AssetMovement.movement_type == MovementType.TRANSFER,
            AssetMovement.created_at >= cutoff,
        )
        receipts_q = select(AssetMovement).where(
            AssetMovement.movement_type == MovementType.RECEIPT,
            AssetMovement.created_at >= cutoff,
        )
        if not is_admin:
            transfers_q = transfers_q.where(
                AssetMovement.from_institution == institution_id
            )

        transfers = (await db.execute(transfers_q)).scalars().all()
        receipts = (await db.execute(receipts_q)).scalars().all()

        receipt_keys = {
            (r.from_institution, r.to_institution, r.quantity)
            for r in receipts
        }
        return sum(
            1
            for t in transfers
            if (t.from_institution, t.to_institution, t.quantity)
            not in receipt_keys
        )


async def _category_breakdown(is_admin: bool, institution_id: int | None):
    async with AsyncSessionLocal() as db:
        query = (
            select(
                AssetCategory.name,
                func.coalesce(func.sum(InventoryItem.quantity_total), 0),
                func.count(InventoryItem.id),
            )
            .select_from(AssetCategory)
            .join(Asset, Asset.category_id == AssetCategory.id)
            .join(InventoryItem, InventoryItem.asset_id == Asset.id)
            .group_by(AssetCategory.id, AssetCategory.name)
            .order_by(AssetCategory.code)
        )
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return [
            {"name": name, "total": int(total), "items": int(items)}
            for name, total, items in result.all()
        ]


async def _recent_movements(is_admin: bool, institution_id: int | None):
    async with AsyncSessionLocal() as db:
        query = (
            select(
                AssetMovement,
                Asset.name,
                Institution.name,
                User.full_name,
            )
            .join(
                InventoryItem,
                AssetMovement.inventory_item_id == InventoryItem.id,
            )
            .join(Asset, InventoryItem.asset_id == Asset.id)
            .join(Institution, InventoryItem.institution_id == Institution.id)
            .join(User, AssetMovement.performed_by_id == User.id)
            .order_by(AssetMovement.created_at.desc())
            .limit(10)
        )
        if not is_admin:
            query = query.where(
                InventoryItem.institution_id == institution_id
            )
        result = await db.execute(query)
        return [
            {
                "movement_type": movement.movement_type.value,
                "asset": asset_name,
                "institution": inst_name,
                "performed_by": user_name,
                "quantity": movement.quantity,
                "created_at": movement.created_at,
            }
            for movement, asset_name, inst_name, user_name in result.all()
        ]


async def get_dashboard_stats(db, current_user) -> dict:
    """Aggregate dashboard figures, scoped to the current user's role.

    `db` is accepted for interface consistency; the concurrent queries use
    their own sessions (see module docstring).
    """
    is_admin = current_user.role.value == "KREIS_ADMIN"
    institution_id = current_user.institution_id

    (
        total_institutions,
        total_assets,
        low_stock_items,
        pending_transfers,
        category_breakdown,
        recent_movements,
    ) = await asyncio.gather(
        _count_active_institutions(is_admin),
        _total_quantity(is_admin, institution_id),
        _low_stock_items(is_admin, institution_id),
        _pending_transfers(is_admin, institution_id),
        _category_breakdown(is_admin, institution_id),
        _recent_movements(is_admin, institution_id),
    )

    grand_total = sum(row["total"] for row in category_breakdown)
    for row in category_breakdown:
        row["percentage"] = (
            round(row["total"] / grand_total * 100, 1) if grand_total else 0.0
        )

    return {
        "total_institutions": total_institutions,
        "total_assets": total_assets,
        "low_stock_count": len(low_stock_items),
        "low_stock_items": low_stock_items,
        "pending_transfers": pending_transfers,
        "category_breakdown": category_breakdown,
        "recent_movements": recent_movements,
    }
