from fastapi import (
    APIRouter,
    Request,
    Depends,
    Form
)

from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user

from app.models.institution import Institution
from app.models.user import User


router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/")
async def list_institutions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    result = await db.execute(
        select(Institution)
    )

    institutions = result.scalars().all()

    return templates.TemplateResponse(
        "institutions/index.html",
        {
            "request": request,
            "institutions": institutions,
            "current_user": current_user
        }
    )


@router.get("/new")
async def new_institution_page(
    request: Request,
    current_user: User = Depends(get_current_user)
):

    return templates.TemplateResponse(
        "institutions/form.html",
        {
            "request": request,
            "current_user": current_user
        }
    )


@router.post("/new")
async def create_institution(
    name: str = Form(...),
    code: str = Form(...),
    district: str = Form(...),
    address: str = Form(...),

    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    institution = Institution(
        name=name,
        code=code,
        district=district,
        address=address
    )

    db.add(institution)

    await db.commit()

    return RedirectResponse(
        "/institutions",
        status_code=302
    )