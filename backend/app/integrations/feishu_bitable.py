"""Small, dependency-free client for the Feishu Bitable record API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Self

import httpx

from app.core.config import settings

FEISHU_API = "https://open.feishu.cn/open-apis"


class FeishuBitableError(RuntimeError):
    pass


def _require_settings(table_id: str) -> None:
    if not all(
        (
            settings.feishu_app_id,
            settings.feishu_app_secret,
            settings.feishu_bitable_app_token,
            table_id,
        )
    ):
        raise FeishuBitableError("Feishu Bitable is not fully configured")


def _check_response(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise FeishuBitableError(
            f"Feishu could not {action}: non-JSON HTTP {response.status_code}"
        ) from exc
    if response.status_code >= 400 or body.get("code", 0) != 0:
        raise FeishuBitableError(
            f"Feishu could not {action}: {body.get('msg') or body.get('code') or response.status_code}"
        )
    return body


class FeishuBitableClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client
        self._owns_http_client = False
        self._tenant_access_token: str | None = None
        self._person_union_ids: dict[str, str] = {}

    async def __aenter__(self) -> Self:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=20.0)
            self._owns_http_client = True
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
        self._http_client = None
        self._owns_http_client = False

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http_client is not None:
            yield self._http_client
            return
        async with httpx.AsyncClient(timeout=20.0) as client:
            yield client

    async def _tenant_token(self, client: httpx.AsyncClient) -> str:
        if self._tenant_access_token:
            return self._tenant_access_token
        response = await client.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            },
        )
        body = _check_response(response, "obtain a tenant access token")
        token = body.get("tenant_access_token")
        if not token:
            raise FeishuBitableError("Feishu did not return a tenant access token")
        self._tenant_access_token = str(token)
        return self._tenant_access_token

    async def get_record(self, table_id: str, record_id: str) -> dict[str, Any]:
        """Read one Bitable record directly by its stable record ID."""
        _require_settings(table_id)
        if not record_id:
            raise FeishuBitableError("A Feishu Bitable record ID is required")
        async with self._client() as client:
            token = await self._tenant_token(client)
            response = await client.get(
                f"{FEISHU_API}/bitable/v1/apps/{settings.feishu_bitable_app_token}/tables/{table_id}/records/{record_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"user_id_type": "open_id"},
            )
            body = _check_response(response, "read a Bitable record")
        record = body.get("data", {}).get("record")
        if not isinstance(record, dict):
            raise FeishuBitableError(
                "Feishu did not return the requested Bitable record"
            )
        return record

    async def iter_records(
        self, table_id: str, view_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield all records visible in a view, including pagination."""
        _require_settings(table_id)
        if not view_id:
            raise FeishuBitableError("The Feishu Bitable view ID is not configured")
        async with self._client() as client:
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
                    raise FeishuBitableError(
                        "Feishu returned an incomplete pagination cursor"
                    )

    async def search_records(
        self,
        table_id: str,
        view_id: str,
        *,
        field_name: str,
        value: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield records matching one exact field value using server-side filtering."""
        _require_settings(table_id)
        if not field_name or not value:
            raise FeishuBitableError("A Bitable search field and value are required")
        async with self._client() as client:
            token = await self._tenant_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            page_token: str | None = None
            request_body: dict[str, Any] = {
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        {
                            "field_name": field_name,
                            "operator": "is",
                            "value": [value],
                        }
                    ],
                }
            }
            if view_id:
                request_body["view_id"] = view_id
            while True:
                params: dict[str, Any] = {
                    "page_size": 500,
                    "user_id_type": "open_id",
                }
                if page_token:
                    params["page_token"] = page_token
                response = await client.post(
                    f"{FEISHU_API}/bitable/v1/apps/{settings.feishu_bitable_app_token}/tables/{table_id}/records/search",
                    headers=headers,
                    params=params,
                    json=request_body,
                )
                body = _check_response(response, "search Bitable records")
                data = body.get("data", {})
                for record in data.get("items", []):
                    yield record
                if not data.get("has_more"):
                    return
                page_token = data.get("page_token")
                if not page_token:
                    raise FeishuBitableError(
                        "Feishu returned an incomplete search cursor"
                    )

    async def update_record_field(
        self,
        table_id: str,
        field_id: str,
        record_ids: list[str],
        value: Any,
    ) -> None:
        """Update one field for a group of records, validating the configured field ID first."""
        _require_settings(table_id)
        if not field_id:
            raise FeishuBitableError(
                "The Feishu Bitable status field ID is not configured"
            )
        if not record_ids:
            return
        async with self._client() as client:
            token = await self._tenant_token(client)
            headers = {"Authorization": f"Bearer {token}"}
            field_name = await self._field_name(client, headers, table_id, field_id)
            for start in range(0, len(record_ids), 1000):
                records = [
                    {"record_id": record_id, "fields": {field_name: value}}
                    for record_id in record_ids[start : start + 1000]
                ]
                response = await client.post(
                    f"{FEISHU_API}/bitable/v1/apps/{settings.feishu_bitable_app_token}/tables/{table_id}/records/batch_update",
                    headers=headers,
                    json={"records": records},
                )
                _check_response(response, "update Bitable records")

    async def _field_name(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        table_id: str,
        field_id: str,
    ) -> str:
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            response = await client.get(
                f"{FEISHU_API}/bitable/v1/apps/{settings.feishu_bitable_app_token}/tables/{table_id}/fields",
                headers=headers,
                params=params,
            )
            body = _check_response(response, "read Bitable fields")
            data = body.get("data", {})
            for field in data.get("items", []):
                if field.get("field_id") == field_id:
                    field_name = field.get("field_name")
                    if not field_name:
                        break
                    return str(field_name)
            if not data.get("has_more"):
                raise FeishuBitableError(
                    f"Feishu field {field_id} is not present in table {table_id}"
                )
            page_token = data.get("page_token")
            if not page_token:
                raise FeishuBitableError(
                    "Feishu returned an incomplete field pagination cursor"
                )

    async def get_person_union_id(self, open_id: str) -> str:
        """Resolve the Bitable person field's open_id to the requested union_id."""
        _require_settings(settings.feishu_bitable_table_id)
        cached = self._person_union_ids.get(open_id)
        if cached:
            return cached
        async with self._client() as client:
            token = await self._tenant_token(client)
            response = await client.get(
                f"{FEISHU_API}/contact/v3/users/{open_id}",
                params={"user_id_type": "open_id"},
                headers={"Authorization": f"Bearer {token}"},
            )
            body = _check_response(response, "resolve a Bitable person")
        union_id = body.get("data", {}).get("user", {}).get("union_id")
        if not union_id:
            raise FeishuBitableError(
                "Feishu did not return union_id; grant application-identity scope contact:contact.base:readonly"
            )
        self._person_union_ids[open_id] = str(union_id)
        return self._person_union_ids[open_id]
