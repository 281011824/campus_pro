# -*- coding: utf-8 -*-
"""教官 / 寝管角色服务端鉴权守卫。

核心原则与 deyu_auth / admin_auth 一致：绝不信客户端传入的身份，
只认签名会话 + school_accounts。
- 生产（已配置登录）：仅认 htw_session 签名 Cookie → 查 school_accounts，
  要求 category ∈ {'教官', '寝管'} 且账号启用。
- 管理员放行：active 管理员也可进入巡查模块用于运维。
- dev 旁路（未配置登录）：允许 X-Auth-User 请求头命中上述条件。
- 作废端点额外放行政教处（只允许作废，不进入模块其余接口）。
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services import deyu_auth, wecom_oauth
from tasks.domain.identity import accounts as school_accounts
from tasks.modules.leader import admins

INSPECTOR_CATEGORIES = {"教官", "寝管", "教官寝管"}
# 现有数据中启用状态写作「本校」，停用写作「停用」；按实际取值判断，不写死 active。
_DISABLED_STATUS = {"停用", "disabled", "inactive"}


def _status_enabled(status) -> bool:
    return str(status or "").strip() not in _DISABLED_STATUS


def is_inspector_account(userid) -> bool:
    """该 userid 是否为启用中的教官 / 寝管账号（仅看 school_accounts）。

    兼容学校现有导入数据里的合并类别「教官寝管」。
    """
    try:
        record = school_accounts.get(userid)
    except Exception:
        return False
    if not record:
        return False
    category = str(record.get("category") or "").strip()
    if category not in INSPECTOR_CATEGORIES:
        return False
    return _status_enabled(record.get("status"))


def _allowed(userid) -> bool:
    """教官 / 寝管账号或 active 管理员均可进入。"""
    if not userid:
        return False
    return is_inspector_account(userid) or admins.is_active_admin(userid)


def _session_user(request: Request) -> str:
    """签名会话 userid；未启用登录时退回 X-Auth-User 旁路。"""
    token = request.cookies.get(wecom_oauth.SESSION_COOKIE, "")
    userid = wecom_oauth.read_session(token)
    if userid:
        return userid
    if not wecom_oauth.auth_required():
        return str(request.headers.get("X-Auth-User", "") or "")
    return ""


def _category_of(userid) -> str:
    """账号类别；管理员统一记为「管理员」。"""
    if admins.is_active_admin(userid):
        return "管理员"
    try:
        record = school_accounts.get(userid) or {}
    except Exception:
        return ""
    return str(record.get("category") or "")


def current_inspector(request: Request):
    """返回已认证教官 / 寝管（或管理员）userid；未通过返回 None。"""
    userid = _session_user(request)
    if userid and _allowed(userid):
        return userid
    return None


def has_any_session(request: Request) -> bool:
    """是否存在任意有效身份（用于区分 401 未登录 vs 403 无权限）。"""
    if wecom_oauth.read_session(request.cookies.get(wecom_oauth.SESSION_COOKIE, "")):
        return True
    if not wecom_oauth.auth_required():
        return bool(request.headers.get("X-Auth-User", ""))
    return False


def inspector_forbidden():
    return JSONResponse({"code": 403, "message": "无巡查权限"}, status_code=403)


def inspector_or_401(request: Request):
    """返回 (userid, category, None) 或 (None, None, error_response)。"""
    userid = current_inspector(request)
    if userid:
        return userid, _category_of(userid), None
    if has_any_session(request):
        return None, None, inspector_forbidden()
    return None, None, JSONResponse(
        {"code": 401, "message": "未登录或登录已过期"}, status_code=401,
    )


def void_allowed(request: Request):
    """作废端点专用：返回 (userid, category, is_admin, is_deyu)。

    政教处允许作废任意记录，但不因此获得巡查模块其余接口权限；
    未认证或无任何相关角色时返回 (None, None, False, False)。
    """
    userid = _session_user(request)
    if not userid:
        return None, None, False, False
    if admins.is_active_admin(userid):
        return userid, "管理员", True, False
    if deyu_auth.is_deyu_account(userid):
        return userid, "政教处", False, True
    if is_inspector_account(userid):
        return userid, _category_of(userid), False, False
    return None, None, False, False
