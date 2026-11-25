import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.interfaces.contract import (API_ROUTES, DYNAMIC_ROUTES, FIXED_ROUTES, GROWTH_LEAVES, NORMAL_ROUTES, PREFIX_GUARDS, SOURCE_DISPATCH_BRANCHES, SOURCE_DYNAMIC_DISPATCHES, SOURCE_FIXED_DISPATCHES, SOURCE_PREFIX_GUARDS, SOURCE_ROUTE_BRANCHES, WECOM_ROUTES)

LEGACY_ROOT = ROOT / "班主任端"
SERVER_PATH = LEGACY_ROOT / "app" / "server.py"
if not SERVER_PATH.is_file():
    pytest.skip(
        "legacy 归档 班主任端/ 不在本仓库（已排除），跳过路由基线比对",
        allow_module_level=True,
    )
SERVER_SOURCE = SERVER_PATH.read_text(encoding="utf-8")
ROUTE_FUNCTION = next(
    node for node in ast.parse(SERVER_SOURCE).body
    if isinstance(node, ast.FunctionDef) and node.name == "route"
)


def _fixed_source_routes():
    routes = set()
    for node in ast.walk(ROUTE_FUNCTION):
        if not isinstance(node, ast.If) or "path ==" not in ast.unparse(node.test):
            continue
        if "method ==" not in ast.unparse(node.test):
            continue
        strings = [
            item.value for item in ast.walk(node.test)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        path = next(value for value in strings if value.startswith("/api/"))
        method = next(value for value in strings if value in {"GET", "POST"})
        routes.add((method, path))
    return routes


def _growth_source_leaves():
    for node in ast.walk(ROUTE_FUNCTION):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "table" for target in node.targets):
            continue
        return tuple(key.value for key in node.value.keys)
    raise AssertionError("未找到 growth 动态分派表")


def test_source_branch_accounting_explains_65():
    assert len(FIXED_ROUTES) == SOURCE_FIXED_DISPATCHES == 60
    assert len(DYNAMIC_ROUTES) == 10
    assert SOURCE_DYNAMIC_DISPATCHES == 2
    assert len(PREFIX_GUARDS) == SOURCE_PREFIX_GUARDS == 3
    assert SOURCE_FIXED_DISPATCHES + SOURCE_DYNAMIC_DISPATCHES == SOURCE_DISPATCH_BRANCHES == 62
    assert SOURCE_DISPATCH_BRANCHES + SOURCE_PREFIX_GUARDS == SOURCE_ROUTE_BRANCHES == 65
    assert len(NORMAL_ROUTES) == 70
    assert len(API_ROUTES) == 72
    assert len({route.key for route in API_ROUTES}) == 72


def test_growth_dynamic_dispatch_matches_nine_leaves():
    assert _growth_source_leaves() == GROWTH_LEAVES


@pytest.mark.parametrize(
    "route",
    API_ROUTES,
    ids=[f"{route.method} {route.path}" for route in API_ROUTES],
)
def test_every_target_route_has_archived_source_evidence(route):
    if route in FIXED_ROUTES:
        assert route.key in _fixed_source_routes()
    elif route.path == "/api/v1/session/{session_id}":
        assert 'path.startswith("/api/v1/session/") and method == "GET"' in SERVER_SOURCE
    elif route.path.startswith("/api/v1/growth/"):
        assert route.path.rsplit("/", 1)[-1] in _growth_source_leaves()
        assert 'path.startswith("/api/v1/growth/") and method == "GET"' in SERVER_SOURCE
    else:
        assert route in WECOM_ROUTES
        assert "do_GET" in SERVER_SOURCE and "do_POST" in SERVER_SOURCE
        assert "/api/v1/wecom/callback" in SERVER_SOURCE


def test_http_envelope_identity_and_wecom_semantics_are_locked():
    assert "self._json(200, ok(result))" in SERVER_SOURCE
    assert '{"code": e.code, "error": e.message, "data": None}' in SERVER_SOURCE
    assert '_TRUSTED_IDENTITY = (self.headers.get("X-Auth-User") or "").strip()' in SERVER_SOURCE
    assert '403, "identity_mismatch"' in SERVER_SOURCE
    assert '"text/plain; charset=utf-8"' in SERVER_SOURCE
    assert '"text/xml; charset=utf-8"' in SERVER_SOURCE
    assert {route.response_kind for route in WECOM_ROUTES} == {"wecom_verify", "wecom_callback"}


