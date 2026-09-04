"""Authenticated webhook consumed by Feishu Bitable Automation."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app.core.config import settings
from app.integrations.feishu_bitable import FeishuBitableError
from app.services.bitable_sync import (
    SyncValidationError,
    sync_order_webhook,
    unassign_order_webhook,
)
from app.services.user_repository import DatabaseUnavailable

router = APIRouter(prefix="/integrations/feishu", tags=["Feishu Bitable"])


def _verify_webhook_secret(value: str | None) -> None:
    expected = settings.feishu_sync_webhook_secret
    if not expected or expected.startswith("CHANGE_ME"):
        raise HTTPException(
            status_code=503,
            detail="FEISHU_SYNC_WEBHOOK_SECRET is not configured",
        )
    if not value or not secrets.compare_digest(value, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


@router.post("/order-sync")
async def sync_order_from_bitable(
    payload: dict[str, Any], x_qc_sync_secret: str | None = Header(default=None),
) -> dict[str, int]:
    """Sync one ``record_id`` from a Bitable automation."""
    _verify_webhook_secret(x_qc_sync_secret)
    try:
        return await sync_order_webhook(payload)
    except SyncValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (FeishuBitableError, DatabaseUnavailable) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/order-unassign")
async def unassign_order_from_bitable(
    payload: dict[str, Any], x_qc_sync_secret: str | None = Header(default=None),
) -> dict[str, int]:
    """Clear one synchronized order's local inspector assignment."""
    _verify_webhook_secret(x_qc_sync_secret)
    try:
        return await unassign_order_webhook(payload)
    except SyncValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
