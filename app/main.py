from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.core.templates import templates
from app.core.csrf import generate_csrf_token

from app.routers import (
    auth,
    dashboard,
    institutions,
    assets,
    inventory,
    reports,
    users,
    students,
    attendance,
    academics,
    documents,
    alumni,
)

app = FastAPI(
    title="KREIS IMS",
    docs_url="/api/docs"
)

# Make {{ csrf_token() }} available in every template.
templates.env.globals["csrf_token"] = generate_csrf_token

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    pass

# User-uploaded files (circulars, documents, bills). Importing the storage
# module ensures the uploads/ directory exists. Use a `from` import so the
# name `app` (the FastAPI instance) is not shadowed by the `app` package.
from app.core import storage as _storage  # noqa: E402,F401

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.include_router(auth.router, tags=["auth"])
app.include_router(dashboard.router, tags=["dashboard"])

app.include_router(
    institutions.router,
    prefix="/institutions",
    tags=["institutions"]
)

app.include_router(
    assets.router,
    prefix="/assets",
    tags=["assets"]
)

app.include_router(
    inventory.router,
    prefix="/inventory",
    tags=["inventory"]
)

app.include_router(
    reports.router,
    prefix="/reports",
    tags=["reports"]
)

app.include_router(
    users.router,
    prefix="/users",
    tags=["users"]
)

# ── School ERP routers (Phase 1 scaffolding) ──────────────────
app.include_router(
    students.router,
    prefix="/students",
    tags=["students"]
)

app.include_router(
    attendance.router,
    prefix="/attendance",
    tags=["attendance"]
)

app.include_router(
    academics.router,
    prefix="/academics",
    tags=["academics"]
)

app.include_router(
    documents.router,
    prefix="/documents",
    tags=["documents"]
)

app.include_router(
    alumni.router,
    prefix="/alumni",
    tags=["alumni"]
)


@app.get("/")
async def root():
    return RedirectResponse("/dashboard")
