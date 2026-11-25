import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tasks.interfaces.contract import (API_ROUTES, DEFAULT_REDIS_URL, DEFAULT_REQUEST_QUEUE, DEFAULT_REQUEST_TIMEOUT_SECONDS, DEFAULT_RESPONSE_PREFIX, DEFAULT_RESPONSE_TTL_SECONDS, ERROR_STATUS, REQUEST_QUEUE_ENV, REQUEST_REQUIRED_FIELDS, REQUEST_TIMEOUT_ENV, RESPONSE_PREFIX_ENV, RESPONSE_REQUIRED_FIELDS, RESPONSE_TTL_ENV, RETRY_ON_TIMEOUT, REDIS_URL_ENV, TEXT_CONTENT_TYPE, WRITE_METHODS, XML_CONTENT_TYPE, response_key)


def test_shared_defaults_and_environment_names():
    assert DEFAULT_REDIS_URL == "redis://127.0.0.1:6379/0"
    assert DEFAULT_REQUEST_QUEUE == "head_teacher_workbench:requests"
    assert DEFAULT_RESPONSE_PREFIX == "head_teacher_workbench:response:"
    assert DEFAULT_REQUEST_TIMEOUT_SECONDS == 5.0
    assert DEFAULT_RESPONSE_TTL_SECONDS == 30
    assert RETRY_ON_TIMEOUT is False
    assert REDIS_URL_ENV == "HEAD_TEACHER_WORKBENCH_REDIS_URL"
    assert REQUEST_QUEUE_ENV == "HEAD_TEACHER_WORKBENCH_REQUEST_QUEUE"
    assert RESPONSE_PREFIX_ENV == "HEAD_TEACHER_WORKBENCH_RESPONSE_PREFIX"
    assert RESPONSE_TTL_ENV == "HEAD_TEACHER_WORKBENCH_RESPONSE_TTL_SECONDS"
    assert REQUEST_TIMEOUT_ENV == "HEAD_TEACHER_WORKBENCH_REQUEST_TIMEOUT_SECONDS"


def test_request_example_preserves_raw_query_body_and_identity():
    raw = "<xml><Content>你好</Content></xml>".encode("utf-8")
    request = {
        "request_id": "req-001",
        "method": "POST",
        "path": "/api/v1/wecom/callback",
        "query": "nonce=n&timestamp=1700000000&nonce=n2",
        "body": None,
        "raw_body": base64.b64encode(raw).decode("ascii"),
        "X-Auth-User": "zhangmin",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    assert set(request) == REQUEST_REQUIRED_FIELDS
    assert (request["method"], request["path"]) in {route.key for route in API_ROUTES}
    assert request["query"] == "nonce=n&timestamp=1700000000&nonce=n2"
    assert base64.b64decode(request["raw_body"]) == raw
    assert datetime.fromisoformat(request["timestamp"]).utcoffset().total_seconds() == 0
    assert json.loads(json.dumps(request, ensure_ascii=False)) == request


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        (TEXT_CONTENT_TYPE, "echo_hello"),
        (XML_CONTENT_TYPE, "<xml><Content><![CDATA[已收到]]></Content></xml>"),
        ("application/json; charset=utf-8", '{"code":0,"data":{"ready":false}}'),
    ],
)
def test_response_example_is_correlated_utf8_text(content_type, body):
    response = {
        "request_id": "req-001",
        "status": 200,
        "content_type": content_type,
        "body": body,
    }
    assert set(response) == RESPONSE_REQUIRED_FIELDS
    assert response_key(response["request_id"]) == DEFAULT_RESPONSE_PREFIX + "req-001"
    assert "ttl" not in response and "expires" not in response
    assert json.loads(json.dumps(response, ensure_ascii=False)) == response


def test_failures_are_distinguishable_and_writes_are_not_replayable():
    assert ERROR_STATUS == {
        "redis_unavailable": 503,
        "worker_timeout": 504,
        "bad_worker_response": 502,
    }
    assert len(set(ERROR_STATUS.values())) == 3
    assert "POST" in WRITE_METHODS
    assert RETRY_ON_TIMEOUT is False


def test_response_key_rejects_missing_correlation_id():
    with pytest.raises(ValueError):
        response_key("")
    with pytest.raises(ValueError):
        response_key(None)
