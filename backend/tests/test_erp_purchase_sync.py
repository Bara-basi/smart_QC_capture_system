import json
from pathlib import Path, PurePosixPath
from typing import Self

import httpx
import pytest

from scripts import sync_erp_purchases as sync_module
from scripts.sync_erp_purchases import (
    FeishuPurchaseSyncClient,
    ProductionDaily,
    ProductTask,
    PurchaseOrder,
    PurchaseSummary,
    _completed_order_cleanup_plan,
    _contract_inspectors_from_orders,
    _default_factory_mapping_candidates,
    _factory_backfill_plan,
    _inspector_person_update_plan,
    _load_assignment_queue,
    _order_assignment_status_update_plan,
    _order_create_records,
    _order_metadata_update_plan,
    _task_inspector_update_plan,
    _task_write_plan,
    dispatch_assignment_webhooks,
    dispatch_retirement_webhooks,
    factory_name,
    flush_assignment_queue,
    parse_production_daily,
)


def test_linux_container_prefers_app_data_for_factory_mapping() -> None:
    candidates = _default_factory_mapping_candidates(
        PurePosixPath("/app/scripts/sync_erp_purchases.py")
    )

    assert candidates[0] == PurePosixPath("/app/data/factroy_mapping.json")
    assert candidates[1] == PurePosixPath("/data/factroy_mapping.json")


def _order(stage: str = "待检") -> PurchaseOrder:
    return PurchaseOrder(
        purchase_id="123",
        purchase_code="26MT-001",
        purchase_date="2026-08-17",
        order_status=stage,
        product_types="法兰",
        tasks=[
            ProductTask(
                sequence="1",
                product_type="法兰",
                material="304",
                outer_diameter_mm="100",
                wall_thickness_mm="",
                length="",
                quantity="2",
            )
        ],
    )


def test_existing_task_uses_record_id_to_update_stage_instead_of_skipping() -> None:
    existing = [
        {
            "record_id": "rec_feishu_1",
            "fields": {
                "合同号": "26MT-001",
                "序号": 1,
                "质检阶段": "采购中",
            },
        }
    ]

    creates, updates = _task_write_plan(
        existing,
        [],
        {"26MT-001": "已到货"},
    )

    assert creates == []
    assert updates == [
        {
            "record_id": "rec_feishu_1",
            "fields": {"质检阶段": "已到货"},
        }
    ]


def test_unchanged_stage_is_not_written_again() -> None:
    existing = [
        {
            "record_id": "rec_feishu_1",
            "fields": {
                "合同号": "26MT-001",
                "序号": 1,
                "质检阶段": "已到货",
            },
        }
    ]

    creates, updates = _task_write_plan(
        existing,
        [_order("已到货")],
        {"26MT-001": "已到货"},
    )

    assert creates == []
    assert updates == []


def test_non_numeric_erp_sequence_is_preserved() -> None:
    order = _order()
    task = order.tasks[0]
    alphanumeric_order = PurchaseOrder(
        **{**order.__dict__, "tasks": [ProductTask(**{**task.__dict__, "sequence": "A1"})]}
    )

    creates, _ = _task_write_plan([], [alphanumeric_order], {})

    assert creates[0]["fields"]["序号"] == "A1"


@pytest.mark.parametrize(
    ("contract_no", "expected"),
    [
        ("26MT-10B396", None),
        ("26MT-06N398-ABCD", None),
        ("26MT-06M347-ADD1", None),
        ("26MT-06M362Y-2-HD", "鸿迪"),
        ("26MT-06M362Y-1 沪新", "沪新"),
        ("26MT-06H056ADD1-HD", "鸿迪"),
        ("26MT-06H344溪流供应链-秦皇岛", "秦皇岛"),
        ("26MT-05J298-溪流-诚吉", "诚吉"),
        ("26MT-03P238溪流GYL-兴耀城", "兴耀城"),
        ("26MT-08C020 麦金3吨", "麦金"),
        ("26MT-06C405ADD1-中凯", "中凯"),
        ("SP-07E004-鸿迪", "鸿迪"),
        ("26MT-10E285-XL", None),
    ],
)
def test_factory_name_is_conservative(contract_no: str, expected: str | None) -> None:
    assert factory_name(contract_no) == expected


