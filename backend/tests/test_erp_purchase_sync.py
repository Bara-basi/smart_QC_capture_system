from pathlib import PurePosixPath

import pytest
from scripts.sync_erp_purchases import (
    FeishuPurchaseSyncClient,
    ProductTask,
    ProductionDaily,
    PurchaseOrder,
    PurchaseSummary,
    _default_factory_mapping_candidates,
    _factory_backfill_plan,
    _order_create_records,
    _order_metadata_update_plan,
    _task_write_plan,
    factory_name,
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
                "订单状态": "已完成",
            },
        }
    ]


def test_completed_orders_are_excluded_from_tracking() -> None:
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
    ]
