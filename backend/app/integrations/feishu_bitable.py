"""Small, dependency-free client for the Feishu Bitable record API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import settings

FEISHU_API = "https://open.feishu.cn/open-apis"


class FeishuBitableError(RuntimeError):
    pass


def _require_settings(table_id: str) -> None:
    if not all((settings.feishu_app_id, settings.feishu_app_secret, settings.feishu_bitable_app_token, table_id)):
        raise FeishuBitableError("Feishu Bitable is not fully configured")


def _check_response(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise FeishuBitableError(f"Feishu could not {action}: non-JSON HTTP {response.status_code}") from exc
    if response.status_code >= 400 or body.get("code", 0) != 0:
        raise FeishuBitableError(f"Feishu could not {action}: {body.get('msg') or body.get('code') or response.status_code}")
    return body


class FeishuBitableClient:
    async def _tenant_token(self, client: httpx.AsyncClient) -> str:
        response = await client.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
        )
        body = _check_response(response, "obtain a tenant access token")
        token = body.get("tenant_access_token")
        if not token:
            raise FeishuBitableError("Feishu did not return a tenant access token")
        return token

    async def iter_records(self, table_id: str, view_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield all records visible in a view, including pagination."""
        _require_settings(table_id)
        if not view_id:
            raise FeishuBitableError("The Feishu Bitable view ID is not configured")
        async with httpx.AsyncClient(timeout=20.0) as client:
            token = await self._tenant_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {"view_id": view_id, "page_size": 500}
                if page_token:
                    params["page_token"] = page_token
                response = await client.get(
                    f"{FEISHU_API}/bitable/v1/apps/{settings.feishu_bitable_app_token}/tables/{table_id}/records",
                    headers=headers,
                    params=params,
                )
                body = _check_response(response, "read Bitable records")
                data = body.get("data", {})
                for record in data.get("items", []):
                    yield record
                if not data.get("has_more"):
                    return
                page_token = data.get("page_token")
                if not page_token:
                    raise FeishuBitableError("Feishu returned an incomplete pagination cursor")

    async def get_person_union_id(self, open_id: str) -> str:
        """Resolve the Bitable person field's open_id to the requested union_id."""
        _require_settings(settings.feishu_bitable_table_id)
        async with httpx.AsyncClient(timeout=20.0) as client:
            token = await self._tenant_token(client)
            response = await client.get(
                f"{FEISHU_API}/contact/v3/users/{open_id}",
                params={"user_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
            )
            body = _check_response(response, "resolve a Bitable person")
        union_id = body.get("data", {}).get("user", {}).get("union_id")
        if not union_id:
            raise FeishuBitableError("Feishu did not return union_id; grant application-identity scope contact:contact.base:readonly")
        return str(union_id)
