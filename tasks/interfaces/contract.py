"""迁移双方共用的路由与 Redis 线协议常量；不包含业务实现。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    response_kind: str = "json"

    @property
    def key(self):
        return self.method, self.path


# server.route() 中 60 个固定 method/path 分派，顺序与归档源码一致。
FIXED_ROUTES = (
    Route("GET", "/api/v1/health"),
    Route("GET", "/api/v1/health/readiness"),
    Route("GET", "/api/v1/settings"),
    Route("GET", "/api/v1/org/directory"),
    Route("GET", "/api/v1/org/persons"),
    Route("GET", "/api/v1/org/posts"),
    Route("GET", "/api/v1/org/conflicts"),
    Route("GET", "/api/v1/portals"),
    Route("GET", "/api/v1/portal/summary"),
    Route("POST", "/api/v1/portal/auto"),
    Route("GET", "/api/v1/federation/pools"),
    Route("GET", "/api/v1/federation/peers"),
    Route("POST", "/api/v1/federation/search"),
    Route("GET", "/api/v1/coedu/view"),
    Route("GET", "/api/v1/coedu/links"),
    Route("GET", "/api/v1/coedu/inbox"),
    Route("POST", "/api/v1/coedu/preview"),
    Route("POST", "/api/v1/coedu/push"),
    Route("GET", "/api/v1/space"),
    Route("GET", "/api/v1/spaces"),
    Route("POST", "/api/v1/space/focus"),
    Route("POST", "/api/v1/space/event"),
    Route("GET", "/api/v1/portal/cards"),
    Route("POST", "/api/v1/portal/enter"),
    Route("POST", "/api/v1/wecom/sync"),
    Route("POST", "/api/v1/session/resolve"),
    Route("POST", "/api/v1/session/switch"),
    Route("POST", "/api/v1/chat"),
    Route("POST", "/api/v1/write/confirm"),
    Route("GET", "/api/v1/write/pending"),
    Route("GET", "/api/v1/write/records"),
    Route("GET", "/api/v1/report/weekly"),
    Route("POST", "/api/v1/report/archive"),
    Route("GET", "/api/v1/report/watchlist"),
    Route("GET", "/api/v1/pilot/classes"),
    Route("GET", "/api/v1/pilot/snapshot"),
    Route("POST", "/api/v1/mcp/call"),
    Route("GET", "/api/v1/push/flow"),
    Route("POST", "/api/v1/push/run"),
    Route("POST", "/api/v1/push/due"),
    Route("GET", "/api/v1/todo/list"),
    Route("POST", "/api/v1/todo/refer"),
    Route("POST", "/api/v1/todo/note"),
    Route("POST", "/api/v1/todo/close"),
    Route("GET", "/api/v1/todo/referrals"),
    Route("POST", "/api/v1/todo/receipt"),
    Route("GET", "/api/v1/warning/state"),
    Route("GET", "/api/v1/scheduler/status"),
    Route("POST", "/api/v1/scheduler/weekly"),
    Route("GET", "/api/v1/dun/targets"),
    Route("POST", "/api/v1/dun/create"),
    Route("POST", "/api/v1/dun/confirm"),
    Route("POST", "/api/v1/dun/reply"),
    Route("GET", "/api/v1/dun/list"),
    Route("POST", "/api/v1/dun/escalate"),
    Route("GET", "/api/v1/audit"),
    Route("GET", "/api/v1/redline"),
    Route("GET", "/api/v1/agent/registry"),
    Route("GET", "/api/v1/agent/prompt"),
    Route("GET", "/api/v1/wecom/outbox"),
)

GROWTH_LEAVES = (
    "overview",
    "attention",
    "derived",
    "balance",
    "goals",
    "profile",
    "readiness",
    "workitem",
    "numbers",
)

# 两个动态分派展开后的 10 个精确注册路径。
DYNAMIC_ROUTES = (
    Route("GET", "/api/v1/session/{session_id}"),
    *(Route("GET", f"/api/v1/growth/{leaf}") for leaf in GROWTH_LEAVES),
)

# 企微两个回调由 Handler 单独处理，不能包成普通 JSON envelope。
WECOM_ROUTES = (
    Route("GET", "/api/v1/wecom/callback", "wecom_verify"),
    Route("POST", "/api/v1/wecom/callback", "wecom_callback"),
)

NORMAL_ROUTES = FIXED_ROUTES + DYNAMIC_ROUTES
API_ROUTES = NORMAL_ROUTES + WECOM_ROUTES

SOURCE_FIXED_DISPATCHES = 60
SOURCE_DYNAMIC_DISPATCHES = 2
SOURCE_PREFIX_GUARDS = 3
SOURCE_ROUTE_BRANCHES = 65
SOURCE_DISPATCH_BRANCHES = 62
PREFIX_GUARDS = (
    ("POST", "/api/v1/federation"),
    ("POST", "/api/v1/coedu"),
    ("POST", "/api/v1/space"),
)

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_REQUEST_QUEUE = "head_teacher_workbench:requests"
DEFAULT_RESPONSE_PREFIX = "head_teacher_workbench:response:"
DEFAULT_RESPONSE_TTL_SECONDS = 30
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5.0
RETRY_ON_TIMEOUT = False

REDIS_URL_ENV = "HEAD_TEACHER_WORKBENCH_REDIS_URL"
REQUEST_QUEUE_ENV = "HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE"
RESPONSE_PREFIX_ENV = "HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX"
RESPONSE_TTL_ENV = "HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS"
REQUEST_TIMEOUT_ENV = "HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS"

# query 是未改写的查询字符串；raw_body 是原始字节的 base64 ASCII 文本。
# body 在没有 JSON 对象时为 None；timestamp 是带 UTC 时区的 ISO-8601 文本。
REQUEST_REQUIRED_FIELDS = frozenset({
    "request_id",
    "method",
    "path",
    "query",
    "body",
    "raw_body",
    "X-Auth-User",
    "timestamp",
})
# body 是 UTF-8 解码后的文本；响应 TTL 是 Redis key 元数据，不塞进消息体。
RESPONSE_REQUIRED_FIELDS = frozenset({
    "request_id",
    "status",
    "content_type",
    "body",
})

ERROR_STATUS = {
    "redis_unavailable": 503,
    "worker_timeout": 504,
    "bad_worker_response": 502,
}
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
TEXT_CONTENT_TYPE = "text/plain; charset=utf-8"
XML_CONTENT_TYPE = "text/xml; charset=utf-8"


def response_key(request_id: str) -> str:
    """按 request_id 生成一次性响应 key；关联校验仍是接收方职责。"""
    if not request_id or not isinstance(request_id, str):
        raise ValueError("request_id must be a non-empty string")
    return DEFAULT_RESPONSE_PREFIX + request_id
