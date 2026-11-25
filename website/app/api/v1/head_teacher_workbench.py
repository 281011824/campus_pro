"""班主任工作台协议路由清单：直接调用业务模块（单体 FastAPI + SQLite）。

不经过 Redis，website 直接 import tasks.head_teacher_workbench.worker.handle_request()。
"""
import base64
import json
import uuid

from fastapi import APIRouter, Request, Response

from app.services import wecom_oauth
from tasks.interfaces import worker


router = APIRouter()

FIXED_ROUTES = (
    ("GET", "/api/v1/health"),
    ("GET", "/api/v1/health/readiness"),
    ("GET", "/api/v1/settings"),
    ("GET", "/api/v1/org/directory"),
    ("GET", "/api/v1/org/persons"),
    ("GET", "/api/v1/org/posts"),
    ("GET", "/api/v1/org/conflicts"),
    ("GET", "/api/v1/portals"),
    ("GET", "/api/v1/portal/summary"),
    ("POST", "/api/v1/portal/auto"),
    ("GET", "/api/v1/federation/pools"),
    ("GET", "/api/v1/federation/peers"),
    ("POST", "/api/v1/federation/search"),
    ("GET", "/api/v1/coedu/view"),
    ("GET", "/api/v1/coedu/links"),
    ("GET", "/api/v1/coedu/inbox"),
    ("POST", "/api/v1/coedu/preview"),
    ("POST", "/api/v1/coedu/push"),
    ("GET", "/api/v1/space"),
    ("GET", "/api/v1/spaces"),
    ("POST", "/api/v1/space/focus"),
    ("POST", "/api/v1/space/event"),
    ("GET", "/api/v1/portal/cards"),
    ("POST", "/api/v1/portal/enter"),
    ("POST", "/api/v1/wecom/sync"),
    ("POST", "/api/v1/session/resolve"),
    ("POST", "/api/v1/session/switch"),
    ("POST", "/api/v1/chat"),
    ("POST", "/api/v1/write/confirm"),
    ("GET", "/api/v1/write/pending"),
    ("GET", "/api/v1/write/records"),
    ("GET", "/api/v1/report/weekly"),
    ("POST", "/api/v1/report/archive"),
    ("GET", "/api/v1/report/watchlist"),
    ("GET", "/api/v1/pilot/classes"),
    ("GET", "/api/v1/pilot/snapshot"),
    ("POST", "/api/v1/mcp/call"),
    ("GET", "/api/v1/push/flow"),
    ("POST", "/api/v1/push/run"),
    ("POST", "/api/v1/push/due"),
    ("GET", "/api/v1/todo/list"),
    ("POST", "/api/v1/todo/refer"),
    ("POST", "/api/v1/todo/note"),
    ("POST", "/api/v1/todo/close"),
    ("GET", "/api/v1/todo/referrals"),
    ("POST", "/api/v1/todo/receipt"),
    ("GET", "/api/v1/warning/state"),
    ("GET", "/api/v1/scheduler/status"),
    ("POST", "/api/v1/scheduler/weekly"),
    ("GET", "/api/v1/dun/targets"),
    ("POST", "/api/v1/dun/create"),
    ("POST", "/api/v1/dun/confirm"),
    ("POST", "/api/v1/dun/reply"),
    ("GET", "/api/v1/dun/list"),
    ("POST", "/api/v1/dun/escalate"),
    ("GET", "/api/v1/audit"),
    ("GET", "/api/v1/redline"),
    ("GET", "/api/v1/agent/registry"),
    ("GET", "/api/v1/agent/prompt"),
    ("GET", "/api/v1/wecom/outbox"),
    # 数据域（实施方案十四域）与德育量化
    ("GET", "/api/v1/domains/status"),
    ("GET", "/api/v1/moral/summary"),
    ("POST", "/api/v1/moral/event"),
    ("POST", "/api/v1/moral/confirm"),
)
GROWTH_LEAVES = (
    "overview", "attention", "derived", "balance", "goals",
    "profile", "readiness", "workitem", "numbers",
)
DYNAMIC_ROUTES = (
    ("GET", "/api/v1/session/{session_id}"),
    ("POST", "/api/v1/ingest/{domain}"),
    *(("GET", f"/api/v1/growth/{leaf}") for leaf in GROWTH_LEAVES),
)
WECOM_ROUTES = (
    ("GET", "/api/v1/wecom/callback"),
    ("POST", "/api/v1/wecom/callback"),
)
API_ROUTES = FIXED_ROUTES + DYNAMIC_ROUTES + WECOM_ROUTES


# 开启 OAuth 后仍需匿名可达的路径：企微服务器回调、存活探针
ANONYMOUS_PATHS = (
    "/api/v1/wecom/callback",
    "/api/v1/health",
    "/api/v1/health/readiness",
)


# 本地登录账号 → 企业微信通讯录 userid（业务身份）。
# 登录页账号是给校内试用用的，业务层仍以企微 userid 为准。
LOGIN_USER_ALIASES = {
    "xuhaichao": "Tiao",
    "admin": "zhangmin",
    "test": "teacher1",
}


def resolve_auth_user(request: Request) -> str:
    """优先使用登录会话（本地登录与企微 OAuth 共用）；未启用任何登录时才信任请求头。"""
    session_user = wecom_oauth.read_session(
        request.cookies.get(wecom_oauth.SESSION_COOKIE, ""),
    )
    if session_user:
        return LOGIN_USER_ALIASES.get(session_user, session_user)
    if wecom_oauth.auth_required():
        return ""
    return request.headers.get("X-Auth-User", "")


async def head_teacher_workbench_proxy(request: Request):
    auth_user = resolve_auth_user(request)
    if (
        wecom_oauth.auth_required()
        and not auth_user
        and request.url.path not in ANONYMOUS_PATHS
    ):
        return Response(
            content=json.dumps(
                {"code": "unauthorized", "error": "未登录或会话已过期", "data": None},
                ensure_ascii=False,
            ),
            status_code=401,
            headers={"content-type": "application/json; charset=utf-8"},
        )

    raw_body = await request.body()
    try:
        parsed_body = json.loads(raw_body) if raw_body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed_body = None
    body = parsed_body if isinstance(parsed_body, dict) else None
    query = request.scope.get("query_string", b"").decode("latin-1")

    # 构造 worker.handle_request() 期望的 request dict，绕过 Redis 线协议
    fake_request = {
        "request_id": str(uuid.uuid4()),
        "method": request.method,
        "path": request.url.path,
        "query": query,
        "body": body,
        "raw_body": base64.b64encode(raw_body or b"").decode("ascii"),
        "X-Auth-User": auth_user,
        "timestamp": "",
    }
    result = worker.handle_request(fake_request)

    return Response(
        content=result["body"],
        status_code=result["status"],
        headers={"content-type": result["content_type"]},
    )


for method, path in API_ROUTES:
    router.add_api_route(
        path.removeprefix("/api/v1"),
        head_teacher_workbench_proxy,
        methods=[method],
        response_model=None,
    )
