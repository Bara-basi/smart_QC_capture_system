r"""Crawl active ERP purchases and append new orders/tasks to Feishu Bitable.

The script uses the authenticated cookie file created by ``erp_login.py``.
ERP credentials are only needed when that saved session has expired.

Dry-run a small sample from the ``backend`` directory::

    .venv\Scripts\python.exe scripts\sync_erp_purchases.py --dry-run --limit 2

Run the incremental synchronization. Existing inspection tasks also receive
the latest ERP status in their ``质检阶段`` field::

    .venv\Scripts\python.exe scripts\sync_erp_purchases.py --ensure-schema

``--ensure-schema`` creates a writable Feishu date field named ``采购时间``
when it is missing.  The existing system-created ``创建时间`` field is kept
because Feishu does not allow an ERP date to be written to that field type.
"""

from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import re
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from scripts.erp_login import (
    DEFAULT_BASE_URL,
    DEFAULT_TOKEN_FILE,
    AuthenticationResult,
    ErpAuthenticationError,
    _cookies_from_client,
    _primary_token,
    authenticated_client_from_file,
    login,
    save_session,
)

ERP_LIST_PATH = "purchase_selectPur"
ERP_DETAIL_PATH = "purchaseItems_selectByPurchaseId"
ERP_LIST_REFERER = "purchase_goOutList?menuCode=80400"
ERP_PAGE_SIZE = 100
FEISHU_API = "https://open.feishu.cn/open-apis"
FEISHU_BATCH_SIZE = 500
SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_SNAPSHOT_FILE = (
    Path(__file__).resolve().parents[1] / "data" / "erp_purchase_snapshot.json"
)
FACTORY_MAPPING_FILE = (
    Path(__file__).resolve().parents[2] / "data" / "factroy_mapping.json"
)
ORDER_CODE_PATTERN = re.compile(
    r"^(?:\d{2}MT|SP)-?(?:\d{2}[A-Z]\d{3}Y?|DP\d{3})",
    re.IGNORECASE,
)

ORDER_FIELDS = {"合同号", "产品类型", "质检状态", "工厂"}
TASK_FIELDS = {"合同号", "序号", "产品类型", "规格", "数量", "质检阶段"}


class ErpProtocolError(RuntimeError):
    """Raised when an ERP response does not match the discovered interface."""


class FeishuSyncError(RuntimeError):
    """Raised when Feishu rejects a read, schema, or record operation."""


@dataclass(frozen=True)
class PurchaseSummary:
    purchase_id: str
    purchase_code: str
    purchase_date: str
    order_status: str


@dataclass(frozen=True)
class ProductTask:
    sequence: str
    product_type: str
    material: str
    outer_diameter_mm: str
    wall_thickness_mm: str
    length: str
    quantity: str

    @property
    def specification(self) -> str:
        return " ".join(
            value for value in (self.material, self.outer_diameter_mm) if value
        )


@dataclass(frozen=True)
class PurchaseOrder:
    purchase_id: str
    purchase_code: str
    purchase_date: str
    order_status: str
    product_types: str
    tasks: list[ProductTask]


