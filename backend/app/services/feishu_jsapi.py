"""Server-side signing for Feishu H5 JSAPI calls."""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.feishu_auth import FEISHU_API, FeishuAuthError, _response_json


@dataclass
class _Ticket:
    value: str
    expires_at: float


_ticket: _Ticket | None = None


async def jsapi_signature(url: str) -> dict[str, str | int]:
    """Return a signature without ever exposing the ticket or app secret."""
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise FeishuAuthError("Feishu JSAPI is not configured")
    ticket = await _get_ticket()
    nonce = secrets.token_urlsafe(16)
    timestamp = int(time.time() * 1000)
    plaintext = f"jsapi_ticket={ticket}&noncestr={nonce}&timestamp={timestamp}&url={url}"
    return {
        "app_id": settings.feishu_app_id,
        "noncestr": nonce,
        "timestamp": timestamp,
        "signature": hashlib.sha1(plaintext.encode("utf-8")).hexdigest(),
    }


async def _get_ticket() -> str:
    global _ticket
    if _ticket and _ticket.expires_at > time.time():
        return _ticket.value
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
        )
        token = _response_json(token_response, "get tenant access token").get("tenant_access_token")
        if not token:
            raise FeishuAuthError("Feishu did not return tenant_access_token")
        ticket_response = await client.post(
            f"{FEISHU_API}/jssdk/ticket/get",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = _response_json(ticket_response, "get JSAPI ticket")
    ticket = body.get("data", {}).get("ticket") or body.get("ticket")
    if not ticket:
        raise FeishuAuthError("Feishu did not return JSAPI ticket")
    _ticket = _Ticket(value=ticket, expires_at=time.time() + 7000)
    return ticket
