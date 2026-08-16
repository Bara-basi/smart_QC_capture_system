import pytest
from fastapi import HTTPException

from app.api.photos import _manifest
from app.services.dashboard_repository import _search_tokens


def test_manifest_accepts_matching_file_indexes() -> None:
    manifest = _manifest('{"contract_no":"26MT-03T005","photos":[{"file_index":0,"task_feishu_record_id":"rec_1","inspection_item":"材质光谱","client_captured_at":"2026-08-16T10:00:00.000Z"}]}', 1)
    assert manifest["contract_no"] == "26MT-03T005"


def test_manifest_rejects_unmatched_files() -> None:
    with pytest.raises(HTTPException) as error:
        _manifest('{"contract_no":"26MT-03T005","photos":[]}', 1)
    assert error.value.status_code == 400


def test_search_tokens_split_chinese_and_whitespace_terms() -> None:
    assert _search_tokens("26MT-03T005，法兰  材质光谱") == ["26MT-03T005", "法兰", "材质光谱"]


def test_search_tokens_are_bounded() -> None:
    assert len(_search_tokens("一 二 三 四 五 六 七 八 九")) == 8
