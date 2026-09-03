"""Confirmation-only batch upload for locally staged capture drafts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile

from app.core.config import settings
from app.integrations.aliyun_oss import OssError, delete_image, upload_image
from app.services.dashboard_repository import commit_photo_records, commit_task_metadata
from app.services.feishu_status_sync import (
    FeishuStatusSyncConfigurationError,
    sync_pending_statuses,
)
from app.services.watermark import (
    WatermarkError,
    factory_initials,
    render_thumbnail,
    render_watermark,
    watermark_lines,
)

router = APIRouter(prefix="/photos", tags=["photos"])
logger = logging.getLogger(__name__)


@router.get("")
async def list_photos(
    request: Request,
    product_type: str | None = Query(default=None),
    inspection_category: str | None = Query(default=None),
    captured_from: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    captured_to: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    scope: str = Query(default="mine", pattern="^(mine|shared)$"),
    q: str | None = Query(default=None, max_length=200),
) -> dict[str, object]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        from app.services.dashboard_repository import inspector_photos
        photos = await inspector_photos(
            str(user_id), product_type=product_type, inspection_category=inspection_category,
            captured_from=captured_from, captured_to=captured_to, sort=sort, scope=scope, search=q,
        )
        return {"photos": photos, "count": len(photos)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
MAX_IMAGE_BYTES = 15 * 1024 * 1024


@router.post("/commit")
async def commit_photos(request: Request, manifest: str = Form(...), files: list[UploadFile] = File(...)) -> dict[str, object]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _manifest(manifest, len(files))
    items: list[dict[str, object]] = payload["photos"]
    try:
        task_map = await commit_task_metadata(str(user_id), [str(item["task_feishu_record_id"]) for item in items], str(payload["contract_no"]))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    prepared: list[dict[str, object]] = []
    for item in items:
        file = files[int(item["file_index"])]
        image = await file.read(MAX_IMAGE_BYTES + 1)
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Each image must be between 1 byte and 15 MB")
        if not _is_supported_image(image):
            raise HTTPException(status_code=415, detail="Only JPEG, PNG and WebP images are supported")
        task = task_map[str(item["task_feishu_record_id"])]
        captured_at = datetime.now(UTC).astimezone()
        try:
            watermarked, content_type = await asyncio.to_thread(
                render_watermark, image, watermark_lines(task["contract_no"], task["sequence_no"], task["specification"], captured_at)
            )
            preview = await asyncio.to_thread(render_thumbnail, watermarked)
        except WatermarkError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        object_key, preview_key = _object_keys(str(task["contract_no"]), str(item["task_feishu_record_id"]))
        factory = factory_initials(str(task["contract_no"]))
        prepared.append({
            "task_id": str(item["task_feishu_record_id"]), "contract_no": str(payload["contract_no"]), "inspection_item": str(item["inspection_item"]),
            "captured_at": captured_at, "source": "feishu_h5_camera", "factory_initials": factory,
            "oss_object_key": object_key, "preview_oss_object_key": preview_key, "original_filename": file.filename,
            "content_type": content_type, "file_size_bytes": len(watermarked), "sha256": hashlib.sha256(watermarked).hexdigest(),
            "watermarked": watermarked, "preview": preview,
            "metadata": {"source": "feishu_h5_camera", "watermarked": True, "preview_bucket": settings.oss_preview_bucket, "client_captured_at": item["client_captured_at"], "inspection_note": item.get("inspection_note", "")},
            "search_text": " ".join(str(value) for value in (task["contract_no"], factory or "", task["sequence_no"] or "", task["product_type"] or "", task["specification"] or "", item["inspection_item"], task["name"] or "") if value),
        })

    uploaded: list[tuple[str, str]] = []
    try:
        for photo in prepared:
            uploaded.append((settings.oss_bucket, str(photo["oss_object_key"])))
            uploaded.append((settings.oss_preview_bucket, str(photo["preview_oss_object_key"])))
            await asyncio.gather(
                asyncio.to_thread(upload_image, settings.oss_bucket, str(photo["oss_object_key"]), bytes(photo["watermarked"]), str(photo["content_type"])),
                asyncio.to_thread(upload_image, settings.oss_preview_bucket, str(photo["preview_oss_object_key"]), bytes(photo["preview"]), str(photo["content_type"])),
            )
        commit_result = await commit_photo_records(str(user_id), prepared)
    except FeishuStatusSyncConfigurationError as exc:
        await _cleanup_uploaded(uploaded)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OssError as exc:
        await _cleanup_uploaded(uploaded)
        raise HTTPException(status_code=502, detail="Photo upload failed; no photos were saved") from exc
    except Exception as exc:
        await _cleanup_uploaded(uploaded)
        raise HTTPException(status_code=500, detail="Photo metadata could not be saved; no photos were saved") from exc
    try:
        feishu_sync = await sync_pending_statuses(commit_result.sync_job_ids)
    except Exception:
        # Photos and the durable outbox are already committed. Never report an
        # upload failure here, otherwise the client may upload the same batch twice.
        logger.exception("Immediate Feishu status synchronization failed; queued for retry")
        feishu_sync = {"synced": 0, "pending": len(commit_result.sync_job_ids)}
    return {
        "photo_ids": commit_result.photo_ids,
        "count": len(commit_result.photo_ids),
        "feishu_sync": feishu_sync,
    }


async def _cleanup_uploaded(uploaded: list[tuple[str, str]]) -> None:
    for bucket, object_key in reversed(uploaded):
        try:
            await asyncio.to_thread(delete_image, bucket, object_key)
        except Exception:
            logger.exception("Could not remove failed upload object %s", object_key)


@router.delete("/{photo_id}")
async def delete_photo(photo_id: str, request: Request) -> dict[str, bool]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.dashboard_repository import delete_photo_for_inspector
    try:
        original_key, preview_key = await delete_photo_for_inspector(str(user_id), photo_id)
        delete_image(settings.oss_bucket, original_key)
        delete_image(settings.oss_preview_bucket, preview_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc
    except OssError as exc:
        raise HTTPException(status_code=502, detail="Photo was removed from the record but OSS cleanup failed") from exc
    return {"deleted": True}


def _manifest(value: str, file_count: int) -> dict[str, object]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid upload manifest") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("contract_no"), str) or not isinstance(payload.get("photos"), list):
        raise HTTPException(status_code=400, detail="Invalid upload manifest")
    items = payload["photos"]
    if not items or len(items) != file_count:
        raise HTTPException(status_code=400, detail="Every submitted photo must have one file")
    indexes = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("file_index"), int) or not isinstance(item.get("task_feishu_record_id"), str) or not isinstance(item.get("inspection_item"), str) or not isinstance(item.get("client_captured_at"), str):
            raise HTTPException(status_code=400, detail="Invalid photo manifest item")
        if not item["inspection_item"].strip() or item["file_index"] < 0 or item["file_index"] >= file_count:
            raise HTTPException(status_code=400, detail="Invalid photo manifest item")
        note = item.get("inspection_note", "")
        if not isinstance(note, str) or len(note.strip()) > 500:
            raise HTTPException(status_code=400, detail="Photo note must be at most 500 characters")
        item["inspection_note"] = note.strip()
        indexes.add(item["file_index"])
    if indexes != set(range(file_count)):
        raise HTTPException(status_code=400, detail="Invalid file indexes")
    return payload


def _object_keys(contract_no: str, task_id: str) -> tuple[str, str]:
    safe_contract = "".join(char if char.isalnum() else "-" for char in contract_no).strip("-") or "unknown-contract"
    base = "/".join(part for part in (settings.oss_prefix.strip("/"), safe_contract, task_id, uuid4().hex) if part)
    return f"{base}.jpg", f"{base}-preview.jpg"


def _is_supported_image(image: bytes) -> bool:
    return image.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")) or (image.startswith(b"RIFF") and image[8:12] == b"WEBP")
