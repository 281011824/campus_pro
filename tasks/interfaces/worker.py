# -*- coding: utf-8 -*-
"""班主任工作台独立 Redis worker；不启动 HTTP 服务。"""
import base64
from datetime import datetime
import json
import logging
import signal
import threading
import urllib.parse

import redis

from tasks.modules.head_teacher import (coedu, push, secretary)
from tasks.domain.collaboration import federation
from tasks.domain.growth import growth
from tasks.domain.identity import org
from tasks.interfaces import server
from tasks.modules.head_teacher import writes
from tasks.shared import (config, db, wecom)
from tasks.interfaces.contract import (DEFAULT_REDIS_URL, DEFAULT_REQUEST_QUEUE, DEFAULT_RESPONSE_PREFIX, DEFAULT_RESPONSE_TTL_SECONDS, JSON_CONTENT_TYPE, REDIS_URL_ENV, REQUEST_QUEUE_ENV, RESPONSE_PREFIX_ENV, RESPONSE_TTL_ENV, TEXT_CONTENT_TYPE, XML_CONTENT_TYPE)

LOGGER = logging.getLogger("head_teacher_workbench.worker")


def _response(request_id, status, content_type, body):
    return {
        "request_id": request_id,
        "status": status,
        "content_type": content_type,
        "body": body,
    }


def _json_response(request_id, status, value):
    return _response(request_id, status, JSON_CONTENT_TYPE,
                     json.dumps(value, ensure_ascii=False))


def _raw_body(request):
    encoded = request.get("raw_body") or ""
    return base64.b64decode(encoded.encode("ascii"), validate=True) if encoded else b""


def _normal_body(request, raw):
    if request.get("body") is not None:
        return request["body"]
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        raise server.ApiError(400, "bad_json", "请求体不是合法 JSON")


def _wecom_verify(request_id, query):
    plain, err = wecom.verify_url(
        query.get("msg_signature", ""), query.get("timestamp", ""),
        query.get("nonce", ""), query.get("echostr", ""))
    if err:
        return _response(request_id, 403, TEXT_CONTENT_TYPE, err)
    return _response(request_id, 200, TEXT_CONTENT_TYPE, plain)


def _wecom_callback(request_id, query, raw):
    """保留企微原始 XML 解密、秘书处理与加密 XML 响应链。"""
    dec, err = wecom.decrypt_callback(
        raw, query.get("msg_signature", ""), query.get("timestamp", ""),
        query.get("nonce", ""))
    if err:
        return _response(request_id, 403, TEXT_CONTENT_TYPE, err)
    msg = wecom.parse_plain_message(dec["plain"])
    userid, text = msg["from_user"], msg["content"]

    row = db.q(
        "SELECT s.session_id FROM sessions s WHERE s.user_id=? AND s.status='active' "
        "ORDER BY s.created_at DESC LIMIT 1", (userid,), one=True)
    if row:
        ctx = server.full_ctx(row["session_id"])
    else:
        resolved, resolve_error = org.resolve(userid)
        if resolve_error:
            reply = "企业微信通讯录中无该账号的有效职务，请联系政教处核对。"
            xml = wecom.text_reply_xml(msg["to_user"], userid, reply)
            encrypted = wecom.build_encrypted_reply(
                xml, query.get("timestamp"), query.get("nonce"))
            return _response(request_id, 200, XML_CONTENT_TYPE, encrypted)
        ctx = server.full_ctx(resolved["session_id"])

    result = secretary.handle(ctx, text, writes.pending_for(ctx["session_id"]))
    if result.get("audit"):
        audit = result["audit"]
        db.audit(ctx, audit[0], audit[1], audit[2], audit[3] if len(audit) > 3 else "")
    reply = result["text"]
    if result.get("pending_id"):
        reply = "写入类操作需在德育工作台完成回显确认，请在企微卡片中打开工作台办理。"
    elif len(reply) > 400:
        reply = reply[:400] + "…（明细请打开德育工作台查看）"
    else:
        reply += "\n\n明细请打开德育工作台查看。"
    if result.get("persist"):
        db.exec_(
            "INSERT INTO chat_turns(ts,session_id,role,text,card_json) VALUES(?,?,?,?,?)",
            (db.now(), ctx["session_id"], "user", text, None))
    xml = wecom.text_reply_xml(msg["to_user"], userid, reply)
    encrypted = wecom.build_encrypted_reply(
        xml, query.get("timestamp"), query.get("nonce"))
    return _response(request_id, 200, XML_CONTENT_TYPE, encrypted)


