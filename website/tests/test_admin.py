# -*- coding: utf-8 -*-
"""后台管理台端到端测试（AC-1 ~ AC-8, AC-12, TR-3.5）。

每个用例使用隔离的临时 SQLite 库：monkeypatch db.DB_PATH 后通过
`with TestClient(app)` 触发 lifespan 建表与播种（admin/abcd1230）。
"""
import hashlib
import io
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
from tasks.modules.leader import admins
from tasks.shared import db
from tasks.modules.head_teacher import roster  # noqa: E402

ADMIN_USER = "admin"
ADMIN_PWD = "abcd1230"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离临时库 + 启用登录（auth_required=True）。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "admin_test.db")
    monkeypatch.setattr(g.config, "AUTH_COOKIE_SECRET", "admin-test-secret")
    # 一个不与 admin 冲突的占位本地账号，仅用于让 auth_required() 为真
    dummy = hashlib.sha256(b"dummy").hexdigest()
    monkeypatch.setattr(g.config, "LOCAL_LOGIN_USERS", f"__test_dummy__:{dummy}")
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(client):
    """已登录 admin 的客户端。"""
    r = client.post("/api/v1/login", json={"username": ADMIN_USER, "password": ADMIN_PWD})
    assert r.status_code == 200, r.text
    return client


def _set_cookie(client, userid):
    token = wecom_oauth.sign_session(userid)
    client.cookies.set(wecom_oauth.SESSION_COOKIE, token)


# ----------------------------------------------------------------- AC-1
def test_admin_login_enters_console(client):
    r = client.post("/api/v1/login", json={"username": ADMIN_USER, "password": ADMIN_PWD})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["next"] == "/api/admin"
    assert wecom_oauth.SESSION_COOKIE in r.headers.get("set-cookie", "")

    # 带会话访问 / → 跳转管理台
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["location"] == "/api/admin"

    # /api/admin 页面可访问
    page = client.get("/api/admin")
    assert page.status_code == 200
    assert "学校管理后台" in page.text
    assert "/static/admin/app.css" in page.text
    assert "/static/admin/app.js" in page.text


def test_admin_login_wrong_password(client):
    r = client.post("/api/v1/login", json={"username": ADMIN_USER, "password": "wrong"})
    assert r.status_code == 401