def test_factory_backfill_only_fills_empty_cells() -> None:
    records = [
        {"record_id": "rec-1", "fields": {"合同号": "26MT-03R411-HD", "工厂": ""}},
        {"record_id": "rec-2", "fields": {"合同号": "26MT-03R411-HD", "工厂": "人工修正"}},
        {"record_id": "rec-3", "fields": {"合同号": "26MT-10E285-XL"}},
    ]

    assert _factory_backfill_plan(records) == [{"record_id": "rec-1", "fields": {"工厂": "鸿迪"}}]


def test_new_order_uses_erp_supplier_instead_of_contract_mapping() -> None:
    mapped = PurchaseOrder(
        **{
            **_order().__dict__,
            "purchase_code": "26MT-03R411-HD",
            "supplier": "ERP供应商",
        }
    )
    unknown = PurchaseOrder(
        **{**_order().__dict__, "purchase_code": "26MT-10E285-XL", "supplier": ""}
    )

    records = _order_create_records([mapped, unknown], "采购时间")

    assert records[0]["fields"]["工厂"] == "ERP供应商"
    assert "工厂" not in records[1]["fields"]


def test_existing_order_metadata_is_updated_from_erp() -> None:
    existing = [
        {
            "record_id": "rec-1",
            "fields": {
                "合同号": "26MT-03R411-HD",
                "工厂": "合同号推导值",
                "睿贝质检员": "",
            },
        }
    ]
    summaries = [
        PurchaseSummary(
            purchase_id="123",
            purchase_code="26MT-03R411-HD",
            purchase_date="2026-09-01",
            order_status="采购已下单",
            supplier="浙江鸿迪管业有限公司",
            inspector="梅正江",
            production_schedule="2026-09-07/订料中",
            factory_delivery_date="2026-09-20",
        )
    ]

    updates = _order_metadata_update_plan(
        existing,
        summaries,
        {
            "26MT-03R411-HD": ProductionDaily(
                content="订料中", created_at="2026-09-07"
            )
        },
        {"26MT-03R411-HD": "已完成"},
    )

    assert updates == [
        {
            "record_id": "rec-1",
            "fields": {
                "工厂": "浙江鸿迪管业有限公司",
                "睿贝质检员": "梅正江",
                "生产内容": "订料中",
                "生产日报创建时间": 1788710400000,
                "工厂交期": 1789833600000,
                "订单状态": "已完成",
            },
        }
    ]


def test_erp_inspector_updates_text_and_person_together() -> None:
    existing = [
        {
            "record_id": "rec-1",
            "fields": {
                "合同号": "26MT-03R411-HD",
                "睿贝质检员": "旧姓名",
                "质检员": [{"id": "ou_old", "name": "旧姓名"}],
            },
        }
    ]
    summary = PurchaseSummary(
        purchase_id="123",
        purchase_code="26MT-03R411-HD",
        purchase_date="2026-09-01",
        order_status="采购已下单",
        supplier="",
        inspector="梅正江",
        production_schedule="",
    )

    updates = _order_metadata_update_plan(
        existing,
        [summary],
        {},
        inspector_open_ids={"梅正江": "ou_mei"},
    )

    assert updates == [
        {
            "record_id": "rec-1",
            "fields": {
                "睿贝质检员": "梅正江",
                "质检员": [{"id": "ou_mei"}],
                "质检状态": "已分配",
            },
        }
    ]


def test_matching_person_response_metadata_does_not_cause_repeat_update() -> None:
    existing = [
        {
            "record_id": "rec-1",
            "fields": {
                "合同号": "26MT-001",
                "睿贝质检员": "高铖",
                "质检状态": "已分配",
                "质检员": [
                    {
                        "id": "ou_gao",
                        "name": "高铖",
                        "avatar_url": "https://example.invalid/avatar.png",
                    }
                ],
            },
        }
    ]
    summary = PurchaseSummary(
        purchase_id="123",
        purchase_code="26MT-001",
        purchase_date="2026-09-01",
        order_status="采购已下单",
        supplier="",
        inspector="高铖",
        production_schedule="",
    )

    assert (
        _order_metadata_update_plan(
            existing,
            [summary],
            {},
            inspector_open_ids={"高铖": "ou_gao"},
        )
        == []
    )
