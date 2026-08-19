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
