import pytest
from fastapi import HTTPException

from app.api.photos import _manifest
from app.services.dashboard_repository import (
    _completion_statuses,
    _mandatory_items,
    _requirements,
    _search_tokens,
)


def test_manifest_accepts_matching_file_indexes() -> None:
    manifest = _manifest('{"contract_no":"26MT-03T005","photos":[{"file_index":0,"task_feishu_record_id":"rec_1","inspection_item":"材质光谱","client_captured_at":"2026-08-16T10:00:00.000Z"}]}', 1)
    assert manifest["contract_no"] == "26MT-03T005"


def test_manifest_preserves_trimmed_optional_photo_note() -> None:
    manifest = _manifest('{"contract_no":"26MT-03T005","photos":[{"file_index":0,"task_feishu_record_id":"rec_1","inspection_item":"补充拍照","inspection_note":"  客户要求补拍铭牌  ","client_captured_at":"2026-08-16T10:00:00.000Z"}]}', 1)

    assert manifest["photos"][0]["inspection_note"] == "客户要求补拍铭牌"


def test_manifest_rejects_overlong_photo_note() -> None:
    payload = '{"contract_no":"26MT-03T005","photos":[{"file_index":0,"task_feishu_record_id":"rec_1","inspection_item":"补充拍照","inspection_note":"' + ('字' * 501) + '","client_captured_at":"2026-08-16T10:00:00.000Z"}]}'

    with pytest.raises(HTTPException) as error:
        _manifest(payload, 1)
    assert error.value.status_code == 400


def test_manifest_rejects_unmatched_files() -> None:
    with pytest.raises(HTTPException) as error:
        _manifest('{"contract_no":"26MT-03T005","photos":[]}', 1)
    assert error.value.status_code == 400


def test_search_tokens_split_chinese_and_whitespace_terms() -> None:
    assert _search_tokens("26MT-03T005，法兰  材质光谱") == ["26MT-03T005", "法兰", "材质光谱"]


def test_search_tokens_are_bounded() -> None:
    assert len(_search_tokens("一 二 三 四 五 六 七 八 九")) == 8


def test_completion_statuses_submit_task_before_whole_order() -> None:
    tasks = [
        {"feishu_record_id": "task-1", "contract_no": "26MT-001", "product_type": "法兰"},
        {"feishu_record_id": "task-2", "contract_no": "26MT-001", "product_type": "法兰"},
    ]
    mandatory = set(_requirements("法兰")) & _mandatory_items()
    completed_tasks, completed_contracts = _completion_statuses(
        tasks,
        {"task-1": mandatory},
    )
    assert completed_tasks == ["task-1"]
    assert completed_contracts == []


def test_completion_statuses_submit_order_only_when_all_tasks_complete() -> None:
    tasks = [
        {"feishu_record_id": "task-1", "contract_no": "26MT-001", "product_type": "法兰"},
        {"feishu_record_id": "task-2", "contract_no": "26MT-001", "product_type": "法兰"},
    ]
    mandatory = set(_requirements("法兰")) & _mandatory_items()
    completed_tasks, completed_contracts = _completion_statuses(
        tasks,
        {"task-1": mandatory, "task-2": mandatory},
    )
    assert completed_tasks == ["task-1", "task-2"]
    assert completed_contracts == ["26MT-001"]
