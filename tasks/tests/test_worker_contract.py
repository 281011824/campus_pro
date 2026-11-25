"""Task 2 的后台请求处理目标测试；worker 不存在时明确跳过。"""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.interfaces.contract import (JSON_CONTENT_TYPE, RESPONSE_REQUIRED_FIELDS)

worker = pytest.importorskip(
    "tasks.interfaces.worker",
    reason="Task 2 尚未实现独立后台 worker",
)


def test_worker_dispatches_without_http_server_and_preserves_error_envelope():
    response = worker.handle_request({
        "request_id": "worker-contract-unknown-route",
        "method": "GET",
        "path": "/api/v1/not-found",
        "query": "",
        "body": None,
        "raw_body": base64.b64encode(b"").decode("ascii"),
        "X-Auth-User": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    assert set(response) == RESPONSE_REQUIRED_FIELDS
    assert response["request_id"] == "worker-contract-unknown-route"
    assert response["status"] == 404
    assert response["content_type"] == JSON_CONTENT_TYPE
    body = json.loads(response["body"])
    assert body["code"] == "not_found"
    assert body["data"] is None
    assert "error" in body
