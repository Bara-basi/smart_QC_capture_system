"""Feishu H5 authentication helpers and protected preview delivery."""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.integrations.aliyun_oss import OssError, signed_download_url
from app.services.feishu_auth import FeishuAuthError
from app.services.feishu_jsapi import jsapi_signature

router = APIRouter(prefix="/feishu", tags=["Feishu"])


@router.get("/jsapi-signature")
async def get_jsapi_signature(request: Request, url: str = Query(min_length=1, max_length=2048)) -> dict[str, str | int]:
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return await jsapi_signature(url)
    except FeishuAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/photos/{photo_id}/preview")
async def preview_photo(
    photo_id: str, request: Request, scope: str = Query(default="mine", pattern="^(mine|shared)$"),
) -> RedirectResponse:
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import photo_object_for_user
    try:
        object_key = await photo_object_for_user(str(request.session["user_id"]), photo_id, preview=True, scope=scope)
        return RedirectResponse(signed_download_url(settings.oss_preview_bucket, object_key))
    except (LookupError, OssError) as exc:
        raise HTTPException(status_code=404, detail="Preview not found") from exc


@router.get("/photos/{photo_id}/full")
async def full_photo(
    photo_id: str, request: Request, scope: str = Query(default="mine", pattern="^(mine|shared)$"),
) -> RedirectResponse:
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import photo_object_for_user
    try:
        object_key = await photo_object_for_user(str(request.session["user_id"]), photo_id, preview=False, scope=scope)
        return RedirectResponse(signed_download_url(settings.oss_bucket, object_key))
    except (LookupError, OssError) as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc


@router.get("/photos/{photo_id}/download")
async def download_photo(
    photo_id: str, request: Request, scope: str = Query(default="mine", pattern="^(mine|shared)$"),
) -> RedirectResponse:
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import photo_object_for_user
    try:
        object_key = await photo_object_for_user(str(request.session["user_id"]), photo_id, preview=False, scope=scope)
        return RedirectResponse(signed_download_url(settings.oss_bucket, object_key, download_name=f"qc-photo-{photo_id}.jpg"))
    except (LookupError, OssError) as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc
