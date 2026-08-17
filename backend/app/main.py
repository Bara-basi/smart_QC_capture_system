import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.services.feishu_status_sync import status_sync_worker


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = asyncio.Event()
    worker = asyncio.create_task(status_sync_worker(stop))
    try:
        yield
    finally:
        stop.set()
        await worker


app = FastAPI(title=settings.app_name, lifespan=lifespan)
if not settings.secret_key or settings.secret_key.startswith("CHANGE_ME"):
    raise RuntimeError("Set SECRET_KEY to a long random value before starting the API")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="qc_session",
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    # ngrok / production must use HTTPS. HTTP localhost remains usable during development.
    https_only=settings.web_origin.startswith("https://"),
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
