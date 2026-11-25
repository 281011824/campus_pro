# -*- coding: utf-8 -*-
"""教官 / 寝管巡查接口：事项目录、学生检索、班级/寝室选择、记录与作废、汇总。

所有端点先过角色守卫：仅教官 / 寝管（及管理员）可进；政教处仅可作废。
"""

import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services import deyu_auth, inspector_auth
from tasks.domain.identity import accounts as school_accounts
from tasks.modules.leader import admins
from tasks.shared import db
from tasks.modules.supervisor import inspection

router = APIRouter()

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ok(data):
    return JSONResponse({"code": 0, "data": data})


def _err(status, message):
    return JSONResponse({"code": status, "message": message}, status_code=status)


async def _json_object(request: Request):
    """解析 JSON 请求体；非对象一律返回 None（由调用方回 400）。"""
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


def _valid_date(value) -> bool:
    text = str(value or "").strip()
    return bool(text) and bool(_DATE_RE.match(text))


def _is_flag(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _display_name(userid):
    try:
        record = school_accounts.get(userid)
    except Exception:
        record = None
    if not record:
        record = admins.get(userid)
    return str((record or {}).get("name") or "")


@router.get("/inspector/me")
async def inspector_me(request: Request):
    """当前巡查账号：userid、姓名与类别。"""
    user, category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    return _ok({"userid": user, "name": _display_name(user), "category": category})


@router.get("/inspector/items")
async def inspector_items(request: Request):
    """固定事项目录：违纪违规 / 仪容仪表 / 卫生检查。"""
    user, _category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    return _ok(inspection.catalog())


@router.get("/inspector/students/search")
async def inspector_students_search(request: Request, q: str = ""):
    """按姓名或学号检索学生（只返回学号、姓名、班级、班主任姓名）。"""
    user, _category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    return _ok({"items": inspection.search_students(q)})


@router.get("/inspector/classes")
async def inspector_classes(request: Request):
    """班级下拉。"""
    user, _category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    return _ok({"items": inspection.classes_for_picker()})


@router.get("/inspector/dorms")
async def inspector_dorms(request: Request):
    """寝室下拉。"""
    user, _category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    return _ok({"items": inspection.dorms_for_picker()})


@router.post("/inspector/records")
async def inspector_record_student(request: Request):
    """学生级记录（违纪违规 / 仪容仪表），同事务镜像德育事件。"""
    user, category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return _err(400, "请求格式错误")
    class_id = str(body.get("class_id") or "").strip()
    student_id = str(body.get("student_id") or "").strip()
    student_no = str(body.get("student_no") or "").strip()
    item_code = str(body.get("item_code") or "").strip()
    if not class_id or (not student_id and not student_no) or not item_code:
        return _err(400, "班级、学生与事项不能为空")
    try:
        data = inspection.create_record(
            user, category, item_code, class_id=class_id, student_id=student_id,
            student_no=student_no, note=body.get("note", ""))
    except ValueError as exc:
        return _err(400, str(exc))
    return _ok(data)


@router.post("/inspector/records/class")
async def inspector_record_class(request: Request):
    """班级级记录（教室卫生 / 清洁区）。"""
    user, category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return _err(400, "请求格式错误")
    class_id = str(body.get("class_id") or "").strip()
    item_code = str(body.get("item_code") or "").strip()
    if not class_id or not item_code:
        return _err(400, "班级与事项不能为空")
    try:
        data = inspection.create_record(
            user, category, item_code, class_id=class_id,
            note=body.get("note", ""))
    except ValueError as exc:
        return _err(400, str(exc))
    return _ok(data)


@router.post("/inspector/records/dorm")
async def inspector_record_dorm(request: Request):
    """寝室级记录（寝室卫生）。

    支持两种入参（二选一）：
    - dorm_id：dorms 表数字主键（下拉选中已入库寝室）
    - dorm_label：房号文本如 3105 / 2号楼3105（下拉未入库或手动输入）
    """
    user, category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return _err(400, "请求格式错误")
    dorm_id = body.get("dorm_id")
    dorm_label = body.get("dorm_label")
    item_code = str(body.get("item_code") or "").strip()
    has_dorm_id = dorm_id not in (None, "")
    has_dorm_label = bool(str(dorm_label or "").strip())
    if not item_code:
        return _err(400, "事项不能为空")
    if not has_dorm_id and not has_dorm_label:
        return _err(400, "请选择寝室或直接输入寝室号")
    try:
        data = inspection.create_record(
            user, category, item_code,
            dorm_id=dorm_id if has_dorm_id else None,
            dorm_label=str(dorm_label).strip() if has_dorm_label else None,
            note=body.get("note", ""))
    except ValueError as exc:
        return _err(400, str(exc))
    return _ok(data)


@router.get("/inspector/records")
async def inspector_records(request: Request, date: str = "", category: str = "",
                            mine: str = "", limit: str = "50"):
    """按日期 / 类别 / 记录人查询；mine=1 时只看本人。"""
    user, viewer_category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    if date and not _valid_date(date):
        return _err(400, "日期格式应为 YYYY-MM-DD")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return _err(400, "数量参数格式错误")
    operator = user if _is_flag(mine) else None
    try:
        items = inspection.list_records(date or None, category, operator, limit)
    except ValueError as exc:
        return _err(400, str(exc))
    is_admin = admins.is_active_admin(user)
    is_deyu = deyu_auth.is_deyu_account(user)
    for it in items:
        it["can_void"] = inspection.can_void(
            it, user, viewer_category, is_admin, is_deyu)
    return _ok({"items": items})


@router.post("/inspector/records/{record_id}/void")
async def inspector_record_void(request: Request, record_id: str):
    """撤回 / 作废记录：本人当日、政教处或管理员。"""
    user, category, is_admin, is_deyu = inspector_auth.void_allowed(request)
    if not user:
        if inspector_auth.has_any_session(request):
            return _err(403, "无巡查权限")
        return _err(401, "未登录或登录已过期")
    body = {}
    if await request.body():
        parsed = await _json_object(request)
        if parsed is None:
            return _err(400, "请求格式错误")
        body = parsed
    reason = str(body.get("reason") or "")
    result = inspection.void_record(user, category, record_id, reason,
                                    is_admin=is_admin, is_deyu=is_deyu)
    if not result.get("ok"):
        return _err(403 if result.get("forbidden") else 400,
                    result.get("error") or "作废失败")
    return _ok({"id": result["id"], "status": result["status"],
                "summary": result["summary"]})


@router.get("/inspector/summary")
async def inspector_summary(request: Request, date: str = ""):
    """当日汇总：三类条数与净分。"""
    user, _category, denied = inspector_auth.inspector_or_401(request)
    if denied:
        return denied
    if date and not _valid_date(date):
        return _err(400, "日期格式应为 YYYY-MM-DD")
    return _ok(inspection.summary_today(date or None))
