"""Task 3 的 Redis 客户端目标测试；模块不存在时明确跳过。"""
import asyncio
import base64
from datetime import datetime
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEBSITE_ROOT = ROOT / "website"
for path in (ROOT, WEBSITE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from tasks.interfaces.contract import (DEFAULT_REQUEST_QUEUE, DEFAULT_RESPONSE_PREFIX, REQUEST_REQUIRED_FIELDS, RESPONSE_REQUIRED_FIELDS)

client_module = pytest.importorskip(
    "app.services.head_teacher_workbench",
    reason="Task 3 尚未实现班主任工作台 Redis 客户端",
)


class FakeRedis:
    def __init__(self, response=None, push_error=None, get_error=None):
        self.response = response
        self.push_error = push_error
        self.get_error = get_error
        self.published = []
        self.get_keys = []

    async def rpush(self, queue, payload):
        self.published.append((queue, payload))
        if self.push_error:
            raise self.push_error
        return 1

    async def get(self, key):
        self.get_keys.append(key)
        if self.get_error:
            raise self.get_error
        if callable(self.response):
            return self.response(key)
        return self.response


def make_client(redis_client, timeout=0.02):
    return client_module.HeadTeacherWorkbenchClient(
        redis_client=redis_client,
        request_queue=DEFAULT_REQUEST_QUEUE,
        response_prefix=DEFAULT_RESPONSE_PREFIX,
        timeout_seconds=timeout,
        response_ttl_seconds=30,
    )


def request(client, method="GET"):
    return asyncio.run(client.request(
        method=method,
        path="/api/v1/chat" if method == "POST" else "/api/v1/health",
        query="a=1&a=2&blank=",
        body={"text": "你好"} if method == "POST" else None,
        raw_body=b'{"text":"\xe4\xbd\xa0\xe5\xa5\xbd"}' if method == "POST" else b"",
        auth_user=" zhangmin ",
    ))


def test_request_uses_shared_fields_and_returns_correlated_response():
    def respond(key):
        sent = json.loads(fake.published[0][1])
        assert key == DEFAULT_RESPONSE_PREFIX + sent["request_id"]
        return json.dumps({
            "request_id": sent["request_id"],
            "status": 200,
            "content_type": "application/json; charset=utf-8",
            "body": '{"code":0,"data":{"status":"running"}}',
        })

    fake = FakeRedis(response=respond)
    result = request(make_client(fake), method="POST")
    assert len(fake.published) == 1
    queue, payload = fake.published[0]
    sent = json.loads(payload)
    assert queue == DEFAULT_REQUEST_QUEUE
    assert set(sent) == REQUEST_REQUIRED_FIELDS
    assert sent["method"] == "POST"
    assert sent["path"] == "/api/v1/chat"
    assert sent["query"] == "a=1&a=2&blank="
    assert sent["body"] == {"text": "你好"}
    assert base64.b64decode(sent["raw_body"]) == b'{"text":"\xe4\xbd\xa0\xe5\xa5\xbd"}'
    assert sent["X-Auth-User"] == "zhangmin"
    assert datetime.fromisoformat(sent["timestamp"]).utcoffset().total_seconds() == 0
    assert set(result) == RESPONSE_REQUIRED_FIELDS
    assert result["request_id"] == sent["request_id"]


def test_timeout_returns_504_error_and_never_replays_post():
    fake = FakeRedis(response=None)
    with pytest.raises(client_module.WorkerTimeoutError) as caught:
        request(make_client(fake), method="POST")
    assert caught.value.status_code == 504
    assert caught.value.code == "worker_timeout"
    assert len(fake.published) == 1


def test_connection_failure_is_503_and_not_business_success():
    fake = FakeRedis(push_error=ConnectionError("offline"))
    with pytest.raises(client_module.RedisUnavailableError) as caught:
        request(make_client(fake))
    assert caught.value.status_code == 503
    assert caught.value.code == "redis_unavailable"
    assert len(fake.published) == 1


def test_response_connection_failure_is_also_503():
    fake = FakeRedis(get_error=ConnectionError("offline"))
    with pytest.raises(client_module.RedisUnavailableError) as caught:
        request(make_client(fake))
    assert caught.value.status_code == 503
    assert caught.value.code == "redis_unavailable"
    assert len(fake.published) == 1


@pytest.mark.parametrize("response", [
    "not-json",
    "{}",
    json.dumps({
        "request_id": "another-request",
        "status": 200,
        "content_type": "application/json; charset=utf-8",
        "body": "{}",
    }),
    json.dumps({
        "request_id": "same-request",
        "status": "200",
        "content_type": "application/json; charset=utf-8",
        "body": "{}",
    }),
    json.dumps({
        "request_id": "same-request",
        "status": 200,
        "content_type": "application/json; charset=utf-8",
        "body": {},
    }),
])
def test_bad_or_mismatched_response_is_502(response):
    fake = FakeRedis(response=response)
    if "same-request" in response:
        # 先让关联 ID 对齐，确保本用例实际校验字段类型而非提前因 ID 拒绝。
        original_response = response

        def correlated_response(key):
            sent = json.loads(fake.published[0][1])
            assert key == DEFAULT_RESPONSE_PREFIX + sent["request_id"]
            return original_response.replace("same-request", sent["request_id"])

        fake.response = correlated_response
    with pytest.raises(client_module.BadWorkerResponseError) as caught:
        request(make_client(fake))
    assert caught.value.status_code == 502
    assert caught.value.code == "bad_worker_response"
    assert len(fake.published) == 1


def test_client_factory_honors_queue_response_and_timeout_environment(monkeypatch):
    monkeypatch.setattr(
        client_module, "get_head_teacher_workbench_redis", lambda: object(),
    )
    monkeypatch.setenv("HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE", "test:queue")
    monkeypatch.setenv("HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX", "test:response:")
    monkeypatch.setenv("HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS", "1.25")
    monkeypatch.setenv("HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS", "12")
    client = client_module.get_head_teacher_workbench_client()
    assert client.request_queue == "test:queue"
    assert client.response_prefix == "test:response:"
    assert client.timeout_seconds == 1.25
    assert client.response_ttl_seconds == 12
