# -*- coding: utf-8 -*-
"""政教处角色服务端鉴权守卫。

核心原则与 admin_auth 一致：绝不信客户端传入的身份，只认签名会话 + school_accounts。
- 生产（已配置登录）：仅认 htw_session 签名 Cookie → 查 school_accounts，
  要求 category == '政教处' 且账号启用。
- 管理员放行：active 管理员也可进入政教处工作台用于运维。
- dev 旁路（未配置登录）：允许 X-Auth-User 请求头命中上述条件。
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services import wecom_oauth
from tasks.domain.identity import accounts as school_accounts
from tasks.modules.leader import admins

DEYU_CATEGORY = "政教处"
# 现有数据中启用状态写作「本校」，停用写作「停用」；按实际取值判断，不写死 active。
_DISABLED_STATUS = {"停用", "disabled", "inactive"}


def _status_enabled(status) -> bool:
    return str(status or "").strip() not in _DISABLED_STATUS


def is_deyu_account(userid) -> bool:
    """该 userid 是否为启用中的政教处账号（仅看 school_accounts）。"""
    try:
        record = school_accounts.get(userid)
    except Exception:
        return False
    if not record or record.get("category") != DEYU_CATEGORY:
        return False
    return _status_enabled(record.get("status"))


def _allowed(userid) -> bool:
    """政教处账号或 active 管理员均可进入。"""
    if not userid:
        return False
    return is_deyu_account(userid) or admins.is_active_admin(userid)


def current_deyu(request: Request):
    """返回已认证政教处（或管理员）userid；未通过返回 None。"""
    token = request.cookies.get(wecom_oauth.SESSION_COOKIE, "")
    userid = wecom_oauth.read_session(token)
    if userid and _allowed(userid):
        return userid
    # dev 旁路：未启用登录时，允许请求头携带身份
    if not wecom_oauth.auth_required():
        header_user = request.headers.get("X-Auth-User", "")
        if header_user and _allowed(header_user):
            return header_user
    return None


def has_any_session(request: Request) -> bool:
    """是否存在任意有效身份（用于区分 401 未登录 vs 403 无权限）。"""
    token = request.cookies.get(wecom_oauth.SESSION_COOKIE, "")
    if wecom_oauth.read_session(token):
        return True
    if not wecom_oauth.auth_required():
        return bool(request.headers.get("X-Auth-User", ""))
    return False


def deyu_forbidden():
    return JSONResponse({"code": 403, "message": "无政教处权限"}, status_code=403)


def deyu_or_401(request: Request):
    """返回 (userid, None) 或 (None, error_response)，供接口守卫直接使用。"""
    userid = current_deyu(request)
    if userid:
        return userid, None
    if has_any_session(request):
        return None, deyu_forbidden()
    return None, JSONResponse(
        {"code": 401, "message": "未登录或登录已过期"}, status_code=401,
    )
