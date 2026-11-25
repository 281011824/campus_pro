import ast
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import uuid
import xml.etree.ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.interfaces import worker  # noqa: E402
from tasks.modules.head_teacher import (coedu, push)
from tasks.domain.growth import growth
from tasks.domain.identity import org
from tasks.interfaces import server
from tasks.shared import (config, crypto, db, wecom)
from tasks.interfaces.contract import (RESPONSE_REQUIRED_FIELDS, TEXT_CONTENT_TYPE, XML_CONTENT_TYPE)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "runtime" / "worker-test.db")
    growth.CACHE.clear()
    server._TRUSTED_IDENTITY = ""
    db.init_db()
    org.sync_directory()


def call(method, path, *, query=None, body=None, raw_body=None, auth_user=""):
    if raw_body is None:
        raw_body = (json.dumps(body, ensure_ascii=False).encode("utf-8")
                    if body is not None else b"")
    response = worker.handle_request({
        "request_id": "test-" + uuid.uuid4().hex,
        "method": method,
        "path": path,
        "query": urllib.parse.urlencode(query or {}),
        "body": body,
        "raw_body": base64.b64encode(raw_body).decode("ascii"),
        "X-Auth-User": auth_user,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    assert set(response) == RESPONSE_REQUIRED_FIELDS
    assert isinstance(response["body"], str)
    return response


def json_call(*args, **kwargs):
    response = call(*args, **kwargs)
    return response, json.loads(response["body"])


def resolve(userid="zhangmin", post_id=None):
    body = {"userid": userid}
    if post_id:
        body["post_id"] = post_id
    response, payload = json_call("POST", "/api/v1/session/resolve", body=body, auth_user=userid)
    assert response["status"] == 200, payload
    return payload["data"]["ctx"]


def test_health_bad_json_identity_and_forbidden_fields():
    response, payload = json_call("GET", "/api/v1/health/")
    assert response["status"] == 200
    assert payload["code"] == 0
    assert payload["data"]["settings"]["wecom_mode"] == "mock"
    assert payload["data"]["settings"]["growth_nav_mode"] == "fixture"
    assert "wecom_corp_secret" not in payload["data"]["settings"]

    response, payload = json_call(
        "POST", "/api/v1/session/resolve", raw_body=b"{bad json")
    assert response["status"] == 400
    assert payload["code"] == "bad_json"

    response, payload = json_call(
        "POST", "/api/v1/session/resolve",
        body={"userid": "zhangmin", "level": "L6"})
    assert response["status"] == 400
    assert payload["code"] == "forbidden_fields"

    ctx = resolve()
    response, payload = json_call(
        "GET", "/api/v1/session/" + ctx["session_id"], auth_user="someone_else")
    assert response["status"] == 403
    assert payload["code"] == "identity_mismatch"


def test_derived_zone_redlines_and_not_ready_degradation():
    ctx = resolve()
    response, payload = json_call(
        "GET", "/api/v1/growth/derived",
        query={"session_id": ctx["session_id"], "fields": "answers,scores"},
        auth_user="zhangmin")
    assert response["status"] == 403
    assert payload["code"] == "derived_zone_forbidden"

    response, payload = json_call(
        "GET", "/api/v1/growth/workitem",
        query={"session_id": ctx["session_id"], "item": "scores"},
        auth_user="zhangmin")
    assert response["status"] == 200
    assert payload["data"]["data"]["available"] is False
    assert "估算" in payload["data"]["data"]["rule"]

    response, payload = json_call(
        "GET", "/api/v1/growth/numbers",
        query={"session_id": ctx["session_id"]}, auth_user="zhangmin")
    numbers = payload["data"]["data"]
    assert numbers["degraded"] is True
    assert "未就绪" in numbers["dorm_note"]
    assert "口径未对齐" in numbers["leave_note"]

    ctx2607 = resolve("Tiao", "p_xhc_bzr_2607")
    response, payload = json_call(
        "GET", "/api/v1/growth/balance",
        query={"session_id": ctx2607["session_id"], "class_id": "2607"},
        auth_user="Tiao")
    assert response["status"] == 200
    assert payload["data"]["data"]["available"] is False
    assert "未就绪" in payload["data"]["data"]["reason"]
    assert "不以示例值或旧值替代" in payload["data"]["data"]["reason"]


def test_two_stage_write_requires_confirmation():
    ctx = resolve()
    before = db.q("SELECT COUNT(*) AS n FROM write_records", one=True)["n"]
    response, payload = json_call(
        "POST", "/api/v1/chat",
        body={"session_id": ctx["session_id"], "text": "记一笔：张××上课玩手机扣2分"},
        auth_user="zhangmin")
    assert response["status"] == 200
    pending_id = payload["data"]["pending_id"]
    assert pending_id
    assert db.q("SELECT COUNT(*) AS n FROM write_records", one=True)["n"] == before

    response, payload = json_call(
        "GET", "/api/v1/write/pending", query={"session_id": ctx["session_id"]},
        auth_user="zhangmin")
    assert payload["data"]["pending"]["id"] == pending_id

    response, payload = json_call(
        "POST", "/api/v1/write/confirm",
        body={"session_id": ctx["session_id"], "decision": "confirm"},
        auth_user="zhangmin")
    assert response["status"] == 200
    assert "已确认落库" in payload["data"]["reply"]
    assert db.q("SELECT COUNT(*) AS n FROM write_records", one=True)["n"] == before + 1


def test_space_federation_and_coeducation_keep_context_isolated():
    ctx = resolve()
    sid = ctx["session_id"]
    response, payload = json_call(
        "POST", "/api/v1/space/focus",
        body={"session_id": sid, "module": "归寝与请假", "class_id": "2611"},
        auth_user="zhangmin")
    assert response["status"] == 200
    assert payload["data"]["shared"]["focus_class"] == "2611"

    response, payload = json_call(
        "POST", "/api/v1/chat", body={"session_id": sid, "text": "生成本周周报"},
        auth_user="zhangmin")
    shared = payload["data"]["space_shared"]
    assert shared["focus_module"] == "归寝与请假"
    assert shared["updated_by"] == "secretary"

    response, payload = json_call(
        "POST", "/api/v1/space/event",
        body={"session_id": sid, "patch": {"parent_phone": "13800000000"}},
        auth_user="zhangmin")
    assert response["status"] == 403
    assert payload["code"] == "space_write_forbidden"

    response, payload = json_call(
        "POST", "/api/v1/federation/search",
        body={"session_id": sid, "metric": "dorm"}, auth_user="zhangmin")
    assert response["status"] == 200
    assert payload["data"]["no_context_pollution"] is True
    assert payload["data"]["writes_to_space"] is False
    assert payload["data"]["space_shared_before"] == payload["data"]["space_shared_after"]

    response, payload = json_call(
        "POST", "/api/v1/federation/search",
        body={"session_id": sid, "metric": "scores"}, auth_user="zhangmin")
    assert response["status"] == 400

    teacher = resolve("teacher1")
    response, payload = json_call(
        "POST", "/api/v1/coedu/preview",
        body={"session_id": teacher["session_id"], "metric": "exam"},
        auth_user="teacher1")
    assert response["status"] == 200
    assert payload["data"]["persisted"] is False

    response, payload = json_call(
        "POST", "/api/v1/coedu/push",
        body={"session_id": teacher["session_id"], "metric": "status"},
        auth_user="teacher1")
    assert response["status"] == 200
    assert payload["data"]["pushed_count"] == 2
    assert payload["data"]["no_context_pollution"] is True
    assert payload["data"]["writes_to_space"] is False

    response, payload = json_call(
        "GET", "/api/v1/coedu/inbox", query={"session_id": teacher["session_id"]},
        auth_user="teacher1")
    assert response["status"] == 403
    assert payload["code"] == "coedu_forbidden"


def test_push_and_redpoint_keep_human_confirmation_boundaries():
    ctx = resolve()
    outbox_before = db.q("SELECT COUNT(*) AS n FROM wecom_outbox", one=True)["n"]
    response, payload = json_call(
        "POST", "/api/v1/push/run",
        body={"session_id": ctx["session_id"], "push_level": "L1"},
        auth_user="zhangmin")
    assert response["status"] == 200
    assert payload["data"]["status"] == "sent"
    assert payload["data"]["targets"]
    assert db.q("SELECT COUNT(*) AS n FROM wecom_outbox", one=True)["n"] > outbox_before

    outbox_before = db.q("SELECT COUNT(*) AS n FROM wecom_outbox", one=True)["n"]
    response, payload = json_call(
        "POST", "/api/v1/todo/note",
        body={"session_id": ctx["session_id"], "category": "家长告知"},
        auth_user="zhangmin")
    item_id = payload["data"]["todo_id"]
    assert "人工签发" in payload["data"]["rule"]
    assert db.q("SELECT COUNT(*) AS n FROM wecom_outbox", one=True)["n"] == outbox_before

    response, payload = json_call(
        "GET", "/api/v1/todo/list", query={"session_id": ctx["session_id"]},
        auth_user="zhangmin")
    assert item_id in {item["item_id"] for item in payload["data"]["items"]}

    response, payload = json_call(
        "POST", "/api/v1/todo/close",
        body={"session_id": ctx["session_id"], "item_id": item_id},
        auth_user="zhangmin")
    assert payload["data"]["status"] == "closed"
    response, payload = json_call(
        "GET", "/api/v1/todo/list", query={"session_id": ctx["session_id"]},
        auth_user="zhangmin")
    closed = next(item for item in payload["data"]["items"] if item["item_id"] == item_id)
    assert closed["status"] == "closed"
    assert payload["data"]["open_count"] == 0


def configure_wecom(monkeypatch):
    key = base64.b64encode(b"0" * 32).decode("ascii").rstrip("=")
    monkeypatch.setattr(config, "WECOM_TOKEN", "test-token")
    monkeypatch.setattr(config, "WECOM_ENCODING_AES_KEY", key)
    monkeypatch.setattr(config, "WECOM_CORP_ID", "corp-jszx")
    return key


def test_wecom_verify_and_encrypted_callback_roundtrip(monkeypatch):
    key = configure_wecom(monkeypatch)
    timestamp, nonce = "1700000000", "nonce"
    encrypted_echo = crypto.encrypt("echo-hello", key, config.WECOM_CORP_ID)
    signature = crypto.signature(config.WECOM_TOKEN, timestamp, nonce, encrypted_echo)
    response = call("GET", "/api/v1/wecom/callback", query={
        "msg_signature": signature, "timestamp": timestamp,
        "nonce": nonce, "echostr": encrypted_echo,
    })
    assert response["status"] == 200
    assert response["content_type"] == TEXT_CONTENT_TYPE
    assert response["body"] == "echo-hello"

    plain = ("<xml><ToUserName><![CDATA[corp-jszx]]></ToUserName>"
             "<FromUserName><![CDATA[zhangmin]]></FromUserName>"
             "<CreateTime>1700000000</CreateTime><MsgType><![CDATA[text]]></MsgType>"
             "<Content><![CDATA[你好]]></Content><AgentID><![CDATA[1]]></AgentID></xml>")
    encrypted = crypto.encrypt(plain, key, config.WECOM_CORP_ID)
    signature = crypto.signature(config.WECOM_TOKEN, timestamp, nonce, encrypted)
    raw = ("<xml><Encrypt><![CDATA[%s]]></Encrypt></xml>" % encrypted).encode("utf-8")
    response = call("POST", "/api/v1/wecom/callback", query={
        "msg_signature": signature, "timestamp": timestamp, "nonce": nonce,
    }, raw_body=raw)
    assert response["status"] == 200
    assert response["content_type"] == XML_CONTENT_TYPE
    root = ET.fromstring(response["body"])
    reply_plain, receive_id = crypto.decrypt(root.findtext("Encrypt"), key)
    assert receive_id == config.WECOM_CORP_ID
    assert "明细请打开德育工作台查看" in reply_plain
    assert "zhangmin" in reply_plain


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True


def test_redis_consume_correlation_response_prefix_and_ttl():
    fake = FakeRedis()
    request = {
        "request_id": "redis-contract-1",
        "method": "GET",
        "path": "/api/v1/health",
        "query": "",
        "body": None,
        "raw_body": "",
        "X-Auth-User": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    response = worker.consume_payload(
        fake, json.dumps(request), "custom:response:", 17)
    key = "custom:response:redis-contract-1"
    assert response["request_id"] == "redis-contract-1"
    assert json.loads(fake.values[key]) == response
    assert fake.ttls[key] == 17
    assert set(response) == RESPONSE_REQUIRED_FIELDS


def test_scheduler_invokes_all_legacy_due_handlers(monkeypatch):
    calls = []
    monkeypatch.setattr(push, "run_due", lambda now: calls.append(("push", now)) or [])
    monkeypatch.setattr(push, "weekly_due", lambda now: calls.append(("weekly", now)) or [])
    monkeypatch.setattr(push, "escalate_overdue", lambda now: calls.append(("dun", now)) or [])

    class StopAfterOnePass:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True
            return True

    worker.scheduler(StopAfterOnePass())
    assert [name for name, _now in calls] == ["push", "weekly", "dun"]


def test_route_function_is_byte_equivalent_to_archive():
    def route_source(path):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "route")
        return ast.get_source_segment(source, node)

    archived = ROOT / "班主任端" / "app" / "server.py"
    if not archived.is_file():
        pytest.skip("legacy 归档 班主任端/ 不在本仓库（已排除），跳过字节等价比对")
    migrated = ROOT / "tasks" / "interfaces" / "server.py"
    assert route_source(migrated) == route_source(archived)


def test_default_and_overridden_db_paths_do_not_touch_archive(tmp_path):
    archived_db = ROOT / "班主任端" / "data" / "dywork.db"
    before = (archived_db.exists(), archived_db.stat().st_mtime_ns if archived_db.exists() else None)
    override = tmp_path / "isolated" / "override.db"
    script = (
        "import json, os; "
        "from tasks.shared import db; "
        "db.init_db() if os.environ.get('INIT_DB') else None; "
        "print(json.dumps({'db_path': str(db.DB_PATH), 'exists': db.DB_PATH.is_file()}))"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("DB_PATH", None)
    default_run = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    default_result = json.loads(default_run.stdout.strip().splitlines()[-1])
    expected_default = ROOT / "tasks" / "runtime" / "dywork.db"
    assert Path(default_result["db_path"]) == expected_default
    assert default_result["exists"] is False

    env["DB_PATH"] = str(override)
    env["INIT_DB"] = "1"
    override_run = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env,
        check=True, capture_output=True, text=True, timeout=30)
    override_result = json.loads(override_run.stdout.strip().splitlines()[-1])
    assert Path(override_result["db_path"]) == override
    assert override.is_file()
    after = (archived_db.exists(), archived_db.stat().st_mtime_ns if archived_db.exists() else None)
    assert after == before
