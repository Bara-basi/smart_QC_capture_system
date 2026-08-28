from app.services.dashboard_repository import _product_previews


def test_product_previews_deduplicates_specifications_before_limiting() -> None:
    tasks = [
        {"specification": "TP304 9.525", "product_type": "焊管"},
        {"specification": " TP304   9.525 ", "product_type": "管子"},
        {"specification": "TP316 12.7", "product_type": "焊管"},
        {"specification": "TP304 19.05", "product_type": "焊管"},
        {"specification": "TP304 25.4", "product_type": "焊管"},
    ]

    assert _product_previews(tasks) == [
        "TP304 9.525 · 焊管",
        "TP316 12.7 · 焊管",
        "TP304 19.05 · 焊管",
        "等",
    ]


def test_product_previews_does_not_add_more_marker_after_deduplication() -> None:
    tasks = [
        {"specification": "TP304", "product_type": "焊管"},
        {"specification": "TP304", "product_type": "焊管"},
        {"specification": "TP316", "product_type": "焊管"},
    ]

    assert _product_previews(tasks) == ["TP304 · 焊管", "TP316 · 焊管"]
