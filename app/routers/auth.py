from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import (
    verify_password,
    create_access_token
)
from app.models.user import User

router = APIRouter()

templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request}
    )


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where(User.email == email)
    )

    user = result.scalar_one_or_none()

    if not user or not verify_password(
        password,
        user.hashed_password
    ):
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "error": "Invalid credentials"
            }
        )

    token = create_access_token({
        "sub": str(user.id),
        "role": user.role.value
    })

    response = RedirectResponse(
        "/dashboard",
        status_code=302
    )

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True
    )

    return response