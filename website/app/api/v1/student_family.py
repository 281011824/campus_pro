# -*- coding: utf-8 -*-
"""家长端：绑定、登录、退出与四个只读页面数据。

安全口径：
- 家长会话独立 Cookie（htw_parent），HMAC 同密钥；每次请求回查绑定是否仍有效。
- 只能看绑定学生；未绑定 / 已撤回 / 越权一律 403 并写审计。
- 只给画像摘要、时间轴、待办；不含原始作答与维度原始分。

路由由 app.main 显式注册（模块标记 _active=False，避免与自动注册重复）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services import student_auth
from tasks.modules.student import student_portal as portal

router = APIRouter()
_active = False


def _ok(data):
    return {"code": 0, "message": "", "data": data}


def _err(status, message):
    return JSONResponse({"code": status, "message": message, "data": None},
                        status_code=status)


async def _json_body(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise portal.InvalidInput("请求格式错误")
    if not isinstance(payload, dict):
        raise portal.InvalidInput("请求格式错误")
    return payload


def _set_parent_cookie(response, binding_id, class_id, student_id):
    token = student_auth.sign_parent_session({
        "id": binding_id, "class_id": class_id, "student_id": student_id})
    response.set_cookie(
        student_auth.PARENT_COOKIE, token,
        max_age=student_auth.PARENT_TTL_SECONDS,
        path="/", httponly=True, samesite="lax",
    )
    return response


@router.post("/family/bind")
async def family_bind(request: Request):
    """家长凭绑定码绑定学生；密码≥6 位。"""
    try:
        body = await _json_body(request)
        result = portal.bind_parent(body.get("student_no"), body.get("code"),
                                    body.get("password"))
    except portal.PortalError as exc:
        return _err(getattr(exc, "status", 400), str(exc))
    response = JSONResponse(_ok({
        "binding_id": result["binding_id"], "class_id": result["class_id"],
        "student_id": result["student_id"],
    }))
    return _set_parent_cookie(response, result["binding_id"],
                              result["class_id"], result["student_id"])


@router.post("/family/login")
async def family_login(request: Request):
    """家长登录：学号 + 自设密码。"""
    try:
        body = await _json_body(request)
        result = portal.parent_login(body.get("student_no"), body.get("password"))
    except portal.PortalError:
        return _err(401, "学号或密码错误")
    response = JSONResponse(_ok({"binding_id": result["binding_id"],
                                 "class_id": result["class_id"],
                                 "student_id": result["student_id"]}))
    return _set_parent_cookie(response, result["binding_id"],
                              result["class_id"], result["student_id"])


@router.post("/family/logout")
async def family_logout():
    response = JSONResponse(_ok({"logged_out": True}))
    response.delete_cookie(student_auth.PARENT_COOKIE, path="/")
    return response


@router.get("/family/home")
async def family_home(request: Request):
    binding, err = student_auth.parent_or_error(request)
    if err:
        return err
    try:
        return _ok(portal.parent_home(binding))
    except portal.PortalError as exc:
        return _err(getattr(exc, "status", 400), str(exc))


@router.get("/family/timeline")
async def family_timeline(request: Request, type: str = "all", page: int = 1, size: int = 20):
    binding, err = student_auth.parent_or_error(request)
    if err:
        return err
    try:
        return _ok(portal.parent_timeline(binding, type, page, size))
    except portal.PortalError as exc:
        return _err(getattr(exc, "status", 400), str(exc))


@router.get("/family/profile")
async def family_profile(request: Request):
    binding, err = student_auth.parent_or_error(request)
    if err:
        return err
    return _ok(portal.parent_profile(binding))


@router.get("/family/todos")
async def family_todos(request: Request):
    binding, err = student_auth.parent_or_error(request)
    if err:
        return err
    return _ok(portal.parent_todos(binding))
