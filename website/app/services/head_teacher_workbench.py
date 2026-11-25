"""班主任工作台 Redis 请求/响应客户端；只实现线协议，不包含业务规则。"""
import asyncio
import base64
from datetime import datetime, timezone
import json
import os
import uuid

import redis.asyncio as redis

from app.initializer import g
from app.initializer._redis import get_head_teacher_workbench_redis


DEFAULT_REQUEST_QUEUE = "head_teacher_workbench:requests"
DEFAULT_RESPONSE_PREFIX = "head_teacher_workbench:response:"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5.0
DEFAULT_RESPONSE_TTL_SECONDS = 30
RESPONSE_REQUIRED_FIELDS = frozenset({"request_id", "status", "content_type", "body"})


class HeadTeacherWorkbenchError(Exception):
    status_code = 502
    code = "bad_worker_response"

    def __init__(self, message):
        self.message = message
        super().__init__(message)


class RedisUnavailableError(HeadTeacherWorkbenchError):
    status_code = 503
    code = "redis_unavailable"

    def __init__(self, message="班主任工作台服务暂时不可用"):
        super().__init__(message)


class WorkerTimeoutError(HeadTeacherWorkbenchError):
    status_code = 504
    code = "worker_timeout"

    def __init__(self, message="班主任工作台后台响应超时"):
        super().__init__(message)


class BadWorkerResponseError(HeadTeacherWorkbenchError):
    status_code = 502
    code = "bad_worker_response"

    def __init__(self, message="班主任工作台后台响应无效"):
        super().__init__(message)


class HeadTeacherWorkbenchClient:
    def __init__(
        self,
        redis_client,
        request_queue=DEFAULT_REQUEST_QUEUE,
        response_prefix=DEFAULT_RESPONSE_PREFIX,
        timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
        response_ttl_seconds=DEFAULT_RESPONSE_TTL_SECONDS,
        poll_interval_seconds=0.05,
    ):
        self.redis_client = redis_client
        self.request_queue = request_queue
        self.response_prefix = response_prefix
        self.timeout_seconds = float(timeout_seconds)
        self.response_ttl_seconds = int(response_ttl_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)

    async def request(self, method, path, query="", body=None, raw_body=b"", auth_user=""):
        request_id = str(uuid.uuid4())
        payload = json.dumps({
            "request_id": request_id,
            "method": method.upper(),
            "path": path,
            "query": query,
            "body": body,
            "raw_body": base64.b64encode(raw_body or b"").decode("ascii"),
            "X-Auth-User": (auth_user or "").strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)
        response_key = self.response_prefix + request_id

        try:
            # 每次调用只投递一次；尤其不能在超时后重放写请求。
            await self.redis_client.rpush(self.request_queue, payload)
        except (redis.RedisError, ConnectionError, TimeoutError, OSError):
            raise RedisUnavailableError() from None

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout_seconds
        while True:
            try:
                raw_response = await self.redis_client.get(response_key)
            except (redis.RedisError, ConnectionError, TimeoutError, OSError):
                raise RedisUnavailableError() from None
            if raw_response is not None:
                return self._parse_response(raw_response, request_id)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise WorkerTimeoutError()
            await asyncio.sleep(min(self.poll_interval_seconds, remaining))

    @staticmethod
    def _parse_response(raw_response, request_id):
        try:
            if isinstance(raw_response, bytes):
                raw_response = raw_response.decode("utf-8")
            if not isinstance(raw_response, str):
                raise TypeError
            response = json.loads(raw_response)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            raise BadWorkerResponseError() from None

        if not isinstance(response, dict) or not RESPONSE_REQUIRED_FIELDS.issubset(response):
            raise BadWorkerResponseError()
        if response["request_id"] != request_id:
            raise BadWorkerResponseError()
        if type(response["status"]) is not int or not 100 <= response["status"] <= 599:
            raise BadWorkerResponseError()
        if not isinstance(response["content_type"], str) or not response["content_type"]:
            raise BadWorkerResponseError()
        if not isinstance(response["body"], str):
            raise BadWorkerResponseError()
        return {field: response[field] for field in RESPONSE_REQUIRED_FIELDS}


def get_head_teacher_workbench_client():
    try:
        redis_client = get_head_teacher_workbench_redis()
    except RuntimeError:
        raise RedisUnavailableError() from None
    return HeadTeacherWorkbenchClient(
        redis_client=redis_client,
        request_queue=os.getenv(
            "HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE",
            g.config.HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE,
        ),
        response_prefix=os.getenv(
            "HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX",
            g.config.HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX,
        ),
        timeout_seconds=float(os.getenv(
            "HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS",
            str(g.config.HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS),
        )),
        response_ttl_seconds=int(os.getenv(
            "HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS",
            str(g.config.HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS),
        )),
    )
