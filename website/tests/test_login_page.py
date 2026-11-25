"""登录页与本地账号登录测试（不访问真实企微接口与 Redis）。"""
import hashlib
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "website"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.main import app  # noqa: E402
from app.initializer import g  # noqa: E402
from app.services import wecom_oauth  # noqa: E402
import app.api.v1.login as login_routes  # noqa: E402
import app.api.v1.head_teacher_workbench as workbench_routes  # noqa: E402
from tasks.interfaces import worker  # noqa: E402

CLIENT = TestClient(app)
PASSWORD = "Gov@2026"
USERID = "fc"


@pytest.fixture(autouse=True)
def reset_login_state(monkeypatch):
    """每个用例都从“未配置且无失败记录、无残留 Cookie”开始。"""
    login_routes._failures.clear()
    CLIENT.cookies.clear()
    monkeypatch.setattr(g.config, "LOCAL_LOGIN_USERS", "")
    monkeypatch.setattr(g.config, "AUTH_COOKIE_SECRET", "")
    yield
    login_routes._failures.clear()
    CLIENT.cookies.clear()


def configure_accounts(monkeypatch, password=PASSWORD, userid=USERID):
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    monkeypatch.setattr(g.config, "LOCAL_LOGIN_USERS", f"{userid}:{digest}")
    monkeypatch.setattr(g.config, "AUTH_COOKIE_SECRET", "unit-test-secret")


def test_login_page_uses_local_lightweight_assets():
    response = CLIENT.get("/api/v1/login")
    assert response.status_code == 200
    text = response.text
    assert "班主任工作台" in text
    assert "京山市中等职业技术学校" in text
    assert "用户登录" in text
    assert "/static/vendor/bootstrap/bootstrap.min.css" in text
    assert "/static/vendor/jquery/jquery.min.js" in text
    assert "/static/login/style.css" in text
    assert "/static/login/login.js" in text
    # 不得依赖外部 CDN（校园网/政务网环境常被拦截）
    assert "cdn.jsdelivr" not in text
    assert "code.jquery.com" not in text


def test_login_static_assets_are_served():
    for path in (
        "/static/vendor/bootstrap/bootstrap.min.css",
        "/static/vendor/jquery/jquery.min.js",
        "/static/login/style.css",
        "/static/login/login.js",
    ):
        response = CLIENT.get(path)
        assert response.status_code == 200
        assert len(response.content) > 500


def test_login_page_disables_wecom_entry_when_oauth_off():
    response = CLIENT.get("/api/v1/login")
    assert 'class="wecom-btn is-disabled"' in response.text
    assert "待管理员开通" in response.text


def test_login_page_enables_wecom_entry_when_oauth_on(monkeypatch):
    monkeypatch.setattr(wecom_oauth, "is_enabled", lambda: True)
    response = CLIENT.get("/api/v1/login")
    assert 'href="/api/v1/auth/wecom/login"' in response.text


@pytest.mark.parametrize(
    "raw",
    ["//evil.example.com", "https://evil.example.com", "/\\evil", ""],
)
def test_next_param_falls_back_to_workbench(raw):
    response = CLIENT.get("/api/v1/login", params={"next": raw})
    assert 'data-next="/api/head_teacher_workbench"' in response.text


def test_next_param_keeps_internal_path():
    response = CLIENT.get("/api/v1/login", params={"next": "/api/v1/todo/list"})
    assert 'data-next="/api/v1/todo/list"' in response.text


