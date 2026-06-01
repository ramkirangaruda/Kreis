from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from app.routers import (
    auth,
    dashboard,
    institutions,
    assets,
    inventory,
    reports
)

app = FastAPI(
    title="KREIS IMS",
    docs_url="/api/docs"
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
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


@app.get("/")
async def root():
    return RedirectResponse("/dashboard")