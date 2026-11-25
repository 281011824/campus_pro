"""登录页与本地账号登录。

本地账号仅作为企业微信 OAuth 上线前的过渡方案：
账号表放在环境变量 LOCAL_LOGIN_USERS（userid:sha256hex,...），
密码只存 SHA-256 摘要，登录成功后复用企微会话 Cookie（htw_session），
因此 OAuth 启用后同一份会话可直接复用，不再区分登录来源。
"""

import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import APP_DIR
from app.initializer import g
from app.services import wecom_oauth
from app.services import deyu_auth
from app.services import inspector_auth
from app.services import student_auth
from tasks.domain.identity import accounts as school_accounts
from tasks.modules.leader import admins

router = APIRouter()

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))

DEFAULT_NEXT = "/api/head_teacher_workbench"
_MAX_FAILS = 5
_FAIL_WINDOW_SECONDS = 60
# 仅记录失败次数，成功即清除；键为客户端 IP
_failures: dict[str, list[float]] = {}


def _safe_next(raw: str) -> str:
    """只允许站内相对路径，避免开放重定向。"""
    if (
        not raw
        or not raw.startswith("/")
        or raw.startswith("//")
        or "\\" in raw
        or "\r" in raw
        or "\n" in raw
    ):
        return DEFAULT_NEXT
    return raw


def _accounts() -> dict[str, str]:
    accounts: dict[str, str] = {}
    for item in (g.config.LOCAL_LOGIN_USERS or "").split(","):
        item = item.strip()
        if ":" not in item:
            continue
        userid, digest = item.split(":", 1)
        userid, digest = userid.strip(), digest.strip().lower()
        if userid and len(digest) == 64:
            accounts[userid] = digest
    return accounts


def _db_digest(userid: str) -> str | None:
    """全校教师账号（SQLite school_accounts）中的密码摘要。"""
    try:
        record = school_accounts.get(userid)
    except Exception:
        return None
    return (record or {}).get("password_sha256")


def _admin_digest(userid: str) -> str | None:
    """管理员账号（admin_accounts）中的密码摘要。"""
    try:
        record = admins.get(userid)
    except Exception:
        return None
    if not record or record.get("status") != "active":
        return None
    return (record or {}).get("password_sha256")


def _local_enabled(env_accounts: dict[str, str]) -> bool:
    if env_accounts:
        return True
    try:
        if school_accounts.count() > 0:
            return True
    except Exception:
        pass
    try:
        return admins.count() > 0
    except Exception:
        return False


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _locked_seconds(key: str) -> int:
    now = time.time()
    hits = [t for t in _failures.get(key, []) if now - t < _FAIL_WINDOW_SECONDS]
    if hits:
        _failures[key] = hits
    else:
        _failures.pop(key, None)
    if len(hits) < _MAX_FAILS:
        return 0
    return int(_FAIL_WINDOW_SECONDS - (now - hits[0])) + 1


def _record_failure(key: str) -> None:
    _failures.setdefault(key, []).append(time.time())


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"code": code, "error": message, "data": None},
        status_code=status,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = ""):
    return templates.TemplateResponse(
        request,
        "login/index.html",
        {
            "request": request,
            "next_url": _safe_next(next),
            "wecom_enabled": wecom_oauth.is_enabled(),
            "wecom_login_url": "/api/v1/auth/wecom/login",
        },
    )


@router.post("/login")
async def login_submit(request: Request):
    accounts = _accounts()
    if not _local_enabled(accounts) or not g.config.AUTH_COOKIE_SECRET:
        return _error(
            "local_login_disabled",
            "本地账号登录未启用，请联系管理员配置",
            503,
        )

    try:
        payload = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error("bad_request", "请求格式错误", 400)
    if not isinstance(payload, dict):
        return _error("bad_request", "请求格式错误", 400)

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    if not username or not password:
        return _error("bad_request", "请输入账号和密码", 400)

    key = _client_key(request)
    locked = _locked_seconds(key)
    if locked:
        return _error(
            "too_many_attempts",
            f"尝试次数过多，请 {locked} 秒后再试",
            429,
        )

    # 管理员账号以 admin_accounts 表为准：避免 LOCAL_LOGIN_USERS 中残留的同名条目
    # 覆盖管理台密码（例如历史遗留的 admin 条目），导致 admin/abcd1230 无法登录。
    expected = (_admin_digest(username) or accounts.get(username) or _db_digest(username)
                or student_auth.expected_digest(username))
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    if not expected or not hmac.compare_digest(digest, expected):
        _record_failure(key)
        return _error("invalid_credentials", "账号或密码错误", 401)

    _failures.pop(key, None)
    is_admin_login = admins.is_active_admin(username)
    if is_admin_login:
        try:
            admins.touch_login(username)
        except Exception:
            pass
    data = {"userid": username}
    if is_admin_login:
        data["next"] = "/api/admin"
    elif deyu_auth.is_deyu_account(username):
        # 政教处优先进入独立工作台；班主任等其余角色保持原逻辑（前端默认工作台）
        data["next"] = "/api/deyu"
    elif inspector_auth.is_inspector_account(username):
        data["next"] = "/api/inspector"
    elif student_auth.is_student_account(username):
        # 学生：学号即账号，登录后直达个人门户（只本人数据）
        data["next"] = "/api/student"
    response = JSONResponse({"code": 0, "error": "", "data": data})
    response.set_cookie(
        wecom_oauth.SESSION_COOKIE,
        wecom_oauth.sign_session(username),
        max_age=wecom_oauth.SESSION_TTL_SECONDS,
        path="/",
        httponly=True,
        samesite="lax",
        secure=request.headers.get("x-forwarded-proto", "").lower() == "https",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/api/v1/login", status_code=302)
    response.delete_cookie(wecom_oauth.SESSION_COOKIE, path="/")
    return response
