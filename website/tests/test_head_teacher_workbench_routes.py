"""Task 3 的 FastAPI 精确注册与既有路由共存目标测试。"""
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[2]
WEBSITE_ROOT = ROOT / "website"
for path in (ROOT, WEBSITE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tasks.interfaces.contract import API_ROUTES  # noqa: E402

pytest.importorskip(
    "app.api.v1.head_teacher_workbench",
    reason="Task 3 尚未注册班主任工作台 FastAPI 路由",
)

from app.main import app  # noqa: E402
import app.api.v1.head_teacher_workbench as workbench_routes  # noqa: E402
from tasks.interfaces import worker  # noqa: E402


CLIENT = TestClient(app)
REGISTERED_ROUTE_LIST = [
    (method, route.path)
    for route in app.routes
    for method in getattr(route, "methods", set())
]
REGISTERED_ROUTES = {
    (method, route.path)
    for route in app.routes
    for method in getattr(route, "methods", set())
}


@pytest.mark.parametrize(
    "route",
    API_ROUTES,
    ids=[f"{route.method} {route.path}" for route in API_ROUTES],
)
def test_archived_api_has_one_exact_fastapi_registration(route):
    assert REGISTERED_ROUTE_LIST.count(route.key) == 1


def test_workbench_page_coexists_with_root_probe():
    assert ("GET", "/api/head_teacher_workbench") in REGISTERED_ROUTES
    assert ("GET", "/") in REGISTERED_ROUTES


def test_no_global_api_catchall_shadows_existing_website_routes():
    wildcard_paths = {
        route.path for route in app.routes
        if "{path:path}" in route.path or "{file_path:path}" in route.path
    }
    assert not any(path.startswith("/api/") for path in wildcard_paths)


class FakeWorker:
    """Mock worker.handle_request(request) 返回 Redis 协议格式的 response dict。"""
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def handle_request(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.result


def install_fake_worker(monkeypatch, result=None, error=None):
    fake = FakeWorker(result=result, error=error)
    monkeypatch.setattr(worker, "handle_request", fake.handle_request)
    return fake


def worker_result(body, status=200, content_type="application/json; charset=utf-8"):
    return {
        "request_id": "fake-request",
        "status": status,
        "content_type": content_type,
        "body": body,
    }


def test_workbench_page_assets_and_original_design_are_preserved():
    # 主页面：简洁版班主任工作台（工作台 / 需关注 / 德育记录 / 待办）
    response = CLIENT.get("/api/head_teacher_workbench")
    assert response.status_code == 200
    for tab in ("概览", "成长档案", "出勤统计", "学情预警", "德育量化", "班务减负", "家校协同", "数据备份"):
        assert tab in response.text
    assert "/static/head_teacher_workbench/app.css" in response.text
    assert "/static/head_teacher_workbench/app.js" in response.text

    app_js = (
        ROOT / "website" / "app" / "static" / "head_teacher_workbench" / "app.js"
    ).read_text(encoding="utf-8")
    # 登录接入：401 自动跳登录、按登录会话自动匹配身份
    assert "/api/v1/login?next=" in app_js
    assert "/api/v1/portal/auto" in app_js

    root = CLIENT.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["location"] == "/api/head_teacher_workbench"

    for name in ("app.js", "app.css"):
        assert CLIENT.get(f"/static/head_teacher_workbench/{name}").status_code == 200


def test_normal_api_preserves_raw_request_and_business_error_response(monkeypatch):
    body = json.dumps(
        {"code": "forbidden", "error": "禁止访问", "data": None},
        ensure_ascii=False,
    )
    fake = install_fake_worker(
        monkeypatch, worker_result(body, status=403),
    )
    response = CLIENT.post(
        "/api/v1/chat?a=1&a=2&blank=",
        json={"text": "你好"},
        headers={"X-Auth-User": "zhangmin"},
    )
    assert response.status_code == 403
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.content == body.encode("utf-8")
    req = fake.calls[0]
    assert req["method"] == "POST"
    assert req["path"] == "/api/v1/chat"
    assert req["query"] == "a=1&a=2&blank="
    assert req["body"] == {"text": "你好"}
    assert req["X-Auth-User"] == "zhangmin"


def test_wecom_verify_preserves_raw_query_and_plain_text(monkeypatch):
    fake = install_fake_worker(
        monkeypatch,
        worker_result("echo_你好", content_type="text/plain; charset=utf-8"),
    )
    response = CLIENT.get(
        "/api/v1/wecom/callback?echostr=a%2Bb&nonce=n&nonce=n2",
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text == "echo_你好"
    req = fake.calls[0]
    assert req["query"] == "echostr=a%2Bb&nonce=n&nonce=n2"
    assert req["body"] is None


def test_wecom_callback_preserves_raw_xml_request_and_response(monkeypatch):
    response_body = "<xml><Content><![CDATA[已收到]]></Content></xml>"
    fake = install_fake_worker(
        monkeypatch,
        worker_result(response_body, content_type="text/xml; charset=utf-8"),
    )
    response = CLIENT.post(
        "/api/v1/wecom/callback?msg_signature=sig&timestamp=1700000000",
        content="<xml><Content>你好</Content></xml>",
        headers={"Content-Type": "text/xml"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/xml; charset=utf-8"
    assert response.text == response_body
    req = fake.calls[0]
    assert req["query"] == "msg_signature=sig&timestamp=1700000000"


@pytest.mark.skip(reason="单体化后无 Redis，基础设施故障不再适用")
@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [],
)
def test_infrastructure_faults_have_distinct_json_errors_and_no_replay(
    monkeypatch, error, status_code, code,
):
    """Redis 基础设施故障测试 — 单体化后跳过。"""
    pass
