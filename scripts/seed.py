import asyncio

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password

from app.models.user import User, UserRole
from app.models.asset import AssetCategory


CATEGORIES = [
    ("A", "Student Welfare & Uniform Assets"),
    ("B", "Library Management Assets"),
    ("C", "Classroom Furniture Assets"),
    ("D", "Smart Classroom Assets"),
    ("E", "Computer Laboratory Assets"),
    ("F", "Science Laboratory Assets"),
    ("G", "Hostel Assets & Amenities"),
]


async def seed():

    async with AsyncSessionLocal() as db:

        existing_admin = await db.execute(
            select(User).where(
                User.email == "admin@kreis.edu"
            )
        )

        admin_exists = existing_admin.scalar_one_or_none()

        if not admin_exists:

            admin = User(
                email="admin@kreis.edu",
                hashed_password=hash_password("changeme123"),
                full_name="KREIS Admin",
                role=UserRole.KREIS_ADMIN,
            )

            db.add(admin)

        for code, name in CATEGORIES:

            existing_category = await db.execute(
                select(AssetCategory).where(
                    AssetCategory.code == code
                )
            )

            category_exists = existing_category.scalar_one_or_none()

            if not category_exists:
                db.add(
                    AssetCategory(
                        code=code,
                        name=name,
                    )
                )

        await db.commit()

        print(
            "Seed complete. "
            "Login: admin@kreis.edu / changeme123"
        )


asyncio.run(seed())