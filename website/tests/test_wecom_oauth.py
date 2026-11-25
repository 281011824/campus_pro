"""企微 OAuth 会话签名与访问控制测试（不访问真实企微接口）。"""
import time
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "website"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.main import app  # noqa: E402
from app.services import wecom_oauth  # noqa: E402

CLIENT = TestClient(app)


def test_session_roundtrip_and_tamper_rejected(monkeypatch):
    monkeypatch.setattr(wecom_oauth, "_secret", lambda: b"unit-test-secret")

    token = wecom_oauth.sign_session("zhangmin")
    assert wecom_oauth.read_session(token) == "zhangmin"

    body, sig = token.rsplit(".", 1)
    assert wecom_oauth.read_session(body + ".x" + sig) == ""
    assert wecom_oauth.read_session("not-a-token") == ""


def test_expired_session_rejected(monkeypatch):
    monkeypatch.setattr(wecom_oauth, "_secret", lambda: b"unit-test-secret")
    token = wecom_oauth.sign_session("zhangmin", ttl=-1)
    assert wecom_oauth.read_session(token) == ""


def test_login_returns_503_when_disabled():
    response = CLIENT.get("/api/v1/auth/wecom/login")
    assert response.status_code == 503
    assert response.json()["code"] == "wecom_oauth_disabled"


def test_enabled_without_session_blocks_business_api(monkeypatch):
    monkeypatch.setattr(wecom_oauth, "is_enabled", lambda: True)
    response = CLIENT.get("/api/v1/org/directory")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_health_stays_anonymous_when_enabled(monkeypatch):
    monkeypatch.setattr(wecom_oauth, "is_enabled", lambda: True)
    # 未登录也应进入代理逻辑；Redis 不可用时返回 503 而不是 401
    response = CLIENT.get("/api/v1/health")
    assert response.status_code != 401


def test_session_cookie_replaces_spoofed_header(monkeypatch):
    monkeypatch.setattr(wecom_oauth, "is_enabled", lambda: True)
    monkeypatch.setattr(wecom_oauth, "_secret", lambda: b"unit-test-secret")
    token = wecom_oauth.sign_session("zhangmin")
    response = CLIENT.get(
        "/api/v1/org/directory",
        headers={
            "Cookie": f"{wecom_oauth.SESSION_COOKIE}={token}",
            "X-Auth-User": "someone-else",
        },
    )
    assert response.status_code != 401
