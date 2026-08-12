"""Small HTTP client for the current Feishu OAuth endpoints.

Tokens are deliberately not persisted: this application only needs Feishu to
establish its own browser session and identify the person opening the page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings

FEISHU_API = "https://open.feishu.cn/open-apis"
logger = logging.getLogger(__name__)


def callback_url() -> str:
    return f"{settings.web_origin.rstrip('/')}{settings.api_prefix}/auth/feishu/callback"


class FeishuAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeishuUser:
    user_id: str
    open_id: str
    union_id: str | None
    tenant_key: str | None
    name: str
    department_ids: list[str]


async def exchange_code_and_get_user(code: str) -> FeishuUser:
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.post(
            f"{FEISHU_API}/authen/v2/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": settings.feishu_app_id,
                "client_secret": settings.feishu_app_secret,
                "code": code,
                # Feishu validates this value against the value used to obtain
                # the authorization code; omitting it produces HTTP 400/20071.
                "redirect_uri": callback_url(),
            },
        )
        token_body = _response_json(token_response, "exchange authorization code")
        token_data = token_body.get("data", token_body)
        access_token = token_data.get("access_token")
        if not access_token:
            raise FeishuAuthError("Feishu did not return user_access_token")

        user_response = await client.get(
            f"{FEISHU_API}/authen/v1/user_info",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_body = _response_json(user_response, "get user information")
        data = user_body.get("data", user_body)

        user_id = data.get("user_id")
        if not user_id:
            raise FeishuAuthError(
                "Feishu did not return user_id. Enable the self-built-app permission "
                "'Get user user ID' and approve it, then authorize again."
            )
        open_id = data.get("open_id")
        if not open_id:
            raise FeishuAuthError("Feishu did not return open_id")

        department_ids: list[str] = []
        # Disabled by default while the application is being brought online.
        # It can be enabled after the app has an application-identity Contact
        # scope and the correct Contact permission range.
        if settings.feishu_sync_departments:
            try:
                department_ids = await _get_departments(client, user_id)
            except FeishuAuthError as exc:
                logger.warning("Feishu department sync skipped for user_id=%s: %s", user_id, exc)
        return FeishuUser(
            user_id=user_id,
            open_id=open_id,
            union_id=data.get("union_id"),
            tenant_key=data.get("tenant_key"),
            name=data.get("name") or user_id,
            department_ids=department_ids,
        )


async def _get_departments(client: httpx.AsyncClient, user_id: str) -> list[str]:
    """Fetch stable open_department_id values using the app's tenant token."""
    tenant_response = await client.post(
        f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
        json={"app_id": settings.feishu_app_id, "app_secret": settings.feishu_app_secret},
    )
    tenant_body = _response_json(tenant_response, "get tenant access token")
    tenant_token = tenant_body.get("tenant_access_token") or tenant_body.get("data", {}).get("tenant_access_token")
    if not tenant_token:
        raise FeishuAuthError("Feishu did not return tenant_access_token")

    response = await client.get(
        f"{FEISHU_API}/contact/v3/users/{user_id}",
        params={"user_id_type": "user_id", "department_id_type": "open_department_id"},
        headers={"Authorization": f"Bearer {tenant_token}"},
    )
    body = _response_json(response, "get user department information")
    return list(body.get("data", {}).get("user", {}).get("department_ids") or [])


def _response_json(response: httpx.Response, action: str) -> dict:
    try:
        body = response.json()
    except ValueError as exc:
        raise FeishuAuthError(f"Unable to {action}: Feishu returned HTTP {response.status_code} with a non-JSON response") from exc
    if response.status_code >= 400:
        detail = body.get("error_description") or body.get("msg") or body.get("error") or body.get("code") or response.text
        raise FeishuAuthError(f"Unable to {action}: Feishu HTTP {response.status_code}: {detail}")
    if body.get("code", 0) != 0:
        detail = body.get("error_description") or body.get("msg") or body.get("error") or body.get("code")
        raise FeishuAuthError(f"Feishu failed to {action}: {detail}")
    return body