def test_all_archived_sha256_entries_match():
    lines = (ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    mismatches = []
    for line in lines:
        expected, relative = line.split("  ", 1)
        path = ROOT / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            mismatches.append(relative)
    assert mismatches == []


@pytest.mark.parametrize(
    ("filename", "class_id", "size"),
    [("fixtures.json", "2611", 50), ("fixtures_2607.json", "2607", 66)],
)
def test_fixtures_keep_counts_whitelist_and_degradation(filename, class_id, size):
    fixture = json.loads((LEGACY_ROOT / "data" / filename).read_text(encoding="utf-8"))
    assert fixture["_meta"]["class"] == class_id
    assert fixture["class"]["class_id"] == class_id
    assert fixture["class"]["size"] == size
    assert len(fixture["students"]) == size
    whitelist = set(fixture["_meta"]["field_whitelist"])
    forbidden = set(fixture["_meta"]["absent_fields"])
    for student in fixture["students"]:
        assert set(student) <= whitelist
        assert not set(student) & forbidden
    if class_id == "2607":
        assert fixture["class"]["attendance_rate"] is None
        assert fixture["class"]["moral_delta"] is None
        assert set(fixture["_meta"]["coverage_pending"]) == {"成绩", "考勤", "德育", "心理"}
        assert fixture["_meta"]["derived_pending"] is True
    else:
        assert fixture["dorm"]["today_ready"] is False


def test_historical_report_counters_remain_baseline_only():
    headteacher = json.loads((ROOT / "headteacher_test_report.json").read_text(encoding="utf-8"))
    pilot = json.loads((ROOT / "2607_pilot_report.json").read_text(encoding="utf-8"))
    integration = json.loads((ROOT / "integration_report.json").read_text(encoding="utf-8"))
    bench = json.loads((ROOT / "bench_report.json").read_text(encoding="utf-8"))
    assert headteacher["instance"] == "http://127.0.0.1:8124"
    assert headteacher["versions"]["selftest"] == "95 tests OK（独立临时库）"
    assert (headteacher["pass"], headteacher["fail"]) == (84, 0)
    assert (pilot["pass"], pilot["fail"]) == (41, 0)
    assert (integration["pass"], integration["fail"]) == (55, 0)
    assert (bench["total_requests"], bench["total_fail"]) == (9628, 0)


def test_legacy_db_and_identity_checks_use_isolated_temp_db(tmp_path):
    target = tmp_path / "isolated" / "head_teacher_workbench.db"
    archived_before = {
        path: (path.exists(), path.stat().st_mtime_ns if path.exists() else None)
        for path in (LEGACY_ROOT / "data").glob("*.db*")
    }
    script = r'''
import json
import os
from pathlib import Path
from app import db, org, server

db.init_db()
org.sync_directory()
assert db.DB_PATH == Path(os.environ["DB_PATH"])
ctx, error = org.resolve("zhangmin")
assert error is None
server._TRUSTED_IDENTITY = " zhangmin ".strip()
assert server.full_ctx(ctx["session_id"])["user_id"] == "zhangmin"
server._TRUSTED_IDENTITY = "someone_else"
try:
    server.full_ctx(ctx["session_id"])
except server.ApiError as exc:
    identity_error = [exc.status, exc.code]
else:
    raise AssertionError("identity mismatch was not rejected")
try:
    server.route("GET", "/api/v1/not-found", {}, {})
except server.ApiError as exc:
    not_found = [exc.status, exc.code]
else:
    raise AssertionError("unknown route was not rejected")
try:
    server.need_ctx({"session_id": ctx["session_id"], "level": "L6"})
except server.ApiError as exc:
    forged = [exc.status, exc.code]
else:
    raise AssertionError("forged level was not rejected")
print(json.dumps({
    "db_path": str(db.DB_PATH),
    "org_posts": len(db.q("SELECT post_id FROM org_posts")),
    "ok": server.ok({"value": 1}),
    "identity_error": identity_error,
    "not_found": not_found,
    "forged": forged,
}, ensure_ascii=False))
'''
    env = os.environ.copy()
    env.update({
        "DB_PATH": str(target),
        "WECOM_MODE": "mock",
        "GROWTH_NAV_MODE": "fixture",
        "TOKEN_SCOPE": "role_class",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(LEGACY_ROOT),
    })
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["db_path"] == str(target)
    assert target.is_file()
    assert result["org_posts"] > 0
    assert result["ok"] == {"code": 0, "data": {"value": 1}}
    assert result["identity_error"] == [403, "identity_mismatch"]
    assert result["not_found"] == [404, "not_found"]
    assert result["forged"] == [400, "forbidden_fields"]
    archived_after = {
        path: (path.exists(), path.stat().st_mtime_ns if path.exists() else None)
        for path in (LEGACY_ROOT / "data").glob("*.db*")
    }
    assert archived_after == archived_before
