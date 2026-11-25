# -*- coding: utf-8 -*-
"""Redis + worker + website 三进程端到端集成测试。

默认跳过；仅在 ``HTW_E2E=1`` 且 ``HTW_E2E_REDIS_URL``（默认
``redis://127.0.0.1:6379/15``）可连接时运行，因此普通 ``pytest`` 不需要 Redis。

测试自行启动两个子进程（uvicorn 提供 website，模块化 worker 消费 Redis 队列），
使用临时 SQLite、独立队列与独立响应前缀，结束时终止子进程并只删除自己写入的 key。
不覆盖归档数据库，也不对 Redis 执行 FLUSHDB／FLUSHALL。
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEBSITE_ROOT = ROOT / "website"

REDIS_URL = os.environ.get("HTW_E2E_REDIS_URL", "redis://127.0.0.1:6379/15")
REQUEST_TIMEOUT_SECONDS = 2.0
RESPONSE_TTL_SECONDS = 30
DEFAULT_REQUEST_QUEUE = "head_teacher_workbench:requests"
STARTUP_TIMEOUT_SECONDS = 45

pytestmark = pytest.mark.skipif(
    os.environ.get("HTW_E2E") != "1",
    reason="三进程集成测试需要 Redis；设置 HTW_E2E=1 后运行",
)

# 复用 website 测试的做法：启动前去掉 MySQL 建表初始化，工作台链路只依赖 Redis。
LAUNCHER_SOURCE = """\
import sys
from pathlib import Path

website = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(website))

from app.initializer import g

g._init_properties = tuple(
    name for name in g._init_properties if name != "db_async_session"
)

import uvicorn

