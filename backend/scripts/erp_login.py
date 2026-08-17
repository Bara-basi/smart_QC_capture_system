r"""Log in to the ERP and persist its reusable HTTP session cookies.

The ERP currently authenticates with a form POST and returns a ``JSESSIONID``
cookie.  The password is read from the environment (or an interactive prompt)
and is never written to disk.

Run from the backend directory::

    $env:ERP_USERNAME = "AI004"
    $env:ERP_PASSWORD = "..."
    .venv\Scripts\python.exe scripts\erp_login.py

Validate the saved session later without supplying the password::

    .venv\Scripts\python.exe scripts\erp_login.py --check-saved
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

DEFAULT_BASE_URL = "https://erp.mtholdinggroup.com/"
DEFAULT_TOKEN_FILE = Path(__file__).resolve().parents[1] / "data" / "erp_session.json"
LOGIN_FORM_MARKER = 'id="frmLogin"'
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class ErpAuthenticationError(RuntimeError):
    """Raised when the ERP rejects a login or a saved session is invalid."""


@dataclass(frozen=True)
class AuthenticationResult:
    username: str
    token_name: str
    token_value: str
    cookies: list[dict[str, Any]]
    final_url: str


def _input_value(html: str, element_id: str) -> str | None:
    """Extract a simple input value without adding an HTML parser dependency."""
    input_match = re.search(
        rf"<input\b[^>]*\bid=[\"']{re.escape(element_id)}[\"'][^>]*>",
        html,
        flags=re.IGNORECASE,
    )
    if not input_match:
        return None
    value_match = re.search(
        r"\bvalue=[\"']([^\"']*)[\"']",
        input_match.group(0),
        flags=re.IGNORECASE,
    )
    return value_match.group(1) if value_match else ""


def _looks_authenticated(html: str) -> bool:
    if LOGIN_FORM_MARKER.lower() in html.lower():
        return False
    return any(marker in html for marker in ("退出", "注销", "logout", "logOut"))


def _cookies_from_client(client: httpx.Client) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for cookie in client.cookies.jar:
        cookies.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": bool(cookie.secure),
                "expires": cookie.expires,
            }
        )
    return cookies


def _primary_token(cookies: list[dict[str, Any]]) -> tuple[str, str]:
    preferred_names = ("JSESSIONID", "SESSION", "session", "token", "access_token")
    by_name = {str(cookie["name"]): str(cookie["value"]) for cookie in cookies}
    for name in preferred_names:
        if by_name.get(name):
            return name, by_name[name]
    if cookies:
        return str(cookies[0]["name"]), str(cookies[0]["value"])
    raise ErpAuthenticationError("登录响应未返回任何会话 Cookie。")


def login(
    username: str,
    password: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 30.0,
) -> AuthenticationResult:
    """Authenticate against the ERP and return the reusable session cookies."""
    if not username.strip():
        raise ValueError("ERP 用户名不能为空。")
    if not password:
        raise ValueError("ERP 密码不能为空。")

    normalized_base_url = base_url.rstrip("/") + "/"
    with httpx.Client(
        headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout
    ) as client:
        login_page = client.get(normalized_base_url)
        login_page.raise_for_status()

        if _input_value(login_page.text, "needVerifyCode") not in (None, "", "false"):
            raise ErpAuthenticationError("ERP 当前要求输入图形验证码，无法进行无人值守登录。")

        response = client.post(
            normalized_base_url,
            data={
                "userId": username.strip(),
                "password": password,
                "redirectUrl": "",
                "global_menuId": "",
                "languageOption": "",
                "verifyCode": "",
                "needVerifyCode": "false",
            },
            headers={"Referer": normalized_base_url},
        )
        response.raise_for_status()

        if not _looks_authenticated(response.text):
            message = _input_value(response.text, "message")
            suffix = f"：{message}" if message and message != "请登录" else ""
            raise ErpAuthenticationError(f"ERP 登录失败{suffix}")

        cookies = _cookies_from_client(client)
        token_name, token_value = _primary_token(cookies)
        return AuthenticationResult(
            username=username.strip(),
            token_name=token_name,
            token_value=token_value,
            cookies=cookies,
            final_url=str(response.url),
        )


def save_session(
    result: AuthenticationResult,
    token_file: Path,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> None:
    """Atomically persist session cookies without storing the password."""
    payload = {
        "schema_version": 1,
        "base_url": base_url.rstrip("/") + "/",
        "username": result.username,
        "captured_at": datetime.now(UTC).isoformat(),
        "primary_token": {
            "name": result.token_name,
            "value": result.token_value,
        },
        "cookies": result.cookies,
    }

    token_file = token_file.resolve()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{token_file.name}.", suffix=".tmp", dir=token_file.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, ensure_ascii=False, indent=2)
            file_handle.write("\n")
        try:
            os.chmod(temporary_name, 0o600)
        except OSError:
            pass
        os.replace(temporary_name, token_file)
    finally:
        temporary_path = Path(temporary_name)
        if temporary_path.exists():
            temporary_path.unlink()


def load_session(token_file: Path) -> dict[str, Any]:
    try:
        with token_file.open("r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except FileNotFoundError as exc:
        raise ErpAuthenticationError(f"未找到会话文件：{token_file}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ErpAuthenticationError(f"无法读取会话文件：{token_file}") from exc

    if payload.get("schema_version") != 1 or not payload.get("cookies"):
        raise ErpAuthenticationError(f"会话文件格式无效：{token_file}")
    return payload


def authenticated_client_from_file(
    token_file: Path = DEFAULT_TOKEN_FILE,
    *,
    timeout: float = 30.0,
) -> httpx.Client:
    """Create an HTTP client carrying cookies saved by :func:`save_session`."""
    payload = load_session(token_file)
    client = httpx.Client(
        headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout
    )
    for cookie in payload["cookies"]:
        client.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain") or urlparse(payload["base_url"]).hostname,
            path=cookie.get("path") or "/",
        )
    return client


def validate_saved_session(
    token_file: Path = DEFAULT_TOKEN_FILE,
    *,
    timeout: float = 30.0,
) -> tuple[bool, str]:
    """Check whether a saved ERP session still reaches an authenticated page."""
    payload = load_session(token_file)
    with authenticated_client_from_file(token_file, timeout=timeout) as client:
        response = client.get(urljoin(payload["base_url"], "/"))
        response.raise_for_status()
        return _looks_authenticated(response.text), str(response.url)


def _token_fingerprint(token_value: str) -> str:
    return hashlib.sha256(token_value.encode("utf-8")).hexdigest()[:12]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证 ERP 登录并保存可复用会话 Cookie。")
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
        "--check-saved",
        action="store_true",
        help="只验证已保存的会话，不重新提交账号密码。",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.check_saved:
            valid, final_url = validate_saved_session(args.token_file, timeout=args.timeout)
            if not valid:
                raise ErpAuthenticationError("已保存的 ERP 会话已失效，请重新登录。")
            payload = load_session(args.token_file)
            primary_token = payload["primary_token"]
            print(
                "ERP saved session is valid: "
                f"user={payload['username']}, token={primary_token['name']}, "
                f"fingerprint={_token_fingerprint(primary_token['value'])}, "
                f"url={final_url}"
            )
            return 0

        username = args.username or input("ERP username: ").strip()
        password = args.password or getpass.getpass("ERP password: ")
        result = login(
            username,
            password,
            base_url=args.base_url,
            timeout=args.timeout,
        )
        save_session(result, args.token_file, base_url=args.base_url)
        print(
            "ERP login succeeded: "
            f"user={result.username}, token={result.token_name}, "
            f"fingerprint={_token_fingerprint(result.token_value)}, "
            f"saved_to={args.token_file.resolve()}"
        )
        return 0
    except (ErpAuthenticationError, httpx.HTTPError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
