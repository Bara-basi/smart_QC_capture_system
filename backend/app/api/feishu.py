"""Feishu H5 authentication helpers and protected preview delivery."""

from __future__ import annotations

import asyncio
import re
import tempfile
import zipfile
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.integrations.aliyun_oss import OssError, read_image, signed_download_url
from app.services.feishu_auth import FeishuAuthError
from app.services.feishu_jsapi import jsapi_signature

router = APIRouter(prefix="/feishu", tags=["Feishu"])
MAX_BATCH_PHOTOS = 200
MAX_BATCH_BYTES = 512 * 1024 * 1024


class DownloadBatchRequest(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=MAX_BATCH_PHOTOS)
    scope: str = Field(default="mine", pattern="^(mine|shared)$")


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
) -> Response:
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import photo_object_for_user
    try:
        object_key = await photo_object_for_user(str(request.session["user_id"]), photo_id, preview=False, scope=scope)
        image = await asyncio.to_thread(read_image, settings.oss_bucket, object_key)
    except (LookupError, OssError) as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc
    return Response(
        content=image,
        media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="qc-photo-{photo_id}.jpg"'},
    )


@router.get("/photos/{photo_id}/download-url")
async def photo_download_url(
    photo_id: str,
    request: Request,
    scope: str = Query(default="mine", pattern="^(mine|shared)$"),
) -> dict[str, str]:
    """Return a short-lived OSS URL for the Feishu native download API."""
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import photo_object_for_user
    try:
        object_key = await photo_object_for_user(
            str(request.session["user_id"]), photo_id, preview=False, scope=scope
        )
        filename = f"qc-photo-{photo_id}.jpg"
        return {
            "url": signed_download_url(
                settings.oss_bucket,
                object_key,
                expires_in=300,
                download_name=filename,
            ),
            "filename": filename,
        }
    except (LookupError, OssError) as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc


@router.post("/photos/download-batch")
async def download_photo_batch(payload: DownloadBatchRequest, request: Request) -> StreamingResponse:
    """Package authorized originals into a ZIP without relying on a new-tab cookie."""
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import photo_downloads_for_user
    try:
        photos = await photo_downloads_for_user(
            str(request.session["user_id"]), payload.photo_ids, payload.scope
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    total_bytes = sum(int(photo["file_size_bytes"] or 0) for photo in photos)
    if total_bytes > MAX_BATCH_BYTES:
        raise HTTPException(status_code=413, detail="The selected photos exceed the 512 MB batch limit")
    try:
        archive = await asyncio.to_thread(_build_photo_archive, photos)
    except OssError as exc:
        raise HTTPException(status_code=502, detail="One or more photos could not be read") from exc

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    def chunks():
        try:
            while chunk := archive.read(1024 * 1024):
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="qc-photos-{timestamp}.zip"',
            "Cache-Control": "no-store",
        },
    )


def _build_photo_archive(photos: list) -> tempfile.SpooledTemporaryFile:
    archive = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            for photo in photos:
                image = read_image(settings.oss_bucket, str(photo["oss_object_key"]))
                bundle.writestr(_archive_photo_name(photo), image)
        archive.seek(0)
        return archive
    except Exception:
        archive.close()
        raise


def _archive_photo_name(photo: object) -> str:
    values = [
        str(photo["contract_no"] or "合同"),
        str(photo["product_type"] or "产品"),
        str(photo["specification"] or ""),
        str(photo["inspection_item"] or "照片"),
        str(photo["captured_at"].strftime("%Y%m%d-%H%M%S")),
    ]
    base = "_".join(value.strip() for value in values if value.strip())
    base = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", base).strip(" .-")
    suffix = str(photo["id"])[:8]
    return f"{base[:140] or 'qc-photo'}_{suffix}.jpg"
