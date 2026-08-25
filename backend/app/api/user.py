"""Feishu web OAuth endpoints and the current-user endpoint."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadData, URLSafeTimedSerializer

from app.core.config import settings
from app.services.feishu_auth import FeishuAuthError, exchange_code_and_get_user
from app.services.user_repository import DatabaseUnavailable, upsert_feishu_user

router = APIRouter(prefix="/auth", tags=["authentication"])


def callback_url() -> str:
    if not settings.web_origin:
        raise HTTPException(status_code=500, detail="WEB_ORIGIN is not configured")
    return f"{settings.web_origin.rstrip('/')}{settings.api_prefix}/auth/feishu/callback"


def state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="feishu-oauth-state")


def safe_return_path(value: str | None) -> str:
    """Accept only an application-local OAuth return path.

    The path is carried in the signed OAuth state because Feishu may not retain
    the session cookie during its authorization round-trip. Rejecting absolute
    URLs here prevents this endpoint from becoming an open redirector.
    """
    if not value:
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return "/"
    return value


@router.get("/feishu/login")
async def feishu_login(request: Request, next: str | None = None) -> RedirectResponse:
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        raise HTTPException(status_code=500, detail="Feishu OAuth is not configured")

    # The state is signed and short-lived, rather than stored in a browser
    # session. Feishu's embedded WebView may not retain a third-party session
    # cookie across the authorization redirect.
    state = state_serializer().dumps({"nonce": secrets.token_urlsafe(32), "return_path": safe_return_path(next)})
    query = urlencode(
        {
            "client_id": settings.feishu_app_id,
            "redirect_uri": callback_url(),
            "response_type": "code",
            # Required to receive the tenant-stable user_id. Request department
            # information in the Feishu console as documented in docs/setup.md.
            "scope": "contact:user.id:readonly",
            "state": state,
        }
    )
    return RedirectResponse(f"https://accounts.feishu.cn/open-apis/authen/v1/authorize?{query}", status_code=302)


@router.get("/feishu/callback")
async def feishu_callback(request: Request, code: str | None = None, state: str | None = None) -> RedirectResponse:
    if not code or not state:
        raise HTTPException(status_code=400, detail="Invalid or expired Feishu OAuth state")
    try:
        state_data = state_serializer().loads(state, max_age=600)
    except BadData as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired Feishu OAuth state") from exc

    try:
        feishu_user = await exchange_code_and_get_user(code)
        user = await upsert_feishu_user(feishu_user)
    except FeishuAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    request.session["user_id"] = str(user["id"])
    return RedirectResponse(f"{settings.web_origin.rstrip('/')}{safe_return_path(state_data.get('return_path'))}", status_code=302)


@router.get("/me")
async def current_user(request: Request) -> dict[str, object]:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from app.services.user_repository import current_user_profile
    try:
        return await current_user_profile(str(user_id))
    except DatabaseUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
