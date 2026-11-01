"""Feishu H5 authentication helpers and protected preview delivery."""

import re
import tempfile
import zipfile
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse

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
    photo_id: str,
    request: Request,
    scope: str = Query(default="mine", pattern="^(mine|shared)$"),
    watermarked: bool = Query(default=True),
) -> RedirectResponse:
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import photo_object_for_user
    try:
        object_key = await photo_object_for_user(
            str(request.session["user_id"]), photo_id, preview=False, scope=scope, watermarked=watermarked,
        )
        return RedirectResponse(signed_download_url(settings.oss_bucket, object_key, download_name=f"qc-photo-{photo_id}.jpg"))
    except LookupError as exc:
        if "Unwatermarked" in str(exc):
            raise HTTPException(status_code=409, detail="该照片没有可用的无水印原图") from exc
        raise HTTPException(status_code=404, detail="Photo not found") from exc
    except OssError as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc


@router.get("/photos/download-batch")
async def download_photo_batch(
    request: Request,
    photo_ids: Annotated[list[str] | None, Query()] = None,
    scope: str = Query(default="mine", pattern="^(mine|shared)$"),
    watermarked: bool = Query(default=True),
) -> StreamingResponse:
    if not request.session.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    unique_ids = list(dict.fromkeys(photo_ids or []))
    if not unique_ids or len(unique_ids) > 50:
        raise HTTPException(status_code=422, detail="请选择 1 至 50 张照片")

    from app.services.dashboard_repository import photo_download_objects_for_user
    try:
        documents = await photo_download_objects_for_user(
            str(request.session["user_id"]), unique_ids, scope=scope, watermarked=watermarked,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        if "unwatermarked" in str(exc).lower():
            raise HTTPException(status_code=409, detail="所选照片中有历史照片没有无水印原图") from exc
        raise HTTPException(status_code=404, detail="One or more photos were not found") from exc

    archive_file = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)  # noqa: SIM115
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            with zipfile.ZipFile(archive_file, mode="w", compression=zipfile.ZIP_STORED) as archive:
                for index, document in enumerate(documents, start=1):
                    response = await client.get(signed_download_url(settings.oss_bucket, document["object_key"]))
                    response.raise_for_status()
                    archive.writestr(_zip_filename(document, index), response.content)
        archive_file.seek(0, 2)
        content_length = archive_file.tell()
        archive_file.seek(0)
    except (httpx.HTTPError, OssError) as exc:
        archive_file.close()
        raise HTTPException(status_code=502, detail="下载照片失败，请稍后重试") from exc

    async def stream_archive():
        try:
            while chunk := archive_file.read(1024 * 1024):
                yield chunk
        finally:
            archive_file.close()

    return StreamingResponse(
        stream_archive(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="qc-photos.zip"',
            "Content-Length": str(content_length),
        },
    )


def _zip_filename(document: dict[str, object], index: int) -> str:
    stem = "-".join(
        str(value).strip()
        for value in (document["contract_no"], document["inspection_item"], document["id"])
        if str(value).strip()
    )
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", stem).strip(" .-") or "qc-photo"
    return f"{index:03d}-{stem[:120]}.jpg"
