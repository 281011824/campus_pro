# -*- coding: utf-8 -*-
"""学生 / 家长角色服务端鉴权守卫（学号即账号）。

原则与 deyu_auth 一致：绝不信任前端传入的身份，只认签名会话。
- 学号解析：先 students.student_no（政教处编排的正式学号），再 students.student_id；
  命中必须唯一，跨班重名（如 S001）一律不认，避免串号。
- 密码：优先 student_accounts.password_sha256；无账号记录时回落到 sha256(学号)，
  即「初始密码=学号」，学生首次登录无需管理员先建账。
- 家长：独立 Cookie htw_parent，HMAC 同密钥，载荷 role=parent / binding_id /
  class_id / student_id / exp；每次请求都回查绑定是否仍有效。
"""

import base64
import hashlib
import hmac
import json
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from app.initializer import g
from app.services import wecom_oauth
from tasks.shared import db
from tasks.modules.student import (student_accounts, student_portal)

_DISABLED = {"停用", "disabled", "inactive"}
PARENT_COOKIE = "htw_parent"
PARENT_TTL_SECONDS = 8 * 3600


def _enabled(status) -> bool:
    return str(status or "").strip() not in _DISABLED


def find_student(account) -> dict | None:
    """按学号解析学生；命中多行（跨班同学号）视为无效。"""
    acc = str(account or "").strip()
    if not acc:
        return None
    try:
        rows = db.q(
            "SELECT class_id, student_id, student_no, name, major, grade, status "
            "FROM students WHERE student_no=? OR student_id=? LIMIT 2",
            (acc, acc),
        )
    except Exception:
        return None
    if len(rows) != 1:
        return None
    return dict(rows[0])


def is_student_account(account) -> bool:
    return find_student(account) is not None


def expected_digest(account) -> str | None:
    """返回该学号应匹配的密码摘要；非学生账号返回 None（防止任意账号以用户名当密码登录）。"""
    stu = find_student(account)
    if not stu or not _enabled(stu.get("status")):
        return None
    record = student_accounts.get(stu["class_id"], stu["student_id"])
    if record:
        if not _enabled(record.get("status")):
            return None
        digest = record.get("password_sha256")
        if digest:
            return digest
    return student_accounts.sha256_hex(str(account).strip())


def current_student(request: Request) -> dict | None:
    userid = wecom_oauth.read_session(request.cookies.get(wecom_oauth.SESSION_COOKIE, ""))
    if not userid:
        return None
    return find_student(userid)


def has_any_session(request: Request) -> bool:
    if wecom_oauth.read_session(request.cookies.get(wecom_oauth.SESSION_COOKIE, "")):
        return True
    if not wecom_oauth.auth_required():
        return bool(request.headers.get("X-Auth-User", ""))
    return False


def student_or_error(request: Request):
    """返回 (student, None) 或 (None, error_response)。"""
    stu = current_student(request)
    if stu:
        return stu, None
    if has_any_session(request):
        return None, JSONResponse(
            {"code": 403, "message": "仅学生本人可访问"}, status_code=403,
        )
    return None, JSONResponse(
        {"code": 401, "message": "未登录或登录已过期"}, status_code=401,
    )


# ---------------------------------------------------------------- 家长会话
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _parent_secret() -> bytes:
    return str(g.config.AUTH_COOKIE_SECRET or "").encode("utf-8")


def sign_parent_session(binding, ttl: int = PARENT_TTL_SECONDS) -> str:
    """家长会话票据：role=parent + 绑定三元 + 过期时间，HMAC 签名。"""
    payload = json.dumps({
        "role": "parent",
        "binding_id": str(binding["id"]),
        "class_id": str(binding["class_id"]),
        "student_id": str(binding["student_id"]),
        "exp": int(time.time()) + ttl,
    }, separators=(",", ":")).encode("utf-8")
    body = _b64(payload)
    sig = _b64(hmac.new(_parent_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return "%s.%s" % (body, sig)


def read_parent_session(token: str) -> dict | None:
    """返回家长载荷；签名错误、格式错误、过期或角色不符返回 None。"""
    if not token or "." not in token or not _parent_secret():
        return None
    body, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(_parent_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("role") != "parent" or int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


def current_parent(request: Request) -> dict | None:
    """校验家长会话并回查绑定是否仍有效；撤回/越权返回 None。"""
    payload = read_parent_session(request.cookies.get(PARENT_COOKIE, ""))
    if not payload:
        return None
    try:
        binding = student_portal.get_binding(payload.get("binding_id"))
    except Exception:
        return None
    if not binding:
        return None
    if (str(binding["class_id"]) != str(payload.get("class_id"))
            or str(binding["student_id"]) != str(payload.get("student_id"))):
        return None
    return binding


def parent_or_error(request: Request):
    """返回 (binding, None) 或 (None, error_response)。

    按口径：未绑定家长身份或越权访问一律 403，并写审计。
    """
    payload = read_parent_session(request.cookies.get(PARENT_COOKIE, ""))
    if not payload:
        try:
            db.audit(None, "parent.forbidden", "denied", "family", "未绑定家长身份")
        except Exception:
            pass
        return None, JSONResponse(
            {"code": 403, "message": "未绑定家长身份或授权已失效"}, status_code=403,
        )
    binding = current_parent(request)
    if not binding:
        try:
            db.audit({"user_id": "parent:%s" % payload.get("binding_id"),
                      "post_id": "-", "agent_id": "-", "level": "parent"},
                     "parent.forbidden", "denied", "family",
                     "绑定已撤回或越权访问")
        except Exception:
            pass
        return None, JSONResponse(
            {"code": 403, "message": "未绑定该学生或授权已撤回"}, status_code=403,
        )
    return binding, None
