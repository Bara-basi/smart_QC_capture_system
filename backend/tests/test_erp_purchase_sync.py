from scripts.sync_erp_purchases import ProductTask, PurchaseOrder, _task_write_plan


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
