# -*- coding: utf-8 -*-
"""学生成长分享：本人创建/撤销分享码，访客凭码换取只读 token 查看摘要。

安全口径：
- 分享码 8 位，`secrets` 生成，库里只存 sha256；明文只回给本人一次。
- 校验 1 分钟内失败超过 10 次 → 429，并写 access_log。
- 内容白名单：昵称（姓+*）、班级、画像摘要、时间轴标题；
  绝不含学号、姓名全称、家长电话、原始作答、维度原始分。
- 过期 / 撤销统一 404「分享已失效」。

路由由 app.main 显式注册（模块标记 _active=False，避免与自动注册重复）。
"""

import base64
import hashlib
import hmac
import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.initializer import g
from app.services import student_auth
from tasks.modules.student import student_portal as portal

router = APIRouter()
_active = False

TOKEN_TTL_SECONDS = 1800


def _ok(data):
    return {"code": 0, "message": "", "data": data}


def _err(status, message):
    return JSONResponse({"code": status, "message": message, "data": None},
                        status_code=status)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _secret() -> bytes:
    return str(g.config.AUTH_COOKIE_SECRET or "").encode("utf-8")


def sign_token(share_id: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    """访客只读 token：只含分享 id 与过期时间，HMAC 签名。"""
    body = _b64(json.dumps({"s": str(share_id), "e": int(time.time()) + ttl},
                           separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return "%s.%s" % (body, sig)


def read_token(token: str) -> str:
    """返回 share_id；签名错误或过期返回空串。"""
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
    return str(payload.get("s") or "")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/student/shares")
async def create_share(request: Request):
    """创建分享：hours 默认 24，上限 168。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        result = portal.create_share(stu["class_id"], stu["student_id"],
                                     body.get("hours", 24))
        return _ok({"id": result["id"], "code": result["code"],
                    "expires_at": result["expires_at"], "url": result["url"]})
    except portal.PortalError as exc:
        return _err(getattr(exc, "status", 400), str(exc))


@router.get("/student/shares")
async def list_shares(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok({"items": portal.list_shares(stu["student_id"])})


@router.delete("/student/shares/{share_id}")
async def revoke_share(request: Request, share_id: str):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        portal.revoke_share(stu["student_id"], share_id)
        return _ok({"deleted": True})
    except portal.PortalError as exc:
        return _err(getattr(exc, "status", 400), str(exc))


@router.post("/share/verify")
async def verify_share(request: Request):
    """访客校验分享码 → 只读 token；失败过多 429。"""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    try:
        share = portal.verify_share(body.get("code"), _client_ip(request))
        return _ok({"token": sign_token(share["id"])})
    except portal.PortalError as exc:
        return _err(getattr(exc, "status", 400), str(exc))


@router.get("/share/{token}/content")
async def share_content(request: Request, token: str):
    """分享内容白名单（公开只读）。"""
    share_id = read_token(token)
    if not share_id:
        return _err(404, "分享已失效")
    try:
        return _ok(portal.share_content(share_id))
    except portal.PortalError:
        return _err(404, "分享已失效")
