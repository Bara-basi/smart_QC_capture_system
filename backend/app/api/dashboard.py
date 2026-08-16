from fastapi import APIRouter, HTTPException, Request

from app.services.dashboard_repository import capture_task, inspector_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _user_id(request: Request) -> str:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(user_id)


@router.get("")
async def get_dashboard(request: Request) -> dict:
    try:
        return await inspector_dashboard(_user_id(request))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{record_id}")
async def get_capture_task(record_id: str, request: Request) -> dict:
    try:
        return await capture_task(_user_id(request), record_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