def handle_request(request):
    """执行一条契约消息，统一返回 HTTP 状态、content type 与 UTF-8 文本。"""
    request_id = str(request.get("request_id") or "")
    try:
        method = str(request.get("method") or "").upper()
        path = str(request.get("path") or "/").rstrip("/") or "/"
        query = {
            key: values[0]
            for key, values in urllib.parse.parse_qs(str(request.get("query") or "")).items()
        }
        server._TRUSTED_IDENTITY = str(request.get("X-Auth-User") or "").strip()
        raw = _raw_body(request)
        if path == "/api/v1/wecom/callback" and method == "GET":
            return _wecom_verify(request_id, query)
        if path == "/api/v1/wecom/callback" and method == "POST":
            return _wecom_callback(request_id, query, raw)
        body = _normal_body(request, raw) if method == "POST" else {}
        return _json_response(request_id, 200, server.ok(server.route(method, path, query, body)))
    except server.ApiError as exc:
        return _json_response(request_id, exc.status,
                              {"code": exc.code, "error": exc.message, "data": None})
    except growth.Forbidden as exc:
        return _json_response(request_id, 403,
                              {"code": "derived_zone_forbidden", "error": str(exc), "data": None})
    except federation.PollutionDetected as exc:
        return _json_response(request_id, 500,
                              {"code": "context_pollution", "error": str(exc), "data": None})
    except coedu.ContextPolluted as exc:
        return _json_response(request_id, 500,
                              {"code": "context_pollution", "error": str(exc), "data": None})
    except coedu.CoeduForbidden as exc:
        return _json_response(request_id, 403,
                              {"code": "coedu_forbidden", "error": str(exc), "data": None})
    except Exception as exc:
        return _json_response(request_id, 500,
                              {"code": "internal_error", "error": str(exc)[:300], "data": None})


def publish_response(redis_client, response, response_prefix, ttl_seconds):
    """以 String 响应键配合 Web 的 GET 轮询；TTL 只作为 Redis 元数据。"""
    key = response_prefix + response["request_id"]
    redis_client.set(key, json.dumps(response, ensure_ascii=False), ex=ttl_seconds)


def consume_payload(redis_client, payload, response_prefix, ttl_seconds):
    request = json.loads(payload)
    if not isinstance(request, dict) or not request.get("request_id"):
        raise ValueError("request_id must be a non-empty string")
    response = handle_request(request)
    publish_response(redis_client, response, response_prefix, ttl_seconds)
    return response


def scheduler(stop_event):
    """单 worker 内每分钟承接推送、周报与催办超时升级。"""
    last_minute = None
    while not stop_event.is_set():
        now = datetime.now()
        key = now.strftime("%Y-%m-%d %H:%M")
        if key != last_minute:
            last_minute = key
            try:
                fired = push.run_due(now)
                weekly = push.weekly_due(now)
                escalated = push.escalate_overdue(now)
                if fired or weekly or escalated:
                    LOGGER.info("scheduler minute=%s push=%d weekly=%d escalated=%d",
                                key, len(fired), len(weekly), len(escalated))
            except Exception as exc:
                LOGGER.error("scheduler failure type=%s", type(exc).__name__)
        stop_event.wait(10)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db.init_db()
    info = org.sync_directory()

    redis_url = config.get(REDIS_URL_ENV, DEFAULT_REDIS_URL)
    request_queue = config.get(REQUEST_QUEUE_ENV, DEFAULT_REQUEST_QUEUE)
    response_prefix = config.get(RESPONSE_PREFIX_ENV, DEFAULT_RESPONSE_PREFIX)
    ttl_seconds = int(config.get(RESPONSE_TTL_ENV, str(DEFAULT_RESPONSE_TTL_SECONDS)))
    if ttl_seconds <= 0:
        raise ValueError("response TTL must be positive")

    redis_client = redis.Redis.from_url(
        redis_url, decode_responses=True, encoding="utf-8",
        socket_connect_timeout=3, socket_timeout=3)
    redis_client.ping()
    stop_event = threading.Event()

    def stop(_signum=None, _frame=None):
        stop_event.set()

    handled_signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        handled_signals.append(signal.SIGBREAK)
    for signal_name in handled_signals:
        signal.signal(signal_name, stop)

    scheduler_thread = None
    if config.flag("ENABLE_SCHEDULER", False):
        scheduler_thread = threading.Thread(
            target=scheduler, args=(stop_event,), name="head-teacher-scheduler", daemon=True)
        scheduler_thread.start()

    LOGGER.info("worker started queue=%s posts=%d scheduler=%s",
                request_queue, info["posts"], bool(scheduler_thread))
    try:
        while not stop_event.is_set():
            try:
                item = redis_client.blpop(request_queue, timeout=1)
                if not item:
                    continue
                _queue, payload = item
                try:
                    response = consume_payload(
                        redis_client, payload, response_prefix, ttl_seconds)
                    LOGGER.info("request_id=%s status=%d",
                                response["request_id"], response["status"])
                except (ValueError, TypeError, json.JSONDecodeError):
                    LOGGER.warning("discarded malformed request payload")
            except redis.RedisError as exc:
                LOGGER.error("redis failure type=%s", type(exc).__name__)
                stop_event.wait(1)
    finally:
        stop_event.set()
        if scheduler_thread:
            scheduler_thread.join(timeout=12)
        redis_client.close()
        LOGGER.info("worker stopped")


if __name__ == "__main__":
    main()
