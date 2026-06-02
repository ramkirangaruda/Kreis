from fastapi import APIRouter, Request, Depends, Form, Cookie, HTTPException, status
from fastapi.responses import RedirectResponse

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.core.csrf import validate_csrf_token
from app.core.templates import templates
from app.models.user import User

router = APIRouter()


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
    csrf_token: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

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
        httponly=True,
        samesite="lax",
        # Add secure=True once the app is served over HTTPS so the cookie is
        # only ever sent on encrypted connections.
    )

    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@router.get("/auth/change-password")
async def change_password_page(
    request: Request,
    access_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db)
):
    from app.core.security import decode_token
    from sqlalchemy import select

    if not access_token:
        return RedirectResponse("/login", status_code=302)

    payload = decode_token(access_token)
    if not payload:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(User).where(User.id == int(payload["sub"]))
    )
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse("/login", status_code=302)

    return templates.TemplateResponse(
        "auth/change_password.html",
        {"request": request, "current_user": user}
    )


@router.post("/auth/change-password")
async def change_password_submit(
    request: Request,
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(""),
    access_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db)
):
    from app.core.security import decode_token, hash_password
    from sqlalchemy import select

    if not validate_csrf_token(csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    if not access_token:
        return RedirectResponse("/login", status_code=302)

    payload = decode_token(access_token)
    if not payload:
        return RedirectResponse("/login", status_code=302)

    result = await db.execute(
        select(User).where(User.id == int(payload["sub"]))
    )
    user = result.scalar_one_or_none()
    if not user:
        return RedirectResponse("/login", status_code=302)

    error = None
    if len(new_password) < 8:
        error = "Password must be at least 8 characters."
    elif new_password != confirm_password:
        error = "Passwords do not match."

    if error:
        return templates.TemplateResponse(
            "auth/change_password.html",
            {"request": request, "current_user": user, "error": error},
            status_code=422
        )

    user.hashed_password = hash_password(new_password)
    user.password_change_required = False
    await db.commit()

    return RedirectResponse("/dashboard", status_code=302)