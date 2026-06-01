from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def get_assets():
    return {"message": "Assets route working"}