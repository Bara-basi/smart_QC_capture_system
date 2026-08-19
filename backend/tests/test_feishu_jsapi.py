import pytest

from app.core.config import settings
from app.services.feishu_auth import FeishuAuthError
from app.services.feishu_jsapi import _validate_page_url


def test_jsapi_signature_url_must_use_configured_https_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "web_origin", "https://qc.example.com")

    _validate_page_url("https://qc.example.com/capture?task=1")

    with pytest.raises(FeishuAuthError):
        _validate_page_url("http://qc.example.com/capture")
    with pytest.raises(FeishuAuthError):
        _validate_page_url("https://attacker.example/capture")


def test_jsapi_signature_allows_only_explicit_http_ip_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "web_origin", "http://203.0.113.10")
    _validate_page_url("http://203.0.113.10/")

    monkeypatch.setattr(settings, "web_origin", "http://qc.example.com")
    with pytest.raises(FeishuAuthError):
        _validate_page_url("http://qc.example.com/")
