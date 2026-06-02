from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.templates import templates
from app.models.institution import Institution
from app.services.dashboard import get_dashboard_stats

router = APIRouter()


@router.get("/dashboard/partials/schools")
async def schools_partial(
    request: Request,
    district: str = "",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):

    query = select(Institution).where(Institution.is_active.is_(True))

    if district:
        query = query.where(
            Institution.district == district
        )

    # Non-admins only see their own institution.
    if current_user.role.value != "KREIS_ADMIN":
        query = query.where(Institution.id == current_user.institution_id)

    result = await db.execute(query)

    schools = result.scalars().all()

    return templates.TemplateResponse(
        "partials/school_table.html",
        {
            "request": request,
            "schools": schools,
            "current_user": current_user
        }
    )


@router.get("/dashboard")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    stats = await get_dashboard_stats(db, current_user)

    schools_query = select(Institution).where(Institution.is_active.is_(True))
    if current_user.role.value != "KREIS_ADMIN":
        schools_query = schools_query.where(
            Institution.id == current_user.institution_id
        )

    schools_result = await db.execute(schools_query)
    schools = schools_result.scalars().all()

    districts = sorted({school.district for school in schools})

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "current_user": current_user,
            "stats": stats,
            "schools": schools,
            "districts": districts
        }
    )