def test_login_returns_503_when_not_configured():
    response = CLIENT.post(
        "/api/v1/login",
        json={"username": USERID, "password": PASSWORD},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "local_login_disabled"


def test_login_success_sets_signed_session_cookie(monkeypatch):
    configure_accounts(monkeypatch)
    response = CLIENT.post(
        "/api/v1/login",
        json={"username": USERID, "password": PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 0
    cookie = response.headers["set-cookie"]
    assert f"{wecom_oauth.SESSION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    token = response.cookies.get(wecom_oauth.SESSION_COOKIE)
    assert wecom_oauth.read_session(token) == USERID


def test_login_rejects_wrong_password(monkeypatch):
    configure_accounts(monkeypatch)
    response = CLIENT.post(
        "/api/v1/login",
        json={"username": USERID, "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_login_rejects_unknown_account(monkeypatch):
    configure_accounts(monkeypatch)
    response = CLIENT.post(
        "/api/v1/login",
        json={"username": "someone", "password": PASSWORD},
    )
    assert response.status_code == 401


def test_login_rejects_missing_fields(monkeypatch):
    configure_accounts(monkeypatch)
    response = CLIENT.post("/api/v1/login", json={"username": USERID})
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_login_rejects_malformed_body(monkeypatch):
    configure_accounts(monkeypatch)
    response = CLIENT.post(
        "/api/v1/login",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_login_throttles_repeated_failures(monkeypatch):
    configure_accounts(monkeypatch)
    for _ in range(login_routes._MAX_FAILS):
        response = CLIENT.post(
            "/api/v1/login",
            json={"username": USERID, "password": "wrong-password"},
        )
        assert response.status_code == 401
    blocked = CLIENT.post(
        "/api/v1/login",
        json={"username": USERID, "password": PASSWORD},
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "too_many_attempts"


def test_session_cookie_identifies_user_when_oauth_disabled(monkeypatch):
    configure_accounts(monkeypatch)
    token = wecom_oauth.sign_session(USERID)

    calls = []

    def fake_handle(request):
        calls.append(request)
        return {
            "request_id": "fake",
            "status": 200,
            "content_type": "application/json; charset=utf-8",
            "body": '{"code":0,"data":{}}',
        }

    monkeypatch.setattr(worker, "handle_request", fake_handle)
    response = CLIENT.get(
        "/api/v1/org/directory",
        headers={
            "Cookie": f"{wecom_oauth.SESSION_COOKIE}={token}",
            "X-Auth-User": "spoofed",
        },
    )
    assert response.status_code == 200
    assert calls[0]["X-Auth-User"] == USERID


def test_local_login_enforced_rejects_spoofed_header(monkeypatch):
    """配置了本地账号后，请求头不再可信，无会话一律 401。"""
    configure_accounts(monkeypatch)
    response = CLIENT.get(
        "/api/v1/org/directory",
        headers={"X-Auth-User": "spoofed"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"


def test_root_redirects_to_login_when_account_configured(monkeypatch):
    configure_accounts(monkeypatch)
    response = CLIENT.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/api/v1/login"


def test_root_skips_login_with_valid_session(monkeypatch):
    configure_accounts(monkeypatch)
    token = wecom_oauth.sign_session(USERID)
    response = CLIENT.get(
        "/",
        headers={"Cookie": f"{wecom_oauth.SESSION_COOKIE}={token}"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/api/head_teacher_workbench"


def test_logout_clears_session_cookie():
    response = CLIENT.get("/api/v1/logout", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/api/v1/login"
    assert "htw_session=" in response.headers["set-cookie"]
def test_school_account_login_uses_sqlite(monkeypatch):
    """全校教师账号（school_accounts 表）可直接登录。"""
    digest = hashlib.sha256("pw-test".encode("utf-8")).hexdigest()
    monkeypatch.setattr(g.config, "AUTH_COOKIE_SECRET", "unit-test-secret")
    monkeypatch.setattr(login_routes, "_accounts", lambda: {})
    monkeypatch.setattr(login_routes, "_local_enabled", lambda a: True)
    monkeypatch.setattr(
        login_routes, "_db_digest",
        lambda u: digest if u == "JS0001" else None,
    )
    ok = CLIENT.post("/api/v1/login", json={"username": "JS0001", "password": "pw-test"})
    assert ok.status_code == 200
    assert ok.json()["data"]["userid"] == "JS0001"
    bad = CLIENT.post("/api/v1/login", json={"username": "JS0001", "password": "wrong"})
    assert bad.status_code == 401


def test_school_accounts_import_and_digest(tmp_path, monkeypatch):
    from tasks.domain.identity import accounts
    from tasks.shared import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "accounts.db")
    accounts.init()
    n = accounts.import_records([{
        "userid": "JS0001", "name": "李泽旭",
        "password_sha256": accounts.sha256_hex("secret"),
        "wecom_userid": "13500000000", "dept": "校委会",
        "post_name": "书记、校长", "category": "校领导", "status": "本校",
    }])
    assert n == 1
    rec = accounts.get("JS0001")
    assert rec["name"] == "李泽旭"
    assert rec["password_sha256"] == accounts.sha256_hex("secret")
    # 重复导入按登录账号覆盖，不新增
    accounts.import_records([dict(rec, name="李泽旭(更新)")])
    assert accounts.count() == 1
    assert accounts.get("JS0001")["name"].startswith("李泽旭")