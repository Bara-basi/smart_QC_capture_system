from app.services.dashboard_repository import (
    _product_previews,
    _requirements,
    _sequence_sort_key,
)


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


def test_contract_sequences_are_sorted_naturally() -> None:
    values = ["11", "2", None, "10", "1", "A10", "A2"]

    assert sorted(values, key=_sequence_sort_key) == ["1", "2", "10", "11", "A2", "A10", None]


def test_supplemental_photo_is_available_but_not_mandatory() -> None:
    assert _requirements("法兰")[-1] == "补充拍照"
