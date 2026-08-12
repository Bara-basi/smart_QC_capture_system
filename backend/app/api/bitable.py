"""Authenticated webhook consumed by Feishu Bitable Automation."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.core.config import settings
from app.integrations.feishu_bitable import FeishuBitableError
from app.services.bitable_sync import SyncValidationError, sync_order_webhook
from app.services.user_repository import DatabaseUnavailable

router = APIRouter(prefix="/integrations/feishu", tags=["Feishu Bitable"])


@router.post("/order-sync")
async def sync_order_from_bitable(
    payload: dict[str, Any], x_qc_sync_secret: str | None = Header(default=None),
) -> dict[str, int]:
    """Sync one ``record_id`` from an automation, or the entire order view."""
    expected = settings.feishu_sync_webhook_secret
    if not expected or expected.startswith("CHANGE_ME"):
        raise HTTPException(status_code=503, detail="FEISHU_SYNC_WEBHOOK_SECRET is not configured")
    if not x_qc_sync_secret or not secrets.compare_digest(x_qc_sync_secret, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
    try:
        return await sync_order_webhook(payload)
    except SyncValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (FeishuBitableError, DatabaseUnavailable) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
