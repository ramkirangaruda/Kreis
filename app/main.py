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


@app.get("/")
async def root():
    return RedirectResponse("/dashboard")
