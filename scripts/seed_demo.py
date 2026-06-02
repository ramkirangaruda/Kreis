"""Demo seed data for KREIS IMS.

Idempotent: existing records (matched by natural keys) are left untouched, so
the script can safely be re-run. Run with:

    python scripts/seed_demo.py
"""

import asyncio
import random
from datetime import datetime, timedelta

from sqlalchemy import select, func

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password

from app.models.user import User, UserRole
from app.models.institution import Institution
from app.models.asset import Asset, AssetCategory
from app.models.inventory import InventoryItem, AssetMovement, MovementType


CATEGORIES = [
    ("A", "Student Welfare & Uniform Assets"),
    ("B", "Library Management Assets"),
    ("C", "Classroom Furniture Assets"),
    ("D", "Smart Classroom Assets"),
    ("E", "Computer Laboratory Assets"),
    ("F", "Science Laboratory Assets"),
    ("G", "Hostel Assets & Amenities"),
]

# 5 realistic asset names per category (35 total).
ASSETS_BY_CATEGORY = {
    "A": ["School Uniform Set", "School Shoes", "Socks Pair", "Sweater", "School Bag"],
    "B": ["Bookshelf", "Reading Table", "Library Chair", "Book Trolley", "Catalogue Cabinet"],
    "C": ["Student Desk", "Student Chair", "Teacher Table", "Blackboard", "Notice Board"],
    "D": ["Interactive Whiteboard", "Projector", "Projector Screen", "Smart TV", "Speaker System"],
    "E": ["Desktop Computer", "LCD Monitor", "Keyboard", "UPS Unit", "Network Switch"],
    "F": ["Microscope", "Test Tube Set", "Bunsen Burner", "Lab Stool", "Chemical Cabinet"],
    "G": ["Bunk Bed", "Mattress", "Steel Almirah", "Study Lamp", "Water Purifier"],
}

INSTITUTIONS = [
    ("Rajiv Gandhi HS", "RGH-01", "District 3"),
    ("Nehru Model School", "NMS-01", "District 1"),
    ("Ambedkar Vidyalaya", "AV-01", "District 5"),
    ("Gandhi Govt School", "GGS-01", "District 2"),
    ("Saraswati HS", "SHS-01", "District 6"),
]

# (email, full_name, institution_code)
PRINCIPALS = [
    ("principal.rgh@kreis.edu", "Principal — Rajiv Gandhi HS", "RGH-01"),
    ("principal.nms@kreis.edu", "Principal — Nehru Model School", "NMS-01"),
    ("principal.av@kreis.edu", "Principal — Ambedkar Vidyalaya", "AV-01"),
    ("principal.ggs@kreis.edu", "Principal — Gandhi Govt School", "GGS-01"),
    ("principal.shs@kreis.edu", "Principal — Saraswati HS", "SHS-01"),
]

STUDENT_NAMES = [
    "Aarav Sharma", "Diya Patel", "Vivaan Reddy", "Ananya Iyer", "Arjun Nair",
    "Saanvi Rao", "Reyansh Gupta", "Ishaan Kumar", "Aadhya Menon", "Kabir Singh",
    "Myra Joshi", "Vihaan Das", "Anika Bose", "Aryan Pillai", "Navya Shetty",
]


async def _get_or_create_categories(db):
    for code, name in CATEGORIES:
        exists = (
            await db.execute(select(AssetCategory).where(AssetCategory.code == code))
        ).scalar_one_or_none()
        if not exists:
            db.add(AssetCategory(code=code, name=name))
    await db.flush()


async def _get_or_create_admin(db):
    exists = (
        await db.execute(select(User).where(User.email == "admin@kreis.edu"))
    ).scalar_one_or_none()
    if not exists:
        db.add(User(
            email="admin@kreis.edu",
            hashed_password=hash_password("changeme123"),
            full_name="KREIS Admin",
            role=UserRole.KREIS_ADMIN,
        ))
    await db.flush()


async def _get_or_create_institutions(db):
    for name, code, district in INSTITUTIONS:
        exists = (
            await db.execute(select(Institution).where(Institution.code == code))
        ).scalar_one_or_none()
        if not exists:
            db.add(Institution(
                name=name,
                code=code,
                district=district,
                address=f"{name}, {district}, Karnataka",
                is_active=True,
            ))
    await db.flush()


async def _get_or_create_principals(db, inst_by_code):
    for email, full_name, code in PRINCIPALS:
        exists = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if not exists:
            db.add(User(
                email=email,
                hashed_password=hash_password("School@1234"),
                full_name=full_name,
                role=UserRole.PRINCIPAL,
                institution_id=inst_by_code[code].id,
                password_change_required=True,
            ))
    await db.flush()


