#!/usr/bin/env python3
"""Read-only black-box checks for a deployed QC capture instance.

The probe deliberately avoids authenticated writes and valid webhook secrets.
It checks public availability, anonymous access rejection, redirect handling,
and the presence of browser/API security headers.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

BASE_URL = os.environ.get("QC_QA_BASE_URL", "https://47.96.9.22").rstrip("/")
TIMEOUT_SECONDS = 10


@dataclass
class Result:
    name: str
    passed: bool
    detail: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def request(
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = False,
) -> tuple[int, dict[str, str], bytes, str | None]:
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        NoRedirect(),
    )
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers=headers or {},
    )
    try:
        with opener.open(req, timeout=TIMEOUT_SECONDS) as response:
            return (
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                response.read(256 * 1024),
                None,
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            {key.lower(): value for key, value in exc.headers.items()},
            exc.read(256 * 1024),
            None,
        )
    except urllib.error.URLError as exc:
        return 0, {}, b"", str(exc.reason)


def expect(name: str, actual: Any, expected: Any) -> Result:
    return Result(name, actual == expected, f"expected={expected!r}, actual={actual!r}")


def add_header_check(results: list[Result], path: str, headers: dict[str, str]) -> None:
    controls = {
        "strict-transport-security": "HTTPS 强制",
        "content-security-policy": "内容注入限制",
        "x-content-type-options": "MIME 嗅探限制",
        "referrer-policy": "Referer 泄漏限制",
        "permissions-policy": "浏览器能力限制",
    }
    for header, purpose in controls.items():
        value = headers.get(header)
        results.append(
            Result(
                f"{path} 安全响应头 {header}",
                bool(value),
                f"{purpose}；当前值={value!r}",
            )
        )


def main() -> int:
    results: list[Result] = []

    status, headers, body, error = request("GET", "/health")
    results.append(expect("/health 可达并返回 200", (status, error), (200, None)))
    try:
        health = json.loads(body)
    except ValueError:
        health = None
    results.append(expect("/health 返回 status=ok", health, {"status": "ok"}))
    add_header_check(results, "/health", headers)

    status, headers, _, _ = request("GET", "/api/v1/health")
    results.append(expect("/api/v1/health 可达并返回 200", status, 200))
    results.append(
        Result(
            "API 响应设置 no-store",
            headers.get("cache-control", "").lower().find("no-store") >= 0,
            f"cache-control={headers.get('cache-control')!r}",
        )
    )

    protected_gets = [
        "/api/v1/auth/me",
        "/api/v1/dashboard",
        "/api/v1/dashboard/tasks/not-a-real-record",
        "/api/v1/photos",
        "/api/v1/photos?scope=shared",
        "/api/v1/feishu/photos/not-a-real-photo/preview",
        "/api/v1/feishu/jsapi-signature?url=https%3A%2F%2F47.96.9.22%2F",
    ]
    for path in protected_gets:
        status, response_headers, _, error = request("GET", path)
        results.append(
            expect(f"匿名访问 {path} 被拒绝", (status, error), (401, None))
        )
        results.append(
            expect(
                f"{path} 不发放跨域许可",
                response_headers.get("access-control-allow-origin"),
                None,
            )
        )

    status, headers, _, _ = request(
        "GET",
        "/api/v1/auth/feishu/login?next=%2Fgallery%3Fscope%3Dshared",
    )
    results.append(expect("飞书登录入口返回 302", status, 302))
    location = headers.get("location", "")
    results.append(
        expect(
            "飞书登录入口跳转到官方授权域",
            location.startswith("https://accounts.feishu.cn/open-apis/authen/v1/authorize?"),
            True,
        )
    )

    status, _, _, _ = request(
        "GET",
        "/api/v1/auth/feishu/callback",
    )
    results.append(expect("OAuth 回调缺失 code/state 时返回 400", status, 400))

    webhook_headers = {
        "Content-Type": "application/json",
        "Origin": "https://attacker.example",
    }
    for path in (
        "/api/v1/integrations/feishu/order-sync",
        "/api/v1/integrations/feishu/order-unassign",
        "/api/v1/integrations/feishu/order-retire",
    ):
        status, response_headers, _, _ = request(
            "POST",
            path,
            body=b'{"record_id":"qa-readonly-no-secret"}',
            headers=webhook_headers,
        )
        results.append(expect(f"无效密钥访问 {path} 被拒绝", status, 401))
        results.append(
            expect(
                f"{path} 不发放跨域许可",
                response_headers.get("access-control-allow-origin"),
                None,
            )
        )

    status, headers, _, _ = request(
        "GET",
        "/api/v1/photos",
        headers={"Origin": "https://attacker.example"},
    )
    results.append(expect("带恶意 Origin 的匿名请求仍返回 401", status, 401))
    results.append(
        expect(
            "带恶意 Origin 的响应无 CORS 放行",
            headers.get("access-control-allow-origin"),
            None,
        )
    )

    for result in results:
        state = "PASS" if result.passed else "FAIL"
        print(f"[{state}] {result.name}: {result.detail}")

    failed = sum(not result.passed for result in results)
    print(f"\nSUMMARY total={len(results)} passed={len(results) - failed} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