uvicorn.run(
    "app.main:app",
    host="127.0.0.1",
    port=int(sys.argv[2]),
    log_level="warning",
)
"""


def _free_tcp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _tail(path, limit=3000):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "<no log>"
    return text[-limit:]


def _request(base_url, method, path, body=None, timeout=10):
    import requests

    session = requests.Session()
    session.trust_env = False
    try:
        return session.request(method, base_url + path, json=body, timeout=timeout)
    finally:
        session.close()


class Stack:
    """两个子进程 + 本次运行独占的 Redis key 前缀。"""

    def __init__(self, redis_client, tempdir, queue, prefix, default_queue_length):
        self.redis = redis_client
        self.tempdir = tempdir
        self.queue = queue
        self.prefix = prefix
        self.default_queue_length = default_queue_length
        self.base_url = ""
        self.website = None
        self.worker = None
        self.website_log = None
        self.worker_log = None

    def stop_worker(self):
        if self.worker is not None and self.worker.poll() is None:
            self.worker.terminate()
            try:
                self.worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.worker.kill()
                self.worker.wait(timeout=10)

    def response_keys(self):
        return {key for key in self.redis.scan_iter(match=self.prefix + "*")}


@pytest.fixture(scope="module")
def redis_client():
    import redis

    client = redis.Redis.from_url(
        REDIS_URL, decode_responses=True,
        socket_connect_timeout=2, socket_timeout=2,
    )
    try:
        client.ping()
    except Exception as exc:  # 连接失败只跳过，不影响普通测试
        pytest.skip(
            "HTW_E2E_REDIS_URL 指向的 Redis 不可达，跳过三进程集成测试："
            f"{type(exc).__name__}"
        )
    yield client
    client.close()


@pytest.fixture(scope="module")
def stack(redis_client):
    run_id = uuid.uuid4().hex[:12]
    queue = f"htw-e2e:{run_id}:requests"
    prefix = f"htw-e2e:{run_id}:response:"
    tempdir = Path(tempfile.mkdtemp(prefix="htw-e2e-"))
    default_queue_length = redis_client.llen(DEFAULT_REQUEST_QUEUE)

    env = os.environ.copy()
    env.update({
        "DB_PATH": str(tempdir / "dywork.db"),
        "HEAD_TEACHER_WORKBENCH_REDIS_URL": REDIS_URL,
        "HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE": queue,
        "HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX": prefix,
        "HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS": str(REQUEST_TIMEOUT_SECONDS),
        "HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS": str(RESPONSE_TTL_SECONDS),
        "ENABLE_SCHEDULER": "0",
        "APP_ENV": "dev",
        "APP_LOG_OUTDIR": str(tempdir / "website_logs"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    })

    launcher = tempdir / "run_website.py"
    launcher.write_text(LAUNCHER_SOURCE, encoding="utf-8")
    port = _free_tcp_port()

    stack_obj = Stack(redis_client, tempdir, queue, prefix, default_queue_length)
    stack_obj.website_log = tempdir / "website.log"
    stack_obj.worker_log = tempdir / "worker.log"
    website_out = open(stack_obj.website_log, "wb")
    worker_out = open(stack_obj.worker_log, "wb")
    try:
        stack_obj.website = subprocess.Popen(
            [sys.executable, str(launcher), str(WEBSITE_ROOT), str(port)],
            cwd=str(WEBSITE_ROOT), env=env,
            stdout=website_out, stderr=subprocess.STDOUT,
        )
        stack_obj.worker = subprocess.Popen(
            [sys.executable, "-m", "tasks.interfaces.worker"],
            cwd=str(ROOT), env=env,
            stdout=worker_out, stderr=subprocess.STDOUT,
        )
        stack_obj.base_url = f"http://127.0.0.1:{port}"
        _wait_ready(stack_obj)
        yield stack_obj
    finally:
        stack_obj.stop_worker()
        if stack_obj.website is not None and stack_obj.website.poll() is None:
            stack_obj.website.terminate()
            try:
                stack_obj.website.wait(timeout=10)
            except subprocess.TimeoutExpired:
                stack_obj.website.kill()
                stack_obj.website.wait(timeout=10)
        website_out.close()
        worker_out.close()
        redis_client.delete(queue)
        keys = list(redis_client.scan_iter(match=prefix + "*"))
        if keys:
            redis_client.delete(*keys)
        shutil.rmtree(tempdir, ignore_errors=True)


def _wait_ready(stack_obj):
    """先等页面，再等健康检查——后者同时证明 worker 已消费 Redis 请求。"""
    deadline = time.time() + STARTUP_TIMEOUT_SECONDS
    last_error = "未发起请求"
    while time.time() < deadline:
        try:
            response = _request(
                stack_obj.base_url, "GET", "/api/head_teacher_workbench", timeout=3,
            )
            if response.status_code == 200:
                break
            last_error = f"页面返回 {response.status_code}"
        except Exception as exc:
            last_error = f"页面连接失败：{type(exc).__name__}"
        time.sleep(0.2)
    else:
        raise AssertionError(
            f"website 未在 {STARTUP_TIMEOUT_SECONDS}s 内就绪（{last_error}）\n"
            f"website log:\n{_tail(stack_obj.website_log)}"
        )

    while time.time() < deadline:
        try:
            response = _request(
                stack_obj.base_url, "GET", "/api/v1/health",
                timeout=REQUEST_TIMEOUT_SECONDS + 3,
            )
            if response.status_code == 200:
                return
            last_error = f"health 返回 {response.status_code}"
        except Exception as exc:
            last_error = f"health 连接失败：{type(exc).__name__}"
        time.sleep(0.3)
    raise AssertionError(
        f"worker 未在 {STARTUP_TIMEOUT_SECONDS}s 内就绪（{last_error}）\n"
        f"worker log:\n{_tail(stack_obj.worker_log)}\n"
        f"website log:\n{_tail(stack_obj.website_log)}"
    )


def _get_json(stack, path):
    response = _request(stack.base_url, "GET", path)
    return response, response.json()


def test_page_health_business_read_and_wecom_text_semantics(stack):
    page = _request(stack.base_url, "GET", "/api/head_teacher_workbench")
    assert page.status_code == 200
    assert "/static/head_teacher_workbench/style.css" in page.text
    assert "/static/head_teacher_workbench/app.js" in page.text

    # health 经 website 代理到 Redis 队列，由 worker 执行后回传。
    health, health_body = _get_json(stack, "/api/v1/health")
    assert health.status_code == 200
    assert health_body["code"] == 0
    assert health_body["data"]["status"] == "running"

    directory, directory_body = _get_json(stack, "/api/v1/org/directory")
    assert directory.status_code == 200
    assert directory_body["code"] == 0
    assert directory_body["data"]["posts"]

    # 建立会话后访问敏感派生字段，后台必须保持 403 语义。
    resolve = _request(
        stack.base_url, "POST", "/api/v1/session/resolve", body={"userid": "zhangmin"},
    )
    assert resolve.status_code == 200
    session_id = resolve.json()["data"]["ctx"]["session_id"]
    forbidden = _request(
        stack.base_url, "GET",
        f"/api/v1/growth/overview?session_id={session_id}&fields=scores",
    )
    assert forbidden.status_code == 403
    forbidden_body = forbidden.json()
    assert forbidden_body["code"] == "derived_zone_forbidden"
    assert forbidden_body["data"] is None

    # 企微 GET 回调仍走 text/plain，不能退化成 JSON envelope。
    wecom = _request(stack.base_url, "GET", "/api/v1/wecom/callback")
    assert wecom.status_code == 403
    assert wecom.headers["content-type"].startswith("text/plain")
    with pytest.raises(json.JSONDecodeError):
        json.loads(wecom.text)


def test_eight_concurrent_requests_are_correlated_one_to_one(stack):
    before = stack.response_keys()

    def call(_):
        response = _request(stack.base_url, "GET", "/api/v1/org/directory")
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(call, range(8)))

    assert [status for status, _ in results] == [200] * 8
    assert all(body["code"] == 0 for _, body in results)

    new_keys = stack.response_keys() - before
    assert len(new_keys) == 8
    request_ids = set()
    for key in new_keys:
        payload = json.loads(stack.redis.get(key))
        request_id = key[len(stack.prefix):]
        assert payload["request_id"] == request_id
        request_ids.add(request_id)
    assert len(request_ids) == 8
    # worker 已消费全部请求，队列不应留有积压。
    assert stack.redis.llen(stack.queue) == 0


def test_stopped_worker_returns_504_and_enqueues_once(stack):
    # 本用例必须排在读写用例之后：它会终止 worker。
    stack.stop_worker()
    assert stack.redis.llen(stack.queue) == 0

    response = _request(
        stack.base_url, "GET", "/api/v1/org/directory",
        timeout=REQUEST_TIMEOUT_SECONDS + 8,
    )
    assert response.status_code == 504
    body = response.json()
    assert body["code"] == "worker_timeout"
    assert body["data"] is None
    assert stack.redis.llen(stack.queue) == 1

    # 超时后不重放：再等一个完整超时周期，队列长度不得增长。
    time.sleep(REQUEST_TIMEOUT_SECONDS + 1.0)
    assert stack.redis.llen(stack.queue) == 1


def test_default_queue_is_not_polluted(stack):
    assert stack.redis.llen(DEFAULT_REQUEST_QUEUE) == stack.default_queue_length


def test_redis_unavailable_client_returns_503():
    """不依赖运行中的服务：指向未监听端口的客户端必须映射为 503。"""
    if str(WEBSITE_ROOT) not in sys.path:
        sys.path.insert(0, str(WEBSITE_ROOT))

    import redis.asyncio as aioredis

    from app.services.head_teacher_workbench import (
        HeadTeacherWorkbenchClient,
        RedisUnavailableError,
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]

    async def run():
        redis_client = aioredis.Redis.from_url(
            f"redis://127.0.0.1:{dead_port}/15",
            socket_connect_timeout=0.5, socket_timeout=0.5,
        )
        client = HeadTeacherWorkbenchClient(
            redis_client=redis_client,
            request_queue="htw-e2e:unreachable:requests",
            response_prefix="htw-e2e:unreachable:response:",
            timeout_seconds=0.5,
        )
        try:
            with pytest.raises(RedisUnavailableError) as caught:
                await client.request("GET", "/api/v1/health")
            return caught.value
        finally:
            await redis_client.aclose()

    error = asyncio.run(run())
    assert error.status_code == 503
    assert error.code == "redis_unavailable"
