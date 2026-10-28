"""Isolated checks for pure backend behavior and selected robustness boundaries.

Run inside the existing API image from a read-only source mount, for example:

    docker run --rm --network none \
      -v /opt/QC_capture_system/backend:/project/backend:ro \
      -v /opt/QC_capture_system/tmp:/tests:ro \
      -e PYTHONPATH=/project/backend \
      qc_capture_system-api python /tests/qa_container_checks.py

This script never opens a database or external network connection.
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from app.api.photos import _is_supported_image, _manifest
from app.api import feishu as feishu_api
from app.api.user import safe_return_path
from app.services import dashboard_repository
from app.services.dashboard_repository import (
    _completion_statuses,
    _mandatory_items,
    _product_previews,
    _requirements,
    _search_tokens,
    _sequence_sort_key,
)
from app.services.feishu_jsapi import _validate_page_url
from app.services.feishu_auth import FeishuAuthError
from app.services.watermark import (
    factory_initials,
    format_contract,
    format_specification,
    render_watermark,
    watermark_lines,
)

RESULTS: list[tuple[str, bool, str]] = []

configured_rules_path = os.environ.get("QC_REQUIRE_MAPPING_PATH")
if configured_rules_path:
    dashboard_repository.RULES_PATH = Path(configured_rules_path)


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, condition, detail))


def raises_http(payload: str, file_count: int, status: int = 400) -> bool:
    try:
        _manifest(payload, file_count)
    except HTTPException as exc:
        return exc.status_code == status
    return False


def valid_photo_payload(**overrides: object) -> dict[str, object]:
    photo: dict[str, object] = {
        "file_index": 0,
        "task_feishu_record_id": "rec_task",
        "inspection_item": "材质光谱",
        "client_captured_at": "2026-10-22T10:00:00Z",
    }
    photo.update(overrides)
    return {
        "contract_no": "26MT-03T005",
        "mode": "save",
        "photos": [photo],
    }


def test_manifest_boundaries() -> None:
    malformed = [
        ("空字符串", "", 0),
        ("非 JSON", "{", 0),
        ("JSON 数组", "[]", 0),
        ("缺少合同号", '{"photos":[]}', 0),
        ("合同号类型错误", '{"contract_no":123,"photos":[]}', 0),
    ]
    for name, payload, count in malformed:
        check(f"清单拒绝{name}", raises_http(payload, count), f"payload={payload[:80]!r}")

    for mode in ("invalid", None, [], {}):
        payload = json.dumps({"contract_no": "C1", "mode": mode, "photos": []})
        check(f"清单拒绝非法 mode={mode!r}", raises_http(payload, 0))

    check(
        "清单拒绝重复删除 ID",
        raises_http(
            json.dumps(
                {
                    "contract_no": "C1",
                    "delete_photo_ids": ["p1", "p1"],
                    "photos": [],
                }
            ),
            0,
        ),
    )
    check(
        "清单拒绝越界 file_index",
        raises_http(json.dumps(valid_photo_payload(file_index=1)), 1),
    )
    check(
        "清单拒绝未使用的上传文件",
        raises_http(json.dumps({"contract_no": "C1", "photos": []}), 1),
    )
    check(
        "清单对 task_ids 去重",
        _manifest(
            json.dumps(
                {
                    "contract_no": "C1",
                    "mode": "complete",
                    "task_ids": [" t1 ", "t1"],
                    "photos": [],
                }
            ),
            0,
        )["task_ids"]
        == ["t1"],
    )

    long_item = "字" * 101
    accepted_long_item = _manifest(
        json.dumps(valid_photo_payload(inspection_item=long_item)), 1
    )
    check(
        "边界观察：inspection_item 超过数据库 VARCHAR(100) 仍在清单层被接受",
        accepted_long_item["photos"][0]["inspection_item"] == long_item,
    )
    accepted_bad_time = _manifest(
        json.dumps(valid_photo_payload(client_captured_at="not-a-date")), 1
    )
    check(
        "边界观察：client_captured_at 非日期仍在清单层被接受",
        accepted_bad_time["photos"][0]["client_captured_at"] == "not-a-date",
    )
    huge_whitespace_note = _manifest(
        json.dumps(valid_photo_payload(inspection_note=" " * 5000)), 1
    )
    check(
        "边界观察：超长纯空白备注在清单层被接受并归空",
        huge_whitespace_note["photos"][0]["inspection_note"] == "",
    )
    empty_contract = _manifest(
        json.dumps(
            {
                "contract_no": "",
                "mode": "complete",
                "task_ids": ["t1"],
                "photos": [],
            }
        ),
        0,
    )
    check(
        "边界观察：空合同号在清单层被接受",
        empty_contract["contract_no"] == "",
    )


def test_image_boundaries() -> None:
    jpeg = io.BytesIO()
    Image.new("RGB", (64, 64), "gray").save(jpeg, format="JPEG")
    valid = jpeg.getvalue()
    check("JPEG 魔数识别", _is_supported_image(valid))
    check(
        "边界观察：仅魔数正确但内容损坏的图像通过前置类型检查",
        _is_supported_image(b"\xff\xd8\xffnot-a-real-jpeg"),
    )

    oriented = Image.new("RGB", (400, 200), "gray")
    exif = Image.Exif()
    exif[274] = 6
    buffer = io.BytesIO()
    oriented.save(buffer, format="JPEG", exif=exif)
    processed, _ = render_watermark(
        buffer.getvalue(),
        watermark_lines(
            "26MT-03T005",
            "1",
            "304 DN50",
            __import__("datetime").datetime(2026, 10, 22, 10, 0),
        ),
    )
    with Image.open(io.BytesIO(processed)) as output:
        check(
            "边界观察：水印处理未应用 EXIF Orientation（竖向 6）",
            output.size == (400, 200),
            f"处理前后尺寸均为 {output.size}；正确方向应交换为 (200, 400)",
        )


def test_business_rules() -> None:
    aliases = {
        "26MT-03T005-GYL": ("GYL-26MT03T005", "GYL"),
        "26MT-03T005": ("26MT03T005", None),
    }
    for contract, (formatted, factory) in aliases.items():
        check(
            f"合同水印格式 {contract}",
            format_contract(contract, None) == formatted,
        )
        check(
            f"工厂代码 {contract}",
            factory_initials(contract) == factory,
        )
    check("规格水印仅取前两项", format_specification("ASTM A312 TP304") == "ASTM-A312")
    check("未知产品回退到其它规则", _requirements("未知类别") == _requirements("其它"))
    check(
        "边界观察：前端产品“板材/棒材”与规则键“板棒”不一致，回退到其它规则",
        _requirements("板材") == _requirements("其它"),
    )
    check(
        "边界观察：前端产品“管子”没有专用规则，回退到其它规则",
        _requirements("管子") == _requirements("其它"),
    )
    check("补充拍照始终存在且非必拍", "补充拍照" not in _mandatory_items())

    tasks = [
        {
            "feishu_record_id": "t1",
            "contract_no": "C1",
            "product_type": "法兰",
            "inspection_status": "待处理",
        },
        {
            "feishu_record_id": "t2",
            "contract_no": "C1",
            "product_type": "法兰",
            "inspection_status": "待处理",
        },
    ]
    mandatory = set(_requirements("法兰")) & _mandatory_items()
    completed_tasks, completed_contracts = _completion_statuses(
        tasks,
        {"t1": mandatory, "t2": mandatory},
        {"t1"},
    )
    check(
        "仅提交一个任务时不完成整张订单",
        completed_tasks == ["t1"] and completed_contracts == [],
    )
    completed_tasks, completed_contracts = _completion_statuses(
        tasks,
        {"t1": mandatory, "t2": mandatory},
        {"t1", "t2"},
    )
    check(
        "全部任务完成时完成订单",
        completed_tasks == ["t1", "t2"] and completed_contracts == ["C1"],
    )

    preview = _product_previews(
        [
            {"specification": "TP304 9.525", "product_type": "焊管"},
            {"specification": " TP304   9.525 ", "product_type": "管子"},
            {"specification": "TP316 12.7", "product_type": "焊管"},
            {"specification": "TP304 19.05", "product_type": "焊管"},
            {"specification": "TP304 25.4", "product_type": "焊管"},
        ]
    )
    check(
        "合同产品预览去重且最多三组",
        preview
        == [
            "TP304 9.525 · 焊管",
            "TP316 12.7 · 焊管",
            "TP304 19.05 · 焊管",
            "等",
        ],
    )
    check(
        "合同序号自然排序",
        sorted(["11", "2", None, "10", "1", "A10", "A2"], key=_sequence_sort_key)
        == ["1", "2", "10", "11", "A2", "A10", None],
    )
    check(
        "搜索词按中文标点拆分且不超过 8 项",
        _search_tokens("26MT-03T005，法兰  材质光谱 一 二 三 四 五 六 七")
        == ["26MT-03T005", "法兰", "材质光谱", "一", "二", "三", "四", "五"],
    )


def test_redirects_and_origins() -> None:
    safe_paths = {
        "/": "/",
        "/gallery": "/gallery",
        "/gallery?scope=shared": "/gallery?scope=shared",
        "https://attacker.example/": "/",
        "//attacker.example/": "/",
        "javascript:alert(1)": "/",
        "gallery": "/",
    }
    for value, expected in safe_paths.items():
        check(f"OAuth 返回路径 {value!r}", safe_return_path(value) == expected)

    from app.core.config import settings

    original = settings.web_origin
    try:
        settings.web_origin = "https://qc.example.com"
        _validate_page_url("https://qc.example.com/capture")
        rejected = False
        try:
            _validate_page_url("https://attacker.example/capture")
        except FeishuAuthError:
            rejected = True
        check("JSAPI 签名拒绝非配置来源", rejected)
    finally:
        settings.web_origin = original


def test_photo_download_batch() -> None:
    photo = {
        "id": "12345678-abcd-efgh-ijkl-1234567890ab",
        "oss_object_key": "orders/C1/photo.jpg",
        "contract_no": "26MT/001",
        "product_type": "法兰",
        "specification": "304 DN50",
        "inspection_item": "材质光谱",
        "captured_at": datetime(2026, 10, 22, 10, 30),
        "content_type": "image/jpeg",
        "file_size_bytes": 4,
    }
    name = feishu_api._archive_photo_name(photo)
    check(
        "批量图片名称消除路径字符并保留唯一后缀",
        "/" not in name and "\\" not in name and name.endswith("_12345678.jpg"),
        name,
    )

    original_reader = feishu_api.read_image
    try:
        feishu_api.read_image = lambda bucket, key: b"jpeg"
        archive = feishu_api._build_photo_archive([photo, {**photo, "id": "abcdefgh-other"}])
        try:
            with zipfile.ZipFile(archive) as bundle:
                check(
                    "批量 ZIP 包含全部图片且名称唯一",
                    len(bundle.namelist()) == 2
                    and len(set(bundle.namelist())) == 2
                    and all(image.startswith(b"jpeg") for image in map(bundle.read, bundle.namelist())),
                )
        finally:
            archive.close()
    finally:
        feishu_api.read_image = original_reader

    check(
        "批量下载请求接受 shared 范围",
        feishu_api.DownloadBatchRequest(photo_ids=["p1"], scope="shared").scope == "shared",
    )
    rejected_scope = False
    try:
        feishu_api.DownloadBatchRequest(photo_ids=["p1"], scope="private")
    except ValidationError:
        rejected_scope = True
    check("批量下载拒绝非法范围", rejected_scope)
    rejected_size = False
    try:
        feishu_api.DownloadBatchRequest(photo_ids=[str(index) for index in range(201)], scope="mine")
    except ValidationError:
        rejected_size = True
    check("批量下载最多接受 200 张", rejected_size)


def test_download_routes_without_database() -> None:
    class FakeRequest:
        session = {"user_id": "test-user"}

    photo = {
        "id": "12345678-abcd-efgh-ijkl-1234567890ab",
        "oss_object_key": "orders/C1/photo.jpg",
        "contract_no": "C1",
        "product_type": "法兰",
        "specification": "304",
        "inspection_item": "材质光谱",
        "captured_at": datetime(2026, 10, 22, 10, 30),
        "content_type": "image/jpeg",
        "file_size_bytes": 4,
    }
    original_reader = feishu_api.read_image
    original_object = dashboard_repository.photo_object_for_user
    original_batch = dashboard_repository.photo_downloads_for_user
    original_signed_url = feishu_api.signed_download_url

    async def fake_object(*args, **kwargs):
        return photo["oss_object_key"]

    async def fake_batch(*args, **kwargs):
        return [photo]

    try:
        feishu_api.read_image = lambda bucket, key: b"jpeg"
        feishu_api.signed_download_url = lambda *args, **kwargs: "https://oss.example/signed-photo"
        dashboard_repository.photo_object_for_user = fake_object
        dashboard_repository.photo_downloads_for_user = fake_batch

        single = asyncio.run(feishu_api.download_photo(photo["id"], FakeRequest(), "shared"))
        check(
            "单张下载返回图片附件而不是新标签页重定向",
            single.status_code == 200
            and single.media_type == "image/jpeg"
            and single.headers["content-disposition"].startswith("attachment;"),
            f"status={single.status_code}, media_type={single.media_type}",
        )
        native_url = asyncio.run(
            feishu_api.photo_download_url(photo["id"], FakeRequest(), "shared")
        )
        check(
            "飞书原生下载接口返回短期签名图片地址",
            native_url["url"] == "https://oss.example/signed-photo"
            and native_url["filename"].endswith(".jpg"),
        )

        async def consume_batch():
            response = await feishu_api.download_photo_batch(
                feishu_api.DownloadBatchRequest(photo_ids=[photo["id"]], scope="shared"),
                FakeRequest(),
            )
            body = b"".join([chunk async for chunk in response.body_iterator])
            return response, body

        batch_response, archive_bytes = asyncio.run(consume_batch())
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as bundle:
            names = bundle.namelist()
        check(
            "批量下载路由返回可解析 ZIP",
            batch_response.status_code == 200
            and batch_response.media_type == "application/zip"
            and len(names) == 1,
            f"status={batch_response.status_code}, names={names}",
        )
    finally:
        feishu_api.read_image = original_reader
        feishu_api.signed_download_url = original_signed_url
        dashboard_repository.photo_object_for_user = original_object
        dashboard_repository.photo_downloads_for_user = original_batch


def main() -> int:
    test_manifest_boundaries()
    test_image_boundaries()
    test_business_rules()
    test_redirects_and_origins()
    test_photo_download_batch()
    test_download_routes_without_database()

    for name, passed, detail in RESULTS:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    failed = sum(not passed for _, passed, _ in RESULTS)
    print(f"\nSUMMARY total={len(RESULTS)} passed={len(RESULTS) - failed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
