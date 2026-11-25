# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 企业微信对接层

WECOM_MODE=mock：不联网，用内置示例通讯录，所有应用消息写入本地 outbox（可验证推送与卡片）。
WECOM_MODE=real ：调用企业微信官方 API（通讯录同步 / 应用消息 / 回调加解密）。

企业微信只作触达／轻交互层：卡片只带摘要与「打开工作台」入口，明细一律跳转工作台；
交互层＝成长导航系统·班主任工作台（内嵌），引擎＝本服务岗位智能体。
"""
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from tasks.shared import (config, crypto, db)

_TOKEN_CACHE = {"token": None, "expire": 0}


def _json_get(path, params):
    url = config.WECOM_API + path + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def _json_post(path, params, body):
    url = config.WECOM_API + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def _real_ready():
    return bool(config.WECOM_CORP_ID and config.WECOM_CORP_SECRET and config.WECOM_AGENT_ID)


def access_token():
    if not _real_ready():
        raise RuntimeError("WECOM_MODE=real 但企业微信凭证未配置（corp_id / corp_secret / agent_id）")
    if _TOKEN_CACHE["token"] and time.time() < _TOKEN_CACHE["expire"]:
        return _TOKEN_CACHE["token"]
    r = _json_get("/gettoken", {"corpid": config.WECOM_CORP_ID,
                                "corpsecret": config.WECOM_CORP_SECRET})
    if r.get("errcode") != 0:
        raise RuntimeError("gettoken 失败：%s" % r.get("errmsg"))
    _TOKEN_CACHE["token"] = r["access_token"]
    _TOKEN_CACHE["expire"] = time.time() + int(r.get("expires_in", 7200)) - 180
    return r["access_token"]


# ---------------------------------------------------------------- 通讯录同步
def department_map():
    r = _json_get("/department/list", {"access_token": access_token()})
    if r.get("errcode") != 0:
        raise RuntimeError("department/list 失败：%s" % r.get("errmsg"))
    return {str(d["id"]): d["name"] for d in r.get("department", [])}


def list_users():
    """遍历部门树，返回去重后的成员（含 department / position，用于判定兼任职务）。"""
    token = access_token()
    r = _json_get("/department/list", {"access_token": token})
    if r.get("errcode") != 0:
        raise RuntimeError("department/list 失败：%s" % r.get("errmsg"))
    seen, users = set(), []
    for d in r.get("department", []):
        u = _json_get("/user/list", {"access_token": token,
                                     "department_id": d["id"], "fetch_child": 0})
        if u.get("errcode") != 0:
            continue
        for x in u.get("userlist", []):
            if x["userid"] not in seen:
                seen.add(x["userid"])
                users.append(x)
    return users


def user_get(userid):
    r = _json_get("/user/get", {"access_token": access_token(), "userid": userid})
    return r if r.get("errcode") == 0 else None


# ---------------------------------------------------------------- 应用消息
def send(to_user, msg_type, payload):
    """统一发送入口；real 失败不阻断业务流程，降级记入 outbox 并标 failed。"""
    mode = "mock" if config.WECOM_MODE != "real" else "real"
    result, detail = "mock_sent", ""
    if mode == "real":
        try:
            body = {"touser": to_user, "msgtype": msg_type, "agentid": int(config.WECOM_AGENT_ID)}
            body.update(payload)
            r = _json_post("/message/send", {"access_token": access_token()}, body)
            result = "sent" if r.get("errcode") == 0 else "failed"
            detail = r.get("errmsg", "")
        except Exception as e:
            result, detail = "failed", str(e)[:200]
    db.exec_("INSERT INTO wecom_outbox(ts,to_user,msg_type,payload_json,mode,result) "
             "VALUES(?,?,?,?,?,?)",
             (db.now(), to_user, msg_type, db.dumps(payload), mode, result))
    return {"mode": mode, "result": result, "detail": detail, "to_user": to_user}


def send_text(to_user, text):
    return send(to_user, "text", {"text": {"content": text}})


def send_textcard(to_user, title, description, url):
    return send(to_user, "textcard", {"textcard": {
        "title": title[:128], "description": description[:512],
        "url": url, "btntxt": "打开德育工作台"}})


def outbox(limit=30):
    rows = db.q("SELECT * FROM wecom_outbox ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["payload"] = db.loads(r["payload_json"], {})
    return rows


# ---------------------------------------------------------------- 回调（URL 验证 / 消息）
def verify_url(msg_signature, timestamp, nonce, echostr):
    """GET /api/v1/wecom/callback：返回明文 echostr（企微后台配置时校验）。"""
    if not (config.WECOM_TOKEN and config.WECOM_ENCODING_AES_KEY):
        return None, "回调 Token / EncodingAESKey 未配置"
    return crypto.verify_url(msg_signature, timestamp, nonce, echostr,
                             config.WECOM_TOKEN, config.WECOM_ENCODING_AES_KEY)


def _cdata(s):
    return "<![CDATA[%s]]>" % s


def build_encrypted_reply(reply_text, timestamp, nonce):
    enc = crypto.encrypt(reply_text, config.WECOM_ENCODING_AES_KEY, config.WECOM_CORP_ID)
    sig = crypto.signature(config.WECOM_TOKEN, timestamp, nonce, enc)
    return ("<xml>\n<Encrypt>%s</Encrypt>\n<MsgSignature>%s</MsgSignature>\n"
            "<TimeStamp>%s</TimeStamp>\n<Nonce>%s</Nonce>\n</xml>"
            % (_cdata(enc), _cdata(sig), _cdata(str(timestamp)), _cdata(str(nonce))))


def decrypt_callback(xml_bytes, msg_signature, timestamp, nonce):
    """POST 回调：先验签再解密，返回 (明文消息 dict, 错误)。"""
    if not (config.WECOM_TOKEN and config.WECOM_ENCODING_AES_KEY):
        return None, "回调 Token / EncodingAESKey 未配置"
    try:
        root = ET.fromstring(xml_bytes)
        enc = root.findtext("Encrypt") or ""
    except Exception as e:
        return None, "回调 XML 解析失败：%s" % e
    if crypto.signature(config.WECOM_TOKEN, timestamp, nonce, enc) != msg_signature:
        return None, "签名校验失败"
    try:
        plain, receiveid = crypto.decrypt(enc, config.WECOM_ENCODING_AES_KEY)
    except Exception as e:
        return None, "解密失败：%s" % e
    return {"plain": plain, "receiveid": receiveid}, None


def parse_plain_message(plain):
    try:
        root = ET.fromstring(plain)
        return {"from_user": root.findtext("FromUserName") or "",
                "to_user": root.findtext("ToUserName") or "",
                "msg_type": root.findtext("MsgType") or "text",
                "content": root.findtext("Content") or "",
                "agent_id": root.findtext("AgentID") or ""}
    except Exception:
        return {"from_user": "", "msg_type": "text", "content": plain, "agent_id": ""}


def text_reply_xml(to_user, from_user, content):
    ts = int(time.time())
    return ("<xml>\n<ToUserName>%s</ToUserName>\n<FromUserName>%s</FromUserName>\n"
            "<CreateTime>%d</CreateTime>\n<MsgType>%s</MsgType>\n<Content>%s</Content>\n</xml>"
            % (_cdata(to_user), _cdata(from_user), ts, _cdata("text"), escape(content)))