def test_existing_erp_inspector_backfills_person_field() -> None:
    existing = [
        {
            "record_id": "rec-1",
            "fields": {"睿贝质检员": "高铖", "质检员": []},
        },
        {
            "record_id": "rec-2",
            "fields": {
                "睿贝质检员": "高铖",
                "质检员": [{"id": "ou_gao", "name": "高铖"}],
            },
        },
        {
            "record_id": "rec-3",
            "fields": {"睿贝质检员": "无法匹配"},
        },
    ]

    assert _inspector_person_update_plan(existing, {"高铖": "ou_gao"}) == [
        {
            "record_id": "rec-1",
            "fields": {
                "质检员": [{"id": "ou_gao"}],
                "质检状态": "已分配",
            },
        },
        {
            "record_id": "rec-2",
            "fields": {"质检状态": "已分配"},
        }
    ]


def test_new_order_writes_person_open_id_when_name_is_resolved() -> None:
    order = PurchaseOrder(**{**_order().__dict__, "inspector": "高铖"})

    records = _order_create_records(
        [order], "采购时间", inspector_open_ids={"高铖": "ou_gao"}
    )

    assert records[0]["fields"]["睿贝质检员"] == "高铖"
    assert records[0]["fields"]["质检员"] == [{"id": "ou_gao"}]
    assert records[0]["fields"]["质检状态"] == "已分配"


def test_order_inspector_is_mirrored_to_every_matching_task() -> None:
    existing = [
        {
            "record_id": "task-1",
            "fields": {"合同号": "26MT-001", "质检员": []},
        },
        {
            "record_id": "task-2",
            "fields": {
                "合同号": "26MT-001",
                "质检员": [{"id": "ou_old", "name": "旧质检员"}],
            },
        },
        {
            "record_id": "task-other",
            "fields": {"合同号": "26MT-002", "质检员": []},
        },
    ]

    assert _task_inspector_update_plan(existing, {"26MT-001": "ou_gao"}) == [
        {
            "record_id": "task-1",
            "fields": {"质检员": [{"id": "ou_gao"}]},
        },
        {
            "record_id": "task-2",
            "fields": {"质检员": [{"id": "ou_gao"}]},
        },
    ]


def test_new_task_inherits_order_inspector() -> None:
    order = PurchaseOrder(**{**_order().__dict__, "inspector": "高铖"})

    creates, updates = _task_write_plan(
        [], [order], {}, inspector_open_ids={"高铖": "ou_gao"}
    )

    assert updates == []
    assert creates[0]["fields"]["质检员"] == [{"id": "ou_gao"}]


def test_assignment_replay_uses_actual_order_person_and_skips_test_orders() -> None:
    orders = [
        {
            "record_id": "order-1",
            "fields": {
                "合同号": "26MT-001",
                "订单状态": "执行中",
                "质检状态": "待分配",
                "质检员": [{"id": "ou_manual", "name": "手工改派"}],
            },
        },
        {
            "record_id": "order-test",
            "fields": {
                "合同号": "TEST-001",
                "订单状态": "测试订单",
                "质检员": [{"id": "ou_test", "name": "测试人员"}],
            },
        },
    ]

    contract_inspectors, record_ids = _contract_inspectors_from_orders(
        orders, exclude_test_orders=True
    )

    assert contract_inspectors == {"26MT-001": "ou_manual"}
    assert record_ids == {"order-1"}
    assert _order_assignment_status_update_plan(
        orders, exclude_test_orders=True
    ) == [
        {
            "record_id": "order-1",
            "fields": {"质检状态": "已分配"},
        }
    ]


def test_assignment_webhook_uses_existing_server_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 12

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, str],
        ) -> httpx.Response:
            request = httpx.Request("POST", url, headers=headers, json=json)
            requests.append(request)
            status = 200 if json["record_id"] == "rec-ok" else 502
            return httpx.Response(status, request=request, json={"detail": "result"})

    monkeypatch.setattr(sync_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        sync_module.settings,
        "feishu_sync_webhook_url",
        "https://qc.example.com/api/v1/integrations/feishu/order-sync",
    )
    monkeypatch.setattr(
        sync_module.settings, "feishu_sync_webhook_secret", "test-secret"
    )

    succeeded, failed = dispatch_assignment_webhooks(
        {"rec-ok", "rec-fail"}, timeout=12
    )

    assert succeeded == {"rec-ok"}
    assert set(failed) == {"rec-fail"}
    assert len(requests) == 2
    assert all(
        request.headers["x-qc-sync-secret"] == "test-secret"
        for request in requests
    )
    assert {
        json.loads(request.content)["record_id"] for request in requests
    } == {"rec-ok", "rec-fail"}


