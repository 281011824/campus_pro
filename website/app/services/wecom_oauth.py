"""企业微信 OAuth2 网页授权：协议调用与会话签名，不含业务规则。

默认关闭。只有同时配置 corp_id / agent_id / secret / cookie_secret
且 WECOM_OAUTH_ENABLED=true 时才生效，避免影响现有访问方式。
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse

import httpx

from app.initializer import g

AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"
GET_TOKEN_URL = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
GET_USERINFO_URL = "https://qyapi.weixin.qq.com/cgi-bin/auth/getuserinfo"

SESSION_COOKIE = "htw_session"
STATE_COOKIE = "htw_oauth_state"
SESSION_TTL_SECONDS = 8 * 3600


class WecomOAuthError(Exception):
    """企微接口返回异常或配置缺失。"""


def is_enabled() -> bool:
    return bool(
        g.config.WECOM_OAUTH_ENABLED
        and g.config.WECOM_CORP_ID
        and g.config.WECOM_AGENT_ID
        and g.config.WECOM_SECRET
        and g.config.AUTH_COOKIE_SECRET
    )


def auth_required() -> bool:
    """只要配置了任一登录方式，就必须持有效会话，不再信任请求头身份。

    除企微 OAuth 与 LOCAL_LOGIN_USERS 外，只要配置了会话签名密钥，
    管理员/教师账号（SQLite 账号表）即可登录，同样属于已启用登录，
    必须关闭 X-Auth-User 旁路，避免未带 Cookie 也能冒充管理员。
    """
    return bool(
        is_enabled()
        or g.config.LOCAL_LOGIN_USERS
        or g.config.AUTH_COOKIE_SECRET
    )


def authorize_url(state: str) -> str:
    redirect_uri = g.config.WECOM_OAUTH_REDIRECT_URI
    if not redirect_uri:
        raise WecomOAuthError("未配置 WECOM_OAUTH_REDIRECT_URI")
    query = urllib.parse.urlencode({
        "appid": g.config.WECOM_CORP_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "snsapi_base",
        "state": state,
        "agentid": g.config.WECOM_AGENT_ID,
    })
    return f"{AUTHORIZE_URL}?{query}#wechat_redirect"


async def fetch_userid(code: str) -> str:
    """code -> 企微 UserId。snsapi_base 静默授权，不弹确认页。"""
    if not code:
        raise WecomOAuthError("缺少 code")
    async with httpx.AsyncClient(timeout=8.0) as client:
        token_resp = await client.get(GET_TOKEN_URL, params={
            "corpid": g.config.WECOM_CORP_ID,
            "corpsecret": g.config.WECOM_SECRET,
        })
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise WecomOAuthError(
                f"获取 access_token 失败：{token_data.get('errmsg')}"
            )
        user_resp = await client.get(GET_USERINFO_URL, params={
            "access_token": access_token,
            "code": code,
        })
        user_data = user_resp.json()
        userid = user_data.get("userid") or user_data.get("UserId")
        if not userid:
            raise WecomOAuthError(f"未取到 userid：{user_data.get('errmsg')}")
        return userid


def new_state() -> str:
    return secrets.token_urlsafe(16)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _secret() -> bytes:
    return g.config.AUTH_COOKIE_SECRET.encode("utf-8")


def sign_session(userid: str, ttl: int = SESSION_TTL_SECONDS) -> str:
    payload = json.dumps(
        {"u": userid, "e": int(time.time()) + ttl},
        separators=(",", ":"),
    ).encode("utf-8")
    body = _b64(payload)
    sig = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_session(token: str) -> str:
    """返回 userid；签名错误、格式错误或已过期时返回空串。"""
    if not token or "." not in token or not _secret():
        return ""
    body, sig = token.rsplit(".", 1)
    expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return ""
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return ""
    if int(payload.get("e", 0)) < int(time.time()):
        return ""
    return str(payload.get("u") or "")