async def _get_or_create_assets(db, cat_by_code):
    for code, names in ASSETS_BY_CATEGORY.items():
        category = cat_by_code[code]
        for name in names:
            exists = (
                await db.execute(
                    select(Asset).where(
                        Asset.name == name, Asset.category_id == category.id
                    )
                )
            ).scalar_one_or_none()
            if not exists:
                db.add(Asset(
                    name=name,
                    category_id=category.id,
                    unit="Nos",
                    is_active=True,
                ))
    await db.flush()


async def _get_or_create_inventory(db, assets, institutions):
    existing_pairs = set(
        (await db.execute(
            select(InventoryItem.asset_id, InventoryItem.institution_id)
        )).all()
    )
    created = []
    for inst in institutions:
        for asset in assets:
            if (asset.id, inst.id) in existing_pairs:
                continue
            total = random.randint(20, 100)
            issued = random.randint(0, total // 2)
            item = InventoryItem(
                asset_id=asset.id,
                institution_id=inst.id,
                quantity_total=total,
                quantity_available=total - issued,
                low_stock_threshold=10,
            )
            db.add(item)
            created.append(item)
    await db.flush()
    return created


async def _ensure_low_stock(db, institutions):
    """Force at least 4 items, across different schools, to be low stock."""
    targets = []
    for inst in institutions[:4]:
        item = (
            await db.execute(
                select(InventoryItem)
                .where(InventoryItem.institution_id == inst.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if item:
            item.quantity_available = random.randint(0, 5)
            if item.quantity_total < item.quantity_available:
                item.quantity_total = item.quantity_available + 10
            targets.append(item)
    await db.flush()
    return targets


async def _generate_movements(db, principal_by_inst, institution_ids):
    existing = (await db.execute(select(func.count(AssetMovement.id)))).scalar() or 0
    if existing > 0:
        return 0

    items = (await db.execute(select(InventoryItem))).scalars().all()
    if not items:
        return 0

    types = [MovementType.ISSUE, MovementType.RETURN, MovementType.TRANSFER]
    now = datetime.utcnow()
    count = 0
    for _ in range(60):
        item = random.choice(items)
        mtype = random.choice(types)
        qty = random.randint(1, 10)
        performed_by = principal_by_inst.get(item.institution_id)
        if not performed_by:
            continue
        created_at = now - timedelta(
            days=random.randint(0, 29),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        movement = AssetMovement(
            inventory_item_id=item.id,
            movement_type=mtype,
            quantity=qty,
            performed_by_id=performed_by,
            created_at=created_at,
        )
        if mtype == MovementType.ISSUE:
            movement.issued_to = random.choice(STUDENT_NAMES)
            movement.notes = "Issued for classroom use"
        elif mtype == MovementType.RETURN:
            movement.notes = "Returned in good condition"
        else:  # TRANSFER
            others = [i for i in institution_ids if i != item.institution_id]
            movement.from_institution = item.institution_id
            movement.to_institution = random.choice(others) if others else None
            movement.notes = "Inter-school transfer"

        db.add(movement)
        count += 1

    await db.flush()
    return count


async def seed():
    async with AsyncSessionLocal() as db:
        await _get_or_create_categories(db)
        await _get_or_create_admin(db)
        await _get_or_create_institutions(db)

        institutions = (
            await db.execute(select(Institution).order_by(Institution.id))
        ).scalars().all()
        inst_by_code = {i.code: i for i in institutions}

        await _get_or_create_principals(db, inst_by_code)

        categories = (
            await db.execute(select(AssetCategory))
        ).scalars().all()
        cat_by_code = {c.code: c for c in categories}

        await _get_or_create_assets(db, cat_by_code)

        assets = (await db.execute(select(Asset))).scalars().all()

        await _get_or_create_inventory(db, assets, institutions)
        await _ensure_low_stock(db, institutions)

        principals = (
            await db.execute(
                select(User).where(User.role == UserRole.PRINCIPAL)
            )
        ).scalars().all()
        principal_by_inst = {p.institution_id: p.id for p in principals}

        movement_count = await _generate_movements(
            db, principal_by_inst, [i.id for i in institutions]
        )

        await db.commit()

        print("Demo seed complete.")
        print(f"  Institutions: {len(institutions)}")
        print(f"  Assets: {len(assets)}")
        print(f"  Principals: {len(principals)} (password: School@1234)")
        print(f"  Movements generated this run: {movement_count}")
        print("  Admin login: admin@kreis.edu / changeme123")


if __name__ == "__main__":
    asyncio.run(seed())