def _first(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return ""
    value = values[0]
    return "" if value is None else str(value).strip()


def _column_map(row: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(row, list):
        raise ErpProtocolError("ERP row is not a list of configured columns")
    return {
        str(column.get("columnName", "")).strip(): column
        for column in row
        if isinstance(column, dict) and column.get("columnName")
    }


def _normalize_number(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value
    normalized = format(number.normalize(), "f")
    return "0" if normalized in {"-0", ""} else normalized


def _normalize_factory_token(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value).upper()


@lru_cache(maxsize=1)
def _factory_aliases() -> tuple[tuple[str, str], ...]:
    try:
        payload = json.loads(FACTORY_MAPPING_FILE.read_text(encoding="utf-8"))
        aliases = payload["aliases"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(
            f"Invalid factory mapping file: {FACTORY_MAPPING_FILE}"
        ) from exc
    if not isinstance(aliases, dict):
        raise ValueError(  # noqa: TRY004 - malformed user-maintained configuration
            f"Factory mapping aliases must be an object: {FACTORY_MAPPING_FILE}"
        )
    normalized: list[tuple[str, str]] = []
    for alias, factory in aliases.items():
        if not isinstance(alias, str) or not isinstance(factory, str):
            raise ValueError(  # noqa: TRY004 - malformed user-maintained configuration
                "Factory mapping aliases and values must be strings"
            )
        token = _normalize_factory_token(alias)
        name = factory.strip()
        if token and name:
            normalized.append((token, name))
    return tuple(normalized)


def factory_name(contract_no: str) -> str | None:
    """Return only an explicitly mapped factory found after the order-code core."""
    compact = re.sub(r"\s+", "", contract_no or "")
    match = ORDER_CODE_PATTERN.match(compact)
    if not match:
        return None
    suffix = _normalize_factory_token(compact[match.end() :])
    if not suffix:
        return None
    candidates: list[tuple[int, int, str]] = []
    for alias, factory in _factory_aliases():
        position = suffix.rfind(alias)
        if position >= 0:
            candidates.append((position, len(alias), factory))
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def parse_purchase_list(payload: dict[str, Any]) -> tuple[list[PurchaseSummary], int]:
    try:
        total = int(payload["total"])
        root = payload["root"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ErpProtocolError("ERP purchase list is missing total/root") from exc

    purchases: list[PurchaseSummary] = []
    for row in root:
        columns = _column_map(row)
        purchase_values = columns.get("purchase_code", {}).get("columnValues", [])
        purchase_code = _first(purchase_values)
        purchase_id = (
            str(purchase_values[1]).strip()
            if isinstance(purchase_values, list) and len(purchase_values) > 1
            else ""
        )
        # Each list page appends a synthetic total row with no numeric order ID.
        if not purchase_id.isdigit() or not purchase_code:
            continue
        purchases.append(
            PurchaseSummary(
                purchase_id=purchase_id,
                purchase_code=re.sub(r"\s+", " ", purchase_code).strip(),
                purchase_date=_first(
                    columns.get("purchase_date", {}).get("columnValues")
                ),
                order_status=_first(columns.get("status", {}).get("columnValues")),
            )
        )
    return purchases, total


def _parse_nonstandard_root(response_text: str) -> list[Any]:
    """Parse the strict JSON value following the ERP's unquoted ``root:`` key."""
    match = re.search(r"(?:^|[,{])\s*root\s*:\s*", response_text)
    if not match:
        raise ErpProtocolError("ERP detail response does not contain root")
    try:
        root, _ = json.JSONDecoder().raw_decode(response_text[match.end() :])
    except json.JSONDecodeError as exc:
        raise ErpProtocolError("ERP detail root is not valid JSON") from exc
    if not isinstance(root, list):
        raise ErpProtocolError("ERP detail root is not a list")
    return root


def parse_purchase_detail(
    summary: PurchaseSummary, response_text: str
) -> PurchaseOrder:
    tasks: list[ProductTask] = []
    for row_number, row in enumerate(_parse_nonstandard_root(response_text), start=1):
        columns = _column_map(row)
        sequence = _first(columns.get("disp_order", {}).get("columnValues"))
        task = ProductTask(
            sequence=_normalize_number(sequence) or str(row_number),
            product_type=_first(
                columns.get("categoryName", {}).get("columnValues")
            ),
            material=_first(columns.get("user_defined2", {}).get("columnValues")),
            outer_diameter_mm=_normalize_number(
                _first(columns.get("user_defined6", {}).get("columnValues"))
            ),
            wall_thickness_mm=_normalize_number(
                _first(columns.get("user_defined8", {}).get("columnValues"))
            ),
            length=_first(columns.get("user_defined9", {}).get("columnValues")),
            quantity=_normalize_number(
                _first(columns.get("quantity", {}).get("columnValues"))
            ),
        )
        if not task.quantity:
            raise ErpProtocolError(
                f"ERP order {summary.purchase_code} row {row_number} has no quantity"
            )
        tasks.append(task)

    if not tasks:
        raise ErpProtocolError(f"ERP order {summary.purchase_code} has no product rows")
    product_types = "/".join(
        dict.fromkeys(task.product_type for task in tasks if task.product_type)
    )
    return PurchaseOrder(
        purchase_id=summary.purchase_id,
        purchase_code=summary.purchase_code,
        purchase_date=summary.purchase_date,
        order_status=summary.order_status,
        product_types=product_types,
        tasks=tasks,
    )


class ErpPurchaseClient:
    def __init__(
        self,
        *,
        base_url: str,
        token_file: Path,
        username: str | None,
        password: str | None,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.token_file = token_file
        self.username = username
        self.password = password
        self.timeout = timeout
        self._client = self._load_or_login()
        self._retired_clients: list[httpx.Client] = []
        self._reauth_lock = threading.Lock()
        self._count_lock = threading.Lock()
        self.request_count = 0
        self._configure_client(self._client)

    def _configure_client(self, client: httpx.Client) -> httpx.Client:
        client.cookies.set(
            "purchase_business_list",
            str(ERP_PAGE_SIZE),
            domain=urlparse(self.base_url).hostname,
            path="/",
        )
        return client

    def _load_or_login(self) -> httpx.Client:
        try:
            return authenticated_client_from_file(
                self.token_file, timeout=self.timeout
            )
        except ErpAuthenticationError:
            return self._login_again()

    def _login_again(self) -> httpx.Client:
        if not self.username or not self.password:
            raise ErpAuthenticationError(
                "ERP session is unavailable/expired. Run scripts/erp_login.py or set "
                "ERP_USERNAME and ERP_PASSWORD for automatic renewal."
            )
        result = login(
            self.username,
            self.password,
            base_url=self.base_url,
            timeout=self.timeout,
        )
        save_session(result, self.token_file, base_url=self.base_url)
        return self._configure_client(
            authenticated_client_from_file(self.token_file, timeout=self.timeout)
        )

    def close(self) -> None:
        self._persist_current_session()
        for client in [self._client, *self._retired_clients]:
            client.close()

    def _persist_current_session(self) -> None:
        cookies = _cookies_from_client(self._client)
        if not cookies:
            return
        token_name, token_value = _primary_token(cookies)
        save_session(
            AuthenticationResult(
                username=self.username or "saved-session",
                token_name=token_name,
                token_value=token_value,
                cookies=cookies,
                final_url=self.base_url,
            ),
            self.token_file,
            base_url=self.base_url,
        )

    def _is_auth_failure(self, response: httpx.Response) -> bool:
        return (
            response.status_code in {401, 403}
            or b'id="frmLogin"' in response.content
            or b"top.location.href = '/'" in response.content
        )

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(2):
            # httpx.Client supports concurrent requests. Keep a reference to
            # the client used by this attempt so a re-login never closes it
            # while another detail-worker is still receiving a response.
            client = self._client
            with self._count_lock:
                self.request_count += 1
            response = client.request(
                method, urljoin(self.base_url, path), **kwargs
            )
            if not self._is_auth_failure(response):
                response.raise_for_status()
                return response
            if attempt == 1:
                break
            with self._reauth_lock:
                # A different worker may already have refreshed the session.
                if client is self._client:
                    self._retired_clients.append(client)
                    self._client = self._login_again()
        raise ErpAuthenticationError("ERP rejected the saved session after renewal")

    def purchase_summaries(self) -> list[PurchaseSummary]:
        referer = urljoin(self.base_url, ERP_LIST_REFERER)

        def fetch_page(page: int) -> tuple[list[PurchaseSummary], int]:
            response = self.request(
                "POST",
                ERP_LIST_PATH,
                data={
                    "p": str(page),
                    "condition": "uncompleted",
                    "userDefaultTableName": "biz_purchases",
                    "searchValue": "",
                },
                headers={"Referer": referer},
            )
            try:
                payload = json.loads(response.content.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ErpProtocolError("ERP purchase list returned invalid JSON") from exc
            return parse_purchase_list(payload)

        purchases, total = fetch_page(1)
        page_count = max(1, math.ceil(total / ERP_PAGE_SIZE))
        for page in range(2, page_count + 1):
            page_rows, page_total = fetch_page(page)
            if page_total != total:
                raise ErpProtocolError(
                    "ERP active-order total changed during pagination; rerun the sync"
                )
            purchases.extend(page_rows)

        unique = {purchase.purchase_code: purchase for purchase in purchases}
        if len(unique) != total:
            raise ErpProtocolError(
                f"ERP reported {total} active orders but returned "
                f"{len(unique)} unique purchase numbers"
            )
        return list(unique.values())

    def purchase_detail(self, summary: PurchaseSummary) -> PurchaseOrder:
        referer_path = (
            "purchase_toUpdate?openWindow=Y&type=view&id=" + summary.purchase_id
        )
        response = self.request(
            "POST",
            ERP_DETAIL_PATH,
            data={
                "purchaseId": summary.purchase_id,
                "operateType": "view",
                "p": "1",
                "pageSize": str(ERP_PAGE_SIZE),
            },
            headers={"Referer": urljoin(self.base_url, referer_path)},
        )
        return parse_purchase_detail(
            summary, response.content.decode("utf-8", errors="strict")
        )


def _check_feishu_response(response: httpx.Response, action: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise FeishuSyncError(
            f"Feishu could not {action}: non-JSON HTTP {response.status_code}"
        ) from exc
    if response.status_code >= 400 or body.get("code", 0) != 0:
        raise FeishuSyncError(
            f"Feishu could not {action}: "
            f"{body.get('msg') or body.get('code') or response.status_code}"
        )
    return body


def _field_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return _normalize_number(str(value))
    if isinstance(value, list):
        return "".join(_field_text(item) for item in value).strip()
    if isinstance(value, dict):
        return _field_text(
            value.get("text") or value.get("name") or value.get("value")
        )
    return str(value).strip()


class FeishuPurchaseSyncClient:
    def __init__(self, *, timeout: float) -> None:
        required = {
            "FEISHU_APP_ID": settings.feishu_app_id,
            "FEISHU_APP_SECRET": settings.feishu_app_secret,
            "FEISHU_BITABLE_APP_TOKEN": settings.feishu_bitable_app_token,
            "FEISHU_BITABLE_ORDER_TABLE_ID": settings.feishu_bitable_order_table_id,
            "FEISHU_BITABLE_TABLE_ID": settings.feishu_bitable_table_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise FeishuSyncError(
                f"Missing Feishu configuration: {', '.join(missing)}"
            )
        self.client = httpx.Client(timeout=timeout)
        token_response = self.client.post(
            f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.feishu_app_id,
                "app_secret": settings.feishu_app_secret,
            },
        )
        body = _check_feishu_response(token_response, "obtain tenant token")
        token = body.get("tenant_access_token")
        if not token:
            raise FeishuSyncError("Feishu did not return tenant_access_token")
        self.headers = {"Authorization": f"Bearer {token}"}
        self.request_count = 1

    def close(self) -> None:
        self.client.close()

    def fields(self, table_id: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
            response = self.client.get(
                f"{FEISHU_API}/bitable/v1/apps/"
                f"{settings.feishu_bitable_app_token}/tables/{table_id}/fields",
                headers=self.headers,
                params=params,
            )
            self.request_count += 1
            data = _check_feishu_response(response, "read Bitable fields").get(
                "data", {}
            )
            for field in data.get("items", []):
                result[str(field.get("field_name"))] = field
            if not data.get("has_more"):
                return result
            page_token = data.get("page_token")
            if not page_token:
                raise FeishuSyncError("Feishu field pagination has no page_token")

    def ensure_purchase_date_field(self, *, create_if_missing: bool) -> str:
        table_id = settings.feishu_bitable_order_table_id
        fields = self.fields(table_id)
        field = fields.get("采购时间")
        if field:
            if field.get("type") != 5:
                raise FeishuSyncError("Feishu 采购时间 field exists but is not DateTime")
            return "采购时间"

        if not create_if_missing:
            raise FeishuSyncError(
                "Order table needs a writable 采购时间 DateTime field. "
                "Rerun with --ensure-schema to create it."
            )
        response = self.client.post(
            f"{FEISHU_API}/bitable/v1/apps/"
            f"{settings.feishu_bitable_app_token}/tables/{table_id}/fields",
            headers=self.headers,
            json={
                "field_name": "采购时间",
                "type": 5,
                "property": {"date_formatter": "yyyy-MM-dd"},
            },
        )
        self.request_count += 1
        _check_feishu_response(response, "create 采购时间 field")
        return "采购时间"

    def validate_fields(self) -> None:
        order_names = set(self.fields(settings.feishu_bitable_order_table_id))
        task_names = set(self.fields(settings.feishu_bitable_table_id))
        missing_order = ORDER_FIELDS - order_names
        missing_task = TASK_FIELDS - task_names
        if missing_order or missing_task:
            raise FeishuSyncError(
                "Missing Bitable fields: "
                f"order={sorted(missing_order)}, task={sorted(missing_task)}"
            )

    def iter_records(
        self, table_id: str, *, view_id: str | None = None
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 500}
            if view_id:
                params["view_id"] = view_id
            if page_token:
                params["page_token"] = page_token
            response = self.client.get(
                f"{FEISHU_API}/bitable/v1/apps/"
                f"{settings.feishu_bitable_app_token}/tables/{table_id}/records",
                headers=self.headers,
                params=params,
            )
            self.request_count += 1
            data = _check_feishu_response(response, "read Bitable records").get(
                "data", {}
            )
            records.extend(data.get("items", []))
            if not data.get("has_more"):
                return records
            page_token = data.get("page_token")
            if not page_token:
                raise FeishuSyncError("Feishu record pagination has no page_token")

    def existing_contracts(self) -> set[str]:
        records = self.iter_records(
            settings.feishu_bitable_order_table_id,
            view_id=settings.feishu_bitable_order_view_id or None,
        )
        return {
            contract
            for record in records
            if (contract := _field_text((record.get("fields") or {}).get("合同号")))
        }

    def existing_orders(self) -> list[dict[str, Any]]:
        return self.iter_records(settings.feishu_bitable_order_table_id)

    def existing_tasks(self) -> list[dict[str, Any]]:
        return self.iter_records(settings.feishu_bitable_table_id)

    def batch_create(
        self, table_id: str, records: list[dict[str, Any]], *, label: str
    ) -> int:
        created = 0
        for start in range(0, len(records), FEISHU_BATCH_SIZE):
            batch = records[start : start + FEISHU_BATCH_SIZE]
            response = self.client.post(
                f"{FEISHU_API}/bitable/v1/apps/"
                f"{settings.feishu_bitable_app_token}/tables/{table_id}/"
                "records/batch_create",
                headers=self.headers,
                json={"records": batch},
            )
            self.request_count += 1
            body = _check_feishu_response(response, f"create {label}")
            items = body.get("data", {}).get("records", [])
            if len(items) != len(batch):
                raise FeishuSyncError(
                    f"Feishu created {len(items)} of {len(batch)} {label}"
                )
            created += len(items)
        return created

    def batch_update(
        self, table_id: str, records: list[dict[str, Any]], *, label: str
    ) -> int:
        updated = 0
        for start in range(0, len(records), FEISHU_BATCH_SIZE):
            batch = records[start : start + FEISHU_BATCH_SIZE]
            response = self.client.post(
                f"{FEISHU_API}/bitable/v1/apps/"
                f"{settings.feishu_bitable_app_token}/tables/{table_id}/"
                "records/batch_update",
                headers=self.headers,
                json={"records": batch},
            )
            self.request_count += 1
            body = _check_feishu_response(response, f"update {label}")
            items = body.get("data", {}).get("records", [])
            if len(items) != len(batch):
                raise FeishuSyncError(
                    f"Feishu updated {len(items)} of {len(batch)} {label}"
                )
            updated += len(items)
        return updated


def _purchase_date_timestamp(value: str) -> int:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ErpProtocolError(f"Invalid ERP purchase date: {value!r}") from exc
    return int(datetime.combine(parsed, time.min, SHANGHAI).timestamp() * 1000)


def _atomic_json_write(path: Path, payload: Any) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def crawl_new_orders(
    erp: ErpPurchaseClient,
    existing_contracts: set[str],
    *,
    limit: int | None,
    detail_workers: int,
) -> tuple[list[PurchaseOrder], list[PurchaseSummary], int]:
    summaries = erp.purchase_summaries()
    new_summaries = [
        summary
        for summary in summaries
        if summary.purchase_code not in existing_contracts
    ]
    if limit is not None:
        new_summaries = new_summaries[:limit]
    print(
        f"ERP active orders={len(summaries)}, Feishu existing={len(existing_contracts)}, "
        f"new_to_crawl={len(new_summaries)}"
    )

    if not new_summaries:
        return [], summaries, 0

    completed = 0
    completed_lock = threading.Lock()

    def fetch(summary: PurchaseSummary) -> PurchaseOrder:
        nonlocal completed
        order = erp.purchase_detail(summary)
        with completed_lock:
            completed += 1
            if completed == 1 or completed % 10 == 0 or completed == len(new_summaries):
                print(
                    f"ERP details {completed}/{len(new_summaries)}: "
                    f"{summary.purchase_code} ({len(order.tasks)} products)"
                )
        return order

    with ThreadPoolExecutor(max_workers=max(1, detail_workers)) as executor:
        orders = list(executor.map(fetch, new_summaries))
    return orders, summaries, len(new_summaries)


def _task_write_plan(
    existing_records: list[dict[str, Any]],
    orders: list[PurchaseOrder],
    active_stages: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Plan creates by natural key and stage updates by Feishu record ID."""
    existing_keys: set[tuple[str, str]] = set()
    update_records: list[dict[str, Any]] = []
    for record in existing_records:
        fields = record.get("fields") or {}
        contract = _field_text(fields.get("合同号"))
        sequence = _field_text(fields.get("序号"))
        if contract and sequence:
            existing_keys.add((contract, sequence))
        target_stage = active_stages.get(contract)
        record_id = _field_text(record.get("record_id"))
        current_stage = _field_text(fields.get("质检阶段"))
        if record_id and target_stage and current_stage != target_stage:
            update_records.append(
                {
                    "record_id": record_id,
                    "fields": {"质检阶段": target_stage},
                }
            )

    create_records: list[dict[str, Any]] = []
    for order in orders:
        for task in order.tasks:
            key = (order.purchase_code, task.sequence)
            if key in existing_keys:
                continue
            create_records.append(
                {
                    "fields": {
                        "合同号": order.purchase_code,
                        "序号": _bitable_sequence(task.sequence),
                        "产品类型": task.product_type,
                        "规格": task.specification,
                        "数量": task.quantity,
                        "质检阶段": order.order_status,
                    }
                }
            )
            existing_keys.add(key)
    return create_records, update_records


def _factory_backfill_plan(
    existing_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill empty factory cells only; never overwrite an administrator's value."""
    updates: list[dict[str, Any]] = []
    for record in existing_records:
        fields = record.get("fields") or {}
        if _field_text(fields.get("工厂")):
            continue
        record_id = _field_text(record.get("record_id"))
        factory = factory_name(_field_text(fields.get("合同号")))
        if record_id and factory:
            updates.append({"record_id": record_id, "fields": {"工厂": factory}})
    return updates


def _order_create_records(orders: list[PurchaseOrder], purchase_date_field: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for order in orders:
        fields: dict[str, Any] = {
            "合同号": order.purchase_code,
            purchase_date_field: _purchase_date_timestamp(order.purchase_date),
            "产品类型": order.product_types,
            "质检状态": "待分配",
        }
        factory = factory_name(order.purchase_code)
        if factory:
            fields["工厂"] = factory
        records.append({"fields": fields})
    return records


def _bitable_sequence(sequence: str) -> float | str:
    """Keep alphanumeric ERP sequences instead of aborting the whole sync."""
    try:
        value = float(sequence)
    except (TypeError, ValueError):
        return sequence
    return value if math.isfinite(value) else sequence


def sync_to_feishu(
    feishu: FeishuPurchaseSyncClient,
    orders: list[PurchaseOrder],
    active_stages: dict[str, str],
    *,
    ensure_schema: bool,
) -> tuple[int, int, int]:
    feishu.validate_fields()
    task_records, task_updates = _task_write_plan(
        feishu.existing_tasks(), orders, active_stages
    )

    # Tasks are inserted first. If a later order insert fails, the next run can
    # deduplicate by natural key, update its stage, and retry the order record.
    created_tasks = feishu.batch_create(
        settings.feishu_bitable_table_id,
        task_records,
        label="inspection tasks",
    )
    updated_tasks = feishu.batch_update(
        settings.feishu_bitable_table_id,
        task_updates,
        label="inspection task stages",
    )
    purchase_date_field = (
        feishu.ensure_purchase_date_field(create_if_missing=ensure_schema)
        if orders
        else "采购时间"
    )
    order_records = _order_create_records(orders, purchase_date_field)
    created_orders = feishu.batch_create(
        settings.feishu_bitable_order_table_id,
        order_records,
        label="orders",
    )
    return created_orders, created_tasks, updated_tasks


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Incrementally crawl active ERP purchases into Feishu Bitable."
    )
    parser.add_argument(
        "--base-url", default=os.getenv("ERP_BASE_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument("--username", default=os.getenv("ERP_USERNAME"))
    parser.add_argument("--password", default=os.getenv("ERP_PASSWORD"))
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(os.getenv("ERP_TOKEN_FILE", DEFAULT_TOKEN_FILE)),
    )
    parser.add_argument(
        "--snapshot-file",
        type=Path,
        default=Path(
            os.getenv("ERP_PURCHASE_SNAPSHOT_FILE", DEFAULT_SNAPSHOT_FILE)
        ),
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--detail-workers", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Crawl and save a local snapshot without writing Feishu.",
    )
    parser.add_argument(
        "--ensure-schema",
        action="store_true",
        help="Create the writable Feishu 采购时间 DateTime field if missing.",
    )
    parser.add_argument(
        "--backfill-factories-only",
        action="store_true",
        help="Fill empty 工厂 cells in the Feishu order table, then exit without reading ERP.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    if args.limit is not None and args.limit < 0:
        print("ERROR: --limit must be non-negative", file=sys.stderr)
        return 2
    if args.detail_workers < 1 or args.detail_workers > 8:
        print("ERROR: --detail-workers must be between 1 and 8", file=sys.stderr)
        return 2

    password = args.password
    if args.username and not password and not args.token_file.exists():
        password = getpass.getpass("ERP password: ")

    erp: ErpPurchaseClient | None = None
    feishu: FeishuPurchaseSyncClient | None = None
    try:
        feishu = FeishuPurchaseSyncClient(timeout=args.timeout)
        if args.backfill_factories_only:
            feishu.validate_fields()
            order_records = feishu.existing_orders()
            factory_updates = _factory_backfill_plan(order_records)
            updated = feishu.batch_update(
                settings.feishu_bitable_order_table_id,
                factory_updates,
                label="order factories",
            )
            print(
                f"Factory backfill complete: scanned_orders={len(order_records)}, "
                f"updated_factories={updated}, skipped={len(order_records) - updated}, "
                f"Feishu requests={feishu.request_count}"
            )
            return 0
        existing_contracts = feishu.existing_contracts()
        erp = ErpPurchaseClient(
            base_url=args.base_url,
            token_file=args.token_file,
            username=args.username,
            password=password,
            timeout=args.timeout,
        )
        orders, summaries, selected_count = crawl_new_orders(
            erp,
            existing_contracts,
            limit=args.limit,
            detail_workers=args.detail_workers,
        )
        snapshot = {
            "schema_version": 1,
            "captured_at": datetime.now(SHANGHAI).isoformat(),
            "erp_active_order_count": len(summaries),
            "selected_new_order_count": selected_count,
            "orders": [asdict(order) for order in orders],
        }
        _atomic_json_write(args.snapshot_file, snapshot)
        product_count = sum(len(order.tasks) for order in orders)
        print(
            f"Snapshot saved: {args.snapshot_file.resolve()} "
            f"({len(orders)} orders, {product_count} tasks)"
        )

        if args.dry_run:
            print(
                f"Dry run complete: ERP requests={erp.request_count}, "
                f"Feishu read requests={feishu.request_count}"
            )
            return 0

        active_stages = {
            summary.purchase_code: summary.order_status
            for summary in summaries
            if summary.order_status
        }
        created_orders, created_tasks, updated_tasks = sync_to_feishu(
            feishu,
            orders,
            active_stages,
            ensure_schema=args.ensure_schema,
        )
        print(
            f"Sync complete: created_orders={created_orders}, "
            f"created_tasks={created_tasks}, updated_task_stages={updated_tasks}, "
            f"ERP requests={erp.request_count}, "
            f"Feishu requests={feishu.request_count}"
        )
        return 0
    except (
        ErpAuthenticationError,
        ErpProtocolError,
        FeishuSyncError,
        httpx.HTTPError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        if erp is not None:
            erp.close()
        if feishu is not None:
            feishu.close()


if __name__ == "__main__":
    raise SystemExit(main())
