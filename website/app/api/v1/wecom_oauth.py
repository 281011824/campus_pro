"""企业微信 OAuth2 登录入口。默认关闭，关闭时所有接口返回 503。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.services import wecom_oauth as oauth

router = APIRouter()
_prefix = ""  # 复用 api/v1 的 /api/v1 前缀


def _disabled():
    return JSONResponse(
        {
            "code": "wecom_oauth_disabled",
            "error": "企业微信 OAuth 未启用或凭据不完整",
            "data": None,
        },
        status_code=503,
    )


@router.get("/auth/wecom/login")
async def login():
    if not oauth.is_enabled():
        return _disabled()
    state = oauth.new_state()
    response = RedirectResponse(oauth.authorize_url(state), status_code=302)
    response.set_cookie(
        oauth.STATE_COOKIE, state,
        max_age=600, httponly=True, samesite="lax",
    )
    return response


def role_home(userid: str) -> str:
    """按账号角色返回登录后首页，供 OAuth 回调与登录接口共用同一口径。"""
    from app.services import deyu_auth, inspector_auth
    from tasks.modules.leader import admins

    try:
        if admins.is_active_admin(userid):
            return "/api/admin"
        if deyu_auth.is_deyu_account(userid):
            return "/api/deyu"
        if inspector_auth.is_inspector_account(userid):
            return "/api/inspector"
    except Exception:
        pass
    return "/api/head_teacher_workbench"


@router.get("/auth/wecom/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    if not oauth.is_enabled():
        return _disabled()
    if not state or state != request.cookies.get(oauth.STATE_COOKIE):
        return JSONResponse(
            {"code": "state_mismatch", "error": "授权状态校验失败", "data": None},
            status_code=400,
        )
    try:
        userid = await oauth.fetch_userid(code)
    except oauth.WecomOAuthError as exc:
        return JSONResponse(
            {"code": "wecom_oauth_failed", "error": str(exc), "data": None},
            status_code=502,
        )
    response = RedirectResponse(role_home(userid), status_code=302)
    response.set_cookie(
        oauth.SESSION_COOKIE, oauth.sign_session(userid),
        max_age=oauth.SESSION_TTL_SECONDS, httponly=True, samesite="lax",
    )
    response.delete_cookie(oauth.STATE_COOKIE)
    return response


@router.get("/auth/wecom/me")
async def me(request: Request):
    """联调期用来确认企微 UserId 与工作台 userid 是否同名。"""
    if not oauth.is_enabled():
        return _disabled()
    userid = oauth.read_session(request.cookies.get(oauth.SESSION_COOKIE, ""))
    if not userid:
        return JSONResponse(
            {"code": "unauthorized", "error": "未登录或会话已过期", "data": None},
            status_code=401,
        )
    return {"code": 0, "error": "", "data": {"userid": userid}}


@router.get("/auth/wecom/logout")
async def logout():
    response = RedirectResponse("/api/v1/login", status_code=302)
    response.delete_cookie(oauth.SESSION_COOKIE)
    return response
