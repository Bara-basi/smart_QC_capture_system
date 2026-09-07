import json
from contextlib import AbstractAsyncContextManager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.photos import _manifest
from app.services import dashboard_repository as repository


def test_manifest_can_complete_previously_saved_photos():
    payload = _manifest(json.dumps({"contract_no": "C1", "mode": "complete", "task_ids": ["t1"], "photos": []}), 0)
    assert payload["task_ids"] == ["t1"]


@pytest.mark.parametrize("mode", ["invalid", None, [], {}])
def test_manifest_rejects_invalid_mode(mode):
    with pytest.raises(HTTPException):
        _manifest(json.dumps({"contract_no": "C1", "mode": mode, "photos": []}), 0)


def test_saved_required_photos_do_not_complete_task_or_sibling_order():
    tasks = [{"feishu_record_id": task_id, "contract_no": "C1", "product_type": "法兰", "inspection_status": "待处理"} for task_id in ["t1", "t2"]]
    mandatory = set(repository._requirements("法兰")) & repository._mandatory_items()
    photos = {"t1": mandatory, "t2": mandatory}
    assert not repository._task_is_complete(tasks[0], photos)
    assert repository._completion_statuses(tasks, photos, {"t1"}) == (["t1"], [])
    tasks[0]["inspection_status"] = "已提交"
    assert repository._task_is_complete(tasks[0], photos)
    assert repository._completion_statuses(tasks, photos, {"t2"}) == (["t1", "t2"], ["C1"])


@pytest.fixture
def database(monkeypatch):
    connection = MagicMock()
    connection.transaction.return_value = AsyncMock(spec=AbstractAsyncContextManager)
    connection.fetchrow = AsyncMock(return_value={"open_id": "u1", "name": "Inspector", "id": "p1"})
    connection.fetch = AsyncMock()
    connection.execute = AsyncMock()
    connection.close = AsyncMock()
    monkeypatch.setattr(repository.asyncpg, "connect", AsyncMock(return_value=connection))
    enqueue = AsyncMock(return_value=[])
    monkeypatch.setattr(repository, "enqueue_status_updates", enqueue)
    return connection, enqueue


def task():
    return {"feishu_record_id": "t1", "contract_no": "C1", "product_type": "法兰", "sequence_no": "1", "specification": "S1", "inspection_status": "待处理"}


@pytest.mark.asyncio
async def test_save_persists_photo_without_status_updates(database):
    connection, enqueue = database
    connection.fetch.return_value = [task()]
    photo = dict.fromkeys(["captured_at", "source", "factory_initials", "oss_object_key", "preview_oss_object_key", "original_filename", "content_type", "file_size_bytes", "sha256", "search_text"], "test")
    photo.update(task_id="t1", contract_no="C1", inspection_item="材质光谱", metadata={})
    result = await repository.commit_photo_records("u1", [photo], contract_no="C1", mode="save", submitted_task_ids=["t1"])
    assert result.photo_ids == ["p1"]
    assert result.sync_job_ids == []
    assert "INSERT INTO photo_records" in connection.fetchrow.call_args.args[0]
    connection.execute.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [False, True])
async def test_complete_saved_photos_validates_requirements(database, complete):
    connection, enqueue = database
    items = repository._mandatory_items() & set(repository._requirements("法兰")) if complete else set()
    connection.fetch.side_effect = [[task()], [task()], [{"task_feishu_record_id": "t1", "inspection_item": item} for item in items], [{"feishu_record_id": "order1"}]]
    if not complete:
        with pytest.raises(ValueError, match="必拍项缺失"):
            await repository.commit_photo_records("u1", [], contract_no="C1", submitted_task_ids=["t1"])
        connection.execute.assert_not_awaited()
        enqueue.assert_not_awaited()
    else:
        result = await repository.commit_photo_records("u1", [], contract_no="C1", submitted_task_ids=["t1"])
        assert result.photo_ids == []
        assert connection.execute.call_args.args[1:] == (["t1"], "已提交")
        assert enqueue.await_count == 2


@pytest.mark.asyncio
async def test_complete_rejects_task_from_other_contract(database):
    connection, enqueue = database
    connection.fetch.return_value = [task()]
    with pytest.raises(LookupError, match="contract"):
        await repository.commit_photo_records("u1", [], contract_no="OTHER", submitted_task_ids=["t1"])
    enqueue.assert_not_awaited()
