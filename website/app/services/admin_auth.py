# -*- coding: utf-8 -*-
"""管理员服务端鉴权守卫。

核心原则（安全红线）：绝不信客户端传入的身份 / admin_id，只认签名会话 + admin_accounts。
- 生产（已配置登录）：仅认 htw_session 签名 Cookie → 查 admin_accounts → 校验 role/status。
- dev 旁路（未配置登录）：与现有 _user() 一致，允许 X-Auth-User 请求头命中 admin_accounts。
"""

from fastapi import Request

from app.services import wecom_oauth
from tasks.modules.leader import admins


def current_admin(request: Request):
    """返回已认证管理员 userid；未通过返回 None。"""
    token = request.cookies.get(wecom_oauth.SESSION_COOKIE, "")
    userid = wecom_oauth.read_session(token)
    if userid and admins.is_active_admin(userid):
        return userid
    # dev 旁路：未启用登录时，允许请求头携带身份（与 _user() 约定一致）
    if not wecom_oauth.auth_required():
        header_user = request.headers.get("X-Auth-User", "")
        if header_user and admins.is_active_admin(header_user):
            return header_user
    return None


def has_any_session(request: Request):
    """是否存在任意有效身份（用于区分 401 未登录 vs 403 无权限）。"""
    token = request.cookies.get(wecom_oauth.SESSION_COOKIE, "")
    if wecom_oauth.read_session(token):
        return True
    if not wecom_oauth.auth_required():
        return bool(request.headers.get("X-Auth-User", ""))
    return False