# ----------------------------------------------------------------- AC-2
def test_no_cookie_returns_401(client):
    for path in ("/api/v1/admin/me", "/api/v1/admin/students", "/api/v1/admin/dashboard"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["code"] == 401


# ----------------------------------------------------------------- AC-3
def test_non_admin_session_returns_403(client):
    _set_cookie(client, "teacher_not_admin")  # 不在 admin_accounts
    r = client.get("/api/v1/admin/students")
    assert r.status_code == 403
    assert r.json()["code"] == 403


# ----------------------------------------------------------------- AC-4
def test_student_crud_transfer_and_new_fields(admin_client):
    c = admin_client
    # 准备两个班级
    for cid in ("9107", "9108"):
        r = c.post("/api/v1/admin/classes", json={"class_id": cid, "name": f"{cid}班"})
        assert r.status_code == 200, r.text

    # 新增学生（含新字段）
    r = c.post("/api/v1/admin/students", json={
        "class_id": "9107", "student_id": "S9001", "name": "测试生",
        "gender": "男", "dorm": "1401", "address": "京山市测试路1号",
        "phone": "13900000001", "guardian_phone": "13800000001", "status": "在读",
    })
    assert r.status_code == 200, r.text

    # 跨班列表可见 + 字段持久化
    lst = c.get("/api/v1/admin/students?q=S9001").json()["data"]["items"]
    assert len(lst) == 1
    s = lst[0]
    assert s["class_id"] == "9107" and s["name"] == "测试生"
    assert s["dorm"] == "1401" and s["address"] == "京山市测试路1号"
    assert s["phone"] == "13900000001" and s["guardian_phone"] == "13800000001"

    # 调班到 9108
    r = c.put("/api/v1/admin/students/9107/S9001", json={
        "class_id": "9108", "name": "测试生", "student_id": "S9001",
    })
    assert r.status_code == 200, r.text
    assert c.get("/api/v1/admin/students?class_id=9108").json()["data"]["total"] >= 1
    in_old = c.get("/api/v1/admin/students?class_id=9107&q=S9001").json()["data"]["items"]
    assert not any(x["student_id"] == "S9001" for x in in_old)

    # 删除
    r = c.delete("/api/v1/admin/students/9108/S9001")
    assert r.status_code == 200, r.text
    assert c.get("/api/v1/admin/students?q=S9001").json()["data"]["total"] == 0


def test_duplicate_student_key_rejected(admin_client):
    c = admin_client
    c.post("/api/v1/admin/classes", json={"class_id": "2701", "name": "2701班"})
    c.post("/api/v1/admin/students", json={"class_id": "2701", "student_id": "S1", "name": "甲"})
    r = c.post("/api/v1/admin/students", json={"class_id": "2701", "student_id": "S1", "name": "乙"})
    assert r.status_code == 400


# ----------------------------------------------------------------- AC-5
def test_class_delete_blocked_when_referenced(admin_client):
    c = admin_client
    c.post("/api/v1/admin/classes", json={"class_id": "3001", "name": "3001班"})
    c.post("/api/v1/admin/students", json={"class_id": "3001", "student_id": "S2", "name": "丙"})
    r = c.delete("/api/v1/admin/classes/3001")
    assert r.status_code == 400
    # 学生数据未被破坏
    assert c.get("/api/v1/admin/students?class_id=3001").json()["data"]["total"] == 1
    # 先删学生再删班级成功
    c.delete("/api/v1/admin/students/3001/S2")
    assert c.delete("/api/v1/admin/classes/3001").status_code == 200


def test_dorm_delete_blocked_when_occupied(admin_client):
    c = admin_client
    c.post("/api/v1/admin/classes", json={"class_id": "3002", "name": "3002班"})
    r = c.post("/api/v1/admin/dorms", json={"building": "1号楼", "room_no": "9901", "gender": "男", "capacity": 6})
    assert r.status_code == 200, r.text
    c.post("/api/v1/admin/students", json={"class_id": "3002", "student_id": "S3", "name": "丁", "dorm": "9901"})
    did = r.json()["data"]["id"]
    blocked = c.delete(f"/api/v1/admin/dorms/{did}")
    assert blocked.status_code == 400
    # 取消入住后可删
    c.put("/api/v1/admin/students/3002/S3", json={"dorm": ""})
    assert c.delete(f"/api/v1/admin/dorms/{did}").status_code == 200


# ----------------------------------------------------------------- AC-6
def test_teacher_reset_password_then_login(client):
    """重置教师密码后，可用默认口令登录。"""
    # admin 登录创建教师
    admin = client
    r = admin.post("/api/v1/login", json={"username": ADMIN_USER, "password": ADMIN_PWD})
    assert r.status_code == 200
    r = admin.post("/api/v1/admin/accounts/teachers", json={
        "userid": "JS9001", "name": "测试教师", "password": "InitPwd99",
        "dept": "教务处", "category": "教师", "status": "本校",
    })
    assert r.status_code == 200, r.text
    r = admin.post("/api/v1/admin/accounts/teachers/JS9001/reset-password")
    assert r.status_code == 200
    assert r.json()["data"]["password"] == "123456"

    # 用默认口令登录（清除已有 cookie）
    client.cookies.clear()
    ok = client.post("/api/v1/login", json={"username": "JS9001", "password": "123456"})
    assert ok.status_code == 200
    # 旧密码失效
    client.cookies.clear()
    bad = client.post("/api/v1/login", json={"username": "JS9001", "password": "InitPwd99"})
    assert bad.status_code == 401


def test_change_own_password_requires_correct_old(admin_client):
    c = admin_client
    # 旧密码错误 → 400
    r = c.post("/api/v1/admin/password/change", json={"old_password": "wrong", "new_password": "NewPass1"})
    assert r.status_code == 400
    # 正确修改
    r = c.post("/api/v1/admin/password/change", json={"old_password": ADMIN_PWD, "new_password": "NewPass1"})
    assert r.status_code == 200, r.text
    # 旧密码失效
    c.cookies.clear()
    assert c.post("/api/v1/login", json={"username": ADMIN_USER, "password": ADMIN_PWD}).status_code == 401
    # 新密码生效
    assert c.post("/api/v1/login", json={"username": ADMIN_USER, "password": "NewPass1"}).status_code == 200


def test_self_lock_guards_reject(admin_client):
    """模型层防自锁：不能停用/删除自己，不能删光最后一个 superadmin。"""
    # 停用自己
    with pytest.raises(ValueError):
        admins.set_status("admin", "disabled", operator_userid="admin")
    # 删除自己
    with pytest.raises(ValueError):
        admins.delete("admin", operator_userid="admin")
    # 当前仅 1 个 active superadmin → 不能把它降级
    with pytest.raises(ValueError):
        admins.update("admin", role="admin")
    # 新增第二个 superadmin 后，删除其中一个可行
    admins.create("admin2", "二管", "Another1", role="superadmin")
    assert admins.count_active_superadmin() == 2
    admins.delete("admin2", operator_userid="admin")
    assert admins.count_active_superadmin() == 1
    # 仅剩一个时再停用该 superadmin 被拒
    with pytest.raises(ValueError):
        admins.set_status("admin", "disabled", operator_userid="admin2")


def test_student_account_generate_and_reset(admin_client):
    c = admin_client
    c.post("/api/v1/admin/classes", json={"class_id": "3003", "name": "3003班"})
    c.post("/api/v1/admin/students", json={"class_id": "3003", "student_id": "SA1", "name": "学生甲"})
    c.post("/api/v1/admin/students", json={"class_id": "3003", "student_id": "SA2", "name": "学生乙"})
    r = c.post("/api/v1/admin/accounts/students/generate", json={"class_id": "3003"})
    assert r.status_code == 200
    assert r.json()["data"]["generated"] == 2
    # 重复生成跳过
    r2 = c.post("/api/v1/admin/accounts/students/generate", json={"class_id": "3003"})
    assert r2.json()["data"]["generated"] == 0
    # 列表可见
    lst = c.get("/api/v1/admin/accounts/students?class_id=3003").json()["data"]
    assert lst["total"] == 2
    # 重置密码
    r = c.post("/api/v1/admin/accounts/students/reset-password",
               json={"class_id": "3003", "student_id": "SA1"})
    assert r.status_code == 200 and r.json()["data"]["password"] == "123456"
    # 停用
    r = c.post("/api/v1/admin/accounts/students/3003/SA1/toggle-status", json={"status": "disabled"})
    assert r.status_code == 200
    item = c.get("/api/v1/admin/accounts/students?class_id=3003&q=SA1").json()["data"]["items"][0]
    assert item["status"] == "disabled"
    # 列表不返回密码摘要
    assert "password_sha256" not in item


# ----------------------------------------------------------------- AC-7
def _build_students_xlsx(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "学生名册"
    headers = ["班级", "学号", "姓名", "性别", "寝室", "家庭住址", "学生电话", "监护人电话", "状态"]
    ws.append(headers)
    for row in rows:
        ws.append(row)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def test_import_export_students_new_columns(admin_client):
    c = admin_client
    c.post("/api/v1/admin/classes", json={"class_id": "4001", "name": "4001班"})
    bio = _build_students_xlsx([
        ["4001", "SX1", "导入甲", "男", "1401", "导入地址A", "13700000001", "13600000001", "在读"],
        ["4001", "SX2", "导入乙", "女", "2401", "导入地址B", "13700000002", "13600000002", "在读"],
    ])
    r = c.post("/api/v1/admin/students/import",
               files={"file": ("students.xlsx", bio,
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["added"] == 2 and data["updated"] == 0

    # 重复导入 → updated
    bio2 = _build_students_xlsx([["4001", "SX1", "导入甲(改)", "男", "1401", "新地址", "", "", "在读"]])
    r2 = c.post("/api/v1/admin/students/import",
                files={"file": ("s.xlsx", bio2,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r2.json()["data"]["updated"] == 1 and r2.json()["data"]["added"] == 0

    # 导出表头含新列
    resp = c.get("/api/v1/admin/students/export")
    assert resp.status_code == 200
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(resp.content))
    ws = wb.active
    headers = [str(c.value) for c in ws[1]]
    for col in ("寝室", "家庭住址", "学生电话"):
        assert col in headers, headers
    # 数据行包含导入内容
    rows = list(ws.iter_rows(values_only=True))
    flat = " ".join(str(v) for row in rows for v in row if v)
    assert "导入甲" in flat and "1401" in flat


# ----------------------------------------------------------------- AC-8
def test_audit_records_writes_without_plaintext_password(admin_client):
    c = admin_client
    c.post("/api/v1/admin/accounts/teachers", json={
        "userid": "JS9002", "name": "审计教师", "password": "AuditPwd99", "category": "教师"})
    c.post("/api/v1/admin/accounts/teachers/JS9002/reset-password")
    c.post("/api/v1/admin/password/change", json={"old_password": ADMIN_PWD, "new_password": "AuditNew1"})
    rows = c.get("/api/v1/admin/audit?limit=200").json()["data"]
    actions = {r["action"] for r in rows}
    assert "teacher:upsert" in actions
    assert "teacher:reset_password" in actions
    assert "admin:change_password" in actions
    # detail 不得泄露明文密码
    blob = " ".join(str(r.get("detail") or "") for r in rows)
    for secret in ("AuditPwd99", "123456", ADMIN_PWD, "AuditNew1"):
        assert secret not in blob, f"明文密码泄露到审计: {secret}"


def test_dashboard_kpi_and_me(admin_client):
    c = admin_client
    me = c.get("/api/v1/admin/me").json()["data"]
    assert me["userid"] == "admin" and me["role"] == "superadmin"
    dash = c.get("/api/v1/admin/dashboard").json()["data"]
    kpi = dash["kpi"]
    for key in ("teachers", "students", "classes", "dorms", "admins", "student_accounts"):
        assert key in kpi
    assert kpi["admins"] >= 1
    assert isinstance(dash["recent_audit"], list)


def test_admin_page_redirects_when_unauthenticated(client):
    # 未登录且启用登录 → 跳登录页
    r = client.get("/api/admin", follow_redirects=False)
    assert r.status_code == 302
    assert "/api/v1/login" in r.headers["location"]
    assert "next=/api/admin" in r.headers["location"]


def test_admin_page_rejects_non_admin_session(client):
    # 已登录但非管理员 → 不放行管理台骨架，回工作台
    _set_cookie(client, "just_a_teacher")
    r = client.get("/api/admin", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "/api/head_teacher_workbench"
