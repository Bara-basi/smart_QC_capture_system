from pathlib import PurePosixPath

import pytest
from scripts.sync_erp_purchases import (
    ProductTask,
    PurchaseOrder,
    _default_factory_mapping_candidates,
    _factory_backfill_plan,
    _order_create_records,
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


def test_new_order_includes_factory_only_when_mapping_is_confident() -> None:
    mapped = PurchaseOrder(**{**_order().__dict__, "purchase_code": "26MT-03R411-HD"})
    unknown = PurchaseOrder(**{**_order().__dict__, "purchase_code": "26MT-10E285-XL"})

    records = _order_create_records([mapped, unknown], "采购时间")

    assert records[0]["fields"]["工厂"] == "鸿迪"
    assert "工厂" not in records[1]["fields"]