def test_retirement_webhook_sends_record_and_contract_before_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    class FakeClient:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 12

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(
            self,
            url: str,
            *,
            headers: dict[str, str],
            json: dict[str, str],
        ) -> httpx.Response:
            request = httpx.Request("POST", url, headers=headers, json=json)
            requests.append(request)
            return httpx.Response(200, request=request, json={"order_items": 1})

    monkeypatch.setattr(sync_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(
        sync_module.settings,
        "feishu_sync_webhook_url",
        "http://127.0.0.1:8000/api/v1/integrations/feishu/order-sync",
    )
    monkeypatch.setattr(sync_module.settings, "feishu_retire_webhook_url", "")
    monkeypatch.setattr(
        sync_module.settings, "feishu_sync_webhook_secret", "test-secret"
    )

    succeeded, failed = dispatch_retirement_webhooks(
        [{"record_id": "rec-done", "contract_no": "26MT-001"}], timeout=12
    )

    assert succeeded == {"rec-done"}
    assert failed == {}
    assert len(requests) == 1
    assert str(requests[0].url).endswith("/order-retire")
    assert requests[0].headers["x-qc-sync-secret"] == "test-secret"
    assert json.loads(requests[0].content) == {
        "record_id": "rec-done",
        "contract_no": "26MT-001",
    }


def test_assignment_queue_keeps_only_failed_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    queue_path = tmp_path / "assignment-queue.json"
    queue_path.write_text('["rec-ok", "rec-retry"]', encoding="utf-8")

    def dispatch(
        record_ids: set[str], *, timeout: float
    ) -> tuple[set[str], dict[str, str]]:
        assert record_ids == {"rec-ok", "rec-retry"}
        assert timeout == 8
        return {"rec-ok"}, {"rec-retry": "temporary failure"}

    monkeypatch.setattr(sync_module, "dispatch_assignment_webhooks", dispatch)

    assert flush_assignment_queue(queue_path, timeout=8) == (1, 1)
    assert _load_assignment_queue(queue_path) == {"rec-retry"}


def test_legacy_completed_orders_remain_candidates_for_deletion() -> None:
    client = object.__new__(FeishuPurchaseSyncClient)
    records = [
        {"record_id": "active", "fields": {"订单状态": "执行中"}},
        {"record_id": "legacy", "fields": {}},
        {"record_id": "done", "fields": {"订单状态": "已完成"}},
        {"record_id": "test", "fields": {"订单状态": "测试订单"}},
    ]

    assert [record["record_id"] for record in client.tracked_orders(records)] == [
        "active",
        "legacy",
        "done",
    ]


def test_completed_order_cleanup_includes_order_and_matching_task_rows() -> None:
    orders = [
        {"record_id": "order-1", "fields": {"合同号": "26MT-001"}},
        {"record_id": "order-2", "fields": {"合同号": "26MT-002"}},
    ]
    tasks = [
        {"record_id": "task-1", "fields": {"合同号": "26MT-001"}},
        {"record_id": "task-2", "fields": {"合同号": "26MT-001"}},
        {"record_id": "task-3", "fields": {"合同号": "26MT-002"}},
    ]

    assert _completed_order_cleanup_plan(
        orders, tasks, {"26MT-001"}
    ) == [
        {
            "contract_no": "26MT-001",
            "record_id": "order-1",
            "task_record_ids": ["task-1", "task-2"],
        }
    ]


def test_production_daily_uses_latest_date_and_record_id() -> None:
    def row(record_id: str, content: str, created_at: str) -> list[dict[str, object]]:
        return [
            {"columnName": "chk", "columnValues": [record_id]},
            {"columnName": "content", "columnValues": [content]},
            {"columnName": "on_create", "columnValues": [created_at]},
        ]

    rows = [
        row("4200", "旧日报", "2026-09-17"),
        row("4307", "当天较早日报", "2026-09-18"),
        row("4310", "当天最新日报", "2026-09-18"),
    ]
    response = "{total:3,root:" + json.dumps(rows, ensure_ascii=False) + "}"

    assert parse_production_daily("26MT-TEST", response) == ProductionDaily(
        content="当天最新日报",
        created_at="2026-09-18",
        record_id="4310",
    )
