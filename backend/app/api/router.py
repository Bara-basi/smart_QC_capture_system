from fastapi import APIRouter

from app.api.bitable import router as bitable_router
from app.api.dashboard import router as dashboard_router
from app.api.feishu import router as feishu_router
from app.api.photos import router as photos_router
from app.api.user import router as user_router

api_router = APIRouter()
api_router.include_router(user_router)
api_router.include_router(bitable_router)
api_router.include_router(dashboard_router)
api_router.include_router(feishu_router)
api_router.include_router(photos_router)


@api_router.get("/health", tags=["system"])
async def api_health_check() -> dict[str, str]:
    return {"status": "ok"}
