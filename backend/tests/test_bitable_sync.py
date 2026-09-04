from __future__ import annotations

import asyncio
import json
from typing import Any, Self

import httpx
import pytest
from app.core.config import settings
from app.integrations.feishu_bitable import FeishuBitableClient
from app.services import bitable_sync


def _configure_feishu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql://qc:test@db/qc")
    monkeypatch.setattr(settings, "feishu_app_id", "cli_test")
    monkeypatch.setattr(settings, "feishu_app_secret", "secret")
    monkeypatch.setattr(settings, "feishu_bitable_app_token", "app_token")
    monkeypatch.setattr(settings, "feishu_bitable_order_table_id", "tbl_order")
    monkeypatch.setattr(settings, "feishu_bitable_table_id", "tbl_task")
    monkeypatch.setattr(
        settings,
        "feishu_bitable_inspection_task_view_id",
        "vew_task",
    )


def test_bitable_client_reuses_token_and_applies_server_side_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_feishu(monkeypatch)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/auth/v3/tenant_access_token/internal"):
            return httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "tenant_token"},
            )
        if request.method == "GET" and request.url.path.endswith(
            "/tables/tbl_order/records/rec_order"
        ):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "record": {
                            "record_id": "rec_order",
                            "fields": {"合同号": "26MT-001"},
                        }
                    },
                },
            )
        if request.method == "POST" and request.url.path.endswith(
            "/tables/tbl_task/records/search"
        ):
            body = json.loads(request.content)
            assert body == {
                "view_id": "vew_task",
                "filter": {
                    "conjunction": "and",
                    "conditions": [
                        {
                            "field_name": "合同号",
                            "operator": "is",
                            "value": ["26MT-001"],
                        }
                    ],
                },
            }
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "items": [
                            {
                                "record_id": "rec_task",
                                "fields": {"合同号": "26MT-001"},
                            }
                        ],
                        "has_more": False,
                    },
                },
            )
        if request.method == "GET" and request.url.path.endswith(
            "/contact/v3/users/ou_inspector"
        ):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"user": {"union_id": "on_inspector"}},
                },
            )
        raise AssertionError(
            f"Unexpected Feishu request: {request.method} {request.url}"
        )

    async def scenario() -> None:
        transport = httpx.MockTransport(handler)
        async with (
            httpx.AsyncClient(transport=transport) as http_client,
            FeishuBitableClient(http_client) as client,
        ):
            order = await client.get_record("tbl_order", "rec_order")
            tasks = [
                record
                async for record in client.search_records(
                    "tbl_task",
                    "vew_task",
                    field_name="合同号",
                    value="26MT-001",
                )
            ]
            first_union_id = await client.get_person_union_id("ou_inspector")
            second_union_id = await client.get_person_union_id("ou_inspector")

        assert order["record_id"] == "rec_order"
        assert [task["record_id"] for task in tasks] == ["rec_task"]
        assert first_union_id == second_union_id == "on_inspector"

    asyncio.run(scenario())

    assert sum("tenant_access_token" in request.url.path for request in requests) == 1
    assert sum("/contact/v3/users/" in request.url.path for request in requests) == 1


class _FakeTransaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.closed = False

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()

    async def execute(self, query: str, *args: Any) -> None:
        self.executions.append((query, args))

    async def close(self) -> None:
        self.closed = True


class _FakeFeishuClient:
    last_instance: _FakeFeishuClient | None = None

    def __init__(self) -> None:
        self.get_calls: list[tuple[str, str]] = []
        self.search_calls: list[tuple[str, str, str, str]] = []
        self.person_calls: list[str] = []
        _FakeFeishuClient.last_instance = self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_record(self, table_id: str, record_id: str) -> dict[str, Any]:
        self.get_calls.append((table_id, record_id))
        return {
            "record_id": "rec_order",
            "fields": {
                "合同号": "26MT-001",
                "产品类型": "法兰",
                "质检状态": "待分配",
                "质检员": [{"id": "ou_inspector", "name": "王质检"}],
            },
        }

    async def search_records(
        self,
        table_id: str,
        view_id: str,
        *,
        field_name: str,
        value: str,
    ) -> Any:
        self.search_calls.append((table_id, view_id, field_name, value))
        yield {
            "record_id": "rec_task",
            "fields": {
                "合同号": "26MT-001",
                "序号": 1,
                "任务ID": "task-1",
                "产品类型": "法兰",
                "规格": "304 100",
                "数量": 2,
                "质检阶段": "已到货",
                "质检状态": "待拍照",
                "质检员": [{"id": "ou_inspector", "name": "王质检"}],
            },
        }

    async def get_person_union_id(self, open_id: str) -> str:
        self.person_calls.append(open_id)
        return "on_inspector"


def test_webhook_reads_one_order_and_filtered_tasks_before_database_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_feishu(monkeypatch)
    connection = _FakeConnection()

    async def connect(_: str) -> _FakeConnection:
        return connection

    monkeypatch.setattr(bitable_sync, "FeishuBitableClient", _FakeFeishuClient)
    monkeypatch.setattr(bitable_sync.asyncpg, "connect", connect)

    result = asyncio.run(
        bitable_sync.sync_order_webhook({"record_id": "  rec_order\n"})
    )

    client = _FakeFeishuClient.last_instance
    assert client is not None
    assert client.get_calls == [("tbl_order", "rec_order")]
    assert client.search_calls == [("tbl_task", "vew_task", "合同号", "26MT-001")]
    assert client.person_calls == ["ou_inspector"]
    assert result == {"order_items": 1, "inspection_photo_tasks": 1}
    assert connection.closed is True
    assert len(connection.executions) == 3

    order_item_args = connection.executions[1][1]
    assert order_item_args[0:3] == ("26MT-001", "rec_order", "法兰")
    assert order_item_args[4:] == (
        "待分配",
        "ou_inspector",
        "on_inspector",
        "王质检",
    )

    task_args = connection.executions[2][1]
    assert task_args == (
        "rec_task",
        "26MT-001",
        "1",
        "task-1",
        "法兰",
        "304 100",
        "2",
        "已到货",
        "王质检",
        "待拍照",
        "ou_inspector",
        "on_inspector",
    )


def test_webhook_rejects_missing_record_id_without_scanning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_feishu(monkeypatch)

    with pytest.raises(bitable_sync.SyncValidationError, match="one record_id"):
        asyncio.run(bitable_sync.sync_order_webhook({}))
