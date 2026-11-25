# -*- coding: utf-8 -*-
"""后台管理台 JSON 接口。

全部端点强制 require_admin 服务端鉴权（见 app.services.admin_auth），
绝不信客户端传入的身份；所有写操作留审计（db.audit，detail 不写明文密码）。
"""

import io
import json
from urllib.parse import quote

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services import admin_auth
from tasks.domain.identity import (accounts as school_accounts, classes)
from tasks.shared import db
from tasks.modules.leader import admins
from tasks.modules.supervisor import dorms
from tasks.modules.head_teacher import roster
from tasks.modules.student import student_accounts

router = APIRouter(prefix="/admin")

DEFAULT_PASSWORD = "123456"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# --------------------------------------------------------------- 工具
def _guard(request: Request):
    """返回 (admin_userid, None) 或 (None, error_response)。"""
    admin = admin_auth.current_admin(request)
    if admin:
        return admin, None
    if admin_auth.has_any_session(request):
        return None, JSONResponse({"code": 403, "message": "无管理员权限"}, status_code=403)
    return None, JSONResponse({"code": 401, "message": "未登录或登录已过期"}, status_code=401)


def _ok(data=None, **extra):
    payload = {"code": 0, "message": "ok", "data": data}
    payload.update(extra)
    return payload


def _fail(message: str, status: int = 400):
    return JSONResponse({"code": status, "message": message}, status_code=status)


def _audit(admin: str, action: str, resource: str = "", detail: str = ""):
    try:
        db.audit({"user_id": admin, "level": "admin"}, action,
                 resource=resource, detail=str(detail)[:500])
    except Exception:
        pass


async def _json(request: Request):
    try:
        body = await request.json()
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def _xlsx(workbook, filename: str):
    # roster._workbook 返回的是已序列化的 bytes；兼容传入 Workbook 对象的情况
    if isinstance(workbook, (bytes, bytearray)):
        data = bytes(workbook)
    else:
        buf = io.BytesIO()
        workbook.save(buf)
        data = buf.getvalue()
    headers = {"Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(filename)}
    return StreamingResponse(io.BytesIO(data), media_type=XLSX_MEDIA, headers=headers)


CLASS_HEADERS = ["班级编号", "班级名称", "年级", "专业设置", "班主任姓名", "学生数", "状态"]
CLASS_WIDTHS = [14, 18, 10, 20, 14, 10, 10]


def _classes_workbook(items):
    """班级列表导出为 xlsx（表头加底色，冻结首行）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "班级列表"
    ws.append(CLASS_HEADERS)
    for i, w in enumerate(CLASS_WIDTHS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    head_fill = PatternFill("solid", fgColor="E8EEF7")
    for cell in ws[1]:
        cell.fill = head_fill
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for it in items:
        status = "停用" if str(it.get("status") or "") == "停用" else "启用"
        ws.append([it.get("class_id", ""), it.get("name", ""), it.get("grade", ""),
                   it.get("major", ""), it.get("head_teacher_name", ""),
                   it.get("student_count", 0), status])
    ws.freeze_panes = "A2"
    return wb


# --------------------------------------------------------------- 通用
@router.get("/me")
async def me(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    rec = admins.get(admin)
    return _ok({"userid": rec["userid"], "name": rec["name"],
                "role": rec.get("role"), "last_login_at": rec.get("last_login_at")})


@router.get("/dashboard")
async def dashboard(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    recent = db.q("SELECT ts,user_id,action,resource,result,detail FROM audit_logs "
                  "WHERE level='admin' ORDER BY ts DESC LIMIT 10")
    return _ok({
        "kpi": {
            "teachers": school_accounts.count(),
            "students": roster.count_all_students(),
            "classes": classes.count(),
            "dorms": dorms.count(),
            "admins": admins.count(),
            "student_accounts": student_accounts.count(),
        },
        "recent_audit": [dict(r) for r in recent],
    })


@router.get("/audit")
async def audit_list(request: Request, limit: int = 100):
    admin, err = _guard(request)
    if err:
        return err
    limit = max(1, min(500, int(limit or 100)))
    rows = db.q("SELECT ts,user_id,action,resource,result,detail FROM audit_logs "
                "ORDER BY ts DESC LIMIT ?", (limit,))
    return _ok([dict(r) for r in rows])


@router.post("/password/change")
async def change_password(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    old = str(body.get("old_password") or "")
    new = str(body.get("new_password") or "")
    if not old or not new:
        return _fail("旧密码和新密码不能为空")
    if len(new) < 6:
        return _fail("新密码至少 6 位")
    if not admins.verify_password(admin, old):
        return _fail("旧密码不正确")
    admins.set_password(admin, new)
    _audit(admin, "admin:change_password", resource=admin, detail="self")
    return _ok()


# --------------------------------------------------------------- 学生管理
@router.get("/students")
async def students_list(request: Request, q: str = "", class_id: str = "",
                        page: int = 1, size: int = 50):
    admin, err = _guard(request)
    if err:
        return err
    return _ok(roster.list_all_students(q, class_id, page, size))


@router.get("/students/export")
async def students_export(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    _audit(admin, "student:export", detail="all")
    return _xlsx(roster.admin_export_students(), "学生名册.xlsx")


@router.get("/students/template")
async def students_template(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    return _xlsx(roster.template("admin_students"), "学生名册导入模板.xlsx")


@router.post("/students/import")
async def students_import(request: Request, file: UploadFile = File(...)):
    admin, err = _guard(request)
    if err:
        return err
    data = await file.read()
    try:
        result = roster.admin_import_students(data)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "student:import",
           detail="added=%d updated=%d skipped=%d" %
                  (result["added"], result["updated"], result["skipped"]))
    return _ok(result)


@router.post("/students")
async def student_create(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        stu = roster.create_student(
            body.get("class_id"), body.get("student_id"), body.get("name"),
            body.get("gender", ""), body.get("dorm", ""), body.get("address", ""),
            body.get("phone", ""), body.get("guardian_phone", ""),
            body.get("status", "在读"), body.get("major", ""), body.get("grade", ""),
            body.get("boarding_type", ""), body.get("guardian_name", ""),
            body.get("guardian_relation", ""), body.get("bed_no", ""))
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "student:create", resource="%s/%s" % (stu["class_id"], stu["student_id"]),
           detail=stu.get("name", ""))
    return _ok(stu)


@router.post("/students/transfer")
async def student_transfer(request: Request):
    """批量转班：迁移学生主数据与学生账号，历史数据按原班级保留。"""
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    refs = body.get("students")
    if not isinstance(refs, list) or not refs:
        return _fail("请先选择要转班的学生")
    target = str(body.get("target_class_id") or "").strip()
    try:
        result = roster.transfer_students(refs, target, operator=admin)
    except ValueError as e:
        _audit(admin, "student:transfer", resource=target, detail="失败：%s" % e)
        return _fail(str(e), 400)
    _audit(admin, "student:transfer", resource=target,
           detail="转班 %d 人" % result["moved"])
    return _ok(result)


@router.put("/students/{class_id}/{student_id}")
async def student_update(request: Request, class_id: str, student_id: str):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    # body 可能带 class_id/student_id（调班/改学号），与路径参数同名，取出后避免重复传参
    new_class_id = body.pop("class_id", None)
    new_student_id = body.pop("student_id", None)
    try:
        stu = roster.update_student(
            class_id, student_id,
            new_class_id=new_class_id, new_student_id=new_student_id, **body)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "student:update",
           resource="%s/%s" % (stu.get("class_id"), stu.get("student_id")),
           detail=stu.get("name", ""))
    return _ok(stu)


@router.delete("/students/{class_id}/{student_id}")
async def student_delete(request: Request, class_id: str, student_id: str):
    admin, err = _guard(request)
    if err:
        return err
    try:
        roster.delete_student(class_id, student_id)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "student:delete", resource="%s/%s" % (class_id, student_id))
    return _ok()


# --------------------------------------------------------------- 班级管理
@router.get("/classes")
async def classes_list(request: Request, q: str = "", status: str = ""):
    admin, err = _guard(request)
    if err:
        return err
    return _ok(classes.list(q, status))


@router.get("/classes/export")
async def classes_export(request: Request):
    """导出全校班级列表（含专业、班主任、学生数）。"""
    admin, err = _guard(request)
    if err:
        return err
    _audit(admin, "class:export", detail="all")
    return _xlsx(_classes_workbook(classes.list()), "班级列表.xlsx")


@router.post("/classes")
async def class_create(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        item = classes.create(body.get("class_id"), body.get("name", ""),
                              body.get("grade", ""), "",
                              body.get("status", "active"), body.get("major", ""))
        if "head_teacher_userid" in body:
            item = classes.set_head_teacher(item["class_id"], body.get("head_teacher_userid"))
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "class:create", resource=item["class_id"], detail=item.get("name", ""))
    return _ok(item)


@router.post("/classes/major")
async def classes_set_major(request: Request):
    """批量设置多个班级的专业（major 为空表示清空）。"""
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    class_ids = body.get("class_ids") or []
    if not isinstance(class_ids, list) or not class_ids:
        return _fail("请选择班级")
    result = classes.set_majors(class_ids, body.get("major", ""))
    _audit(admin, "class:set_major", resource=",".join(result["class_ids"]),
           detail="major=%s updated=%d" % (str(body.get("major") or ""), result["updated"]))
    return _ok(result)


@router.put("/classes/{class_id}")
async def class_update(request: Request, class_id: str):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        item = classes.update(class_id, name=body.get("name"), grade=body.get("grade"),
                              status=body.get("status"), major=body.get("major"))
        if "head_teacher_userid" in body:
            item = classes.set_head_teacher(class_id, body.get("head_teacher_userid"))
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "class:update", resource=class_id)
    return _ok(item)


@router.get("/headteachers/candidates")
async def headteacher_candidates(request: Request):
    """班主任下拉候选：由「班主任管理」指定的教职工名单。"""
    admin, err = _guard(request)
    if err:
        return err
    return _ok(school_accounts.headteachers_for_select())


@router.get("/headteachers")
async def headteachers_list(request: Request, q: str = "", page: int = 1, size: int = 50):
    """全部教职工及班主任指定状态。"""
    admin, err = _guard(request)
    if err:
        return err
    return _ok(school_accounts.headteacher_overview(q, page, size))


@router.post("/headteachers/set")
async def headteachers_set(request: Request):
    """指定 / 取消指定班主任；取消时同步解除其班级绑定。"""
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    userid = str(body.get("userid") or "").strip()
    enabled = bool(body.get("enabled"))
    try:
        item = school_accounts.pool_set(userid, enabled)
    except ValueError as e:
        return _fail(str(e), 400)
    unbound = 0 if enabled else classes.unbind_head_teacher(userid)
    _audit(admin, "headteacher:enable" if enabled else "headteacher:disable",
           resource=userid, detail=("" if enabled else "解除班级 %s 个" % unbound))
    return _ok({"userid": userid, "enabled": enabled, "unbound_classes": unbound,
                "name": item.get("name", "")})


@router.delete("/classes/{class_id}")
async def class_delete(request: Request, class_id: str):
    admin, err = _guard(request)
    if err:
        return err
    try:
        classes.delete(class_id)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "class:delete", resource=class_id)
    return _ok()


# --------------------------------------------------------------- 寝室管理
@router.get("/dorms")
async def dorms_list(request: Request, q: str = "", status: str = ""):
    admin, err = _guard(request)
    if err:
        return err
    return _ok(dorms.list(q, status))


@router.post("/dorms")
async def dorm_create(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        item = dorms.create(body.get("building", ""), body.get("room_no", ""),
                            body.get("gender", ""), body.get("capacity", 6),
                            body.get("status", "active"))
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "dorm:create", resource=item["label"])
    return _ok(item)


@router.put("/dorms/{dorm_id}")
async def dorm_update(request: Request, dorm_id: int):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        item = dorms.update(dorm_id, building=body.get("building"), room_no=body.get("room_no"),
                            gender=body.get("gender"), capacity=body.get("capacity"),
                            status=body.get("status"))
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "dorm:update", resource=str(dorm_id))
    return _ok(item)


@router.delete("/dorms/{dorm_id}")
async def dorm_delete(request: Request, dorm_id: int):
    admin, err = _guard(request)
    if err:
        return err
    try:
        dorms.delete(dorm_id)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "dorm:delete", resource=str(dorm_id))
    return _ok()


# --------------------------------------------------------------- 教师/领导账号
@router.get("/accounts/teachers")
async def teachers_list(request: Request, q: str = "", category: str = "",
                        page: int = 1, size: int = 50):
    admin, err = _guard(request)
    if err:
        return err
    return _ok(school_accounts.list(q, category, page, size))


@router.post("/accounts/teachers")
async def teacher_upsert(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        item = school_accounts.upsert(
            body.get("userid"), body.get("name"), body.get("password"),
            body.get("wecom_userid", ""), body.get("dept", ""), body.get("post_name", ""),
            body.get("category", "教师"), body.get("status", "本校"))
        if "is_headteacher" in body:
            enabled = bool(body.get("is_headteacher"))
            school_accounts.pool_set(item["userid"], enabled)
            if not enabled:
                classes.unbind_head_teacher(item["userid"])
            item["is_headteacher"] = enabled
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "teacher:upsert", resource=body.get("userid"), detail=item.get("name", ""))
    return _ok(item)


@router.post("/accounts/teachers/{userid}/reset-password")
async def teacher_reset_password(request: Request, userid: str):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    new_pwd = str(body.get("password") or DEFAULT_PASSWORD)
    try:
        school_accounts.set_password(userid, new_pwd)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "teacher:reset_password", resource=userid, detail="reset")
    return _ok({"password": new_pwd})


@router.post("/accounts/teachers/{userid}/toggle-status")
async def teacher_toggle_status(request: Request, userid: str):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        item = school_accounts.set_status(userid, body.get("status", "停用"))
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "teacher:toggle_status", resource=userid, detail=item.get("status", ""))
    return _ok(item)


@router.delete("/accounts/teachers/{userid}")
async def teacher_delete(request: Request, userid: str):
    admin, err = _guard(request)
    if err:
        return err
    try:
        school_accounts.delete(userid)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "teacher:delete", resource=userid)
    return _ok()


@router.get("/accounts/teachers/export")
async def teachers_export(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    _audit(admin, "teacher:export", detail="all")
    return _xlsx(roster.export_teachers(), "教师账号.xlsx")


@router.get("/accounts/teachers/template")
async def teachers_template(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    return _xlsx(roster.template("teachers"), "教师账号导入模板.xlsx")


@router.post("/accounts/teachers/import")
async def teachers_import(request: Request, file: UploadFile = File(...)):
    admin, err = _guard(request)
    if err:
        return err
    data = await file.read()
    try:
        result = roster.import_teachers(data)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "teacher:import", detail="imported=%d" % result.get("imported", 0))
    return _ok(result)


# --------------------------------------------------------------- 学生账号
@router.get("/accounts/students")
async def student_accounts_list(request: Request, class_id: str = "", q: str = "",
                                status: str = "", page: int = 1, size: int = 50):
    admin, err = _guard(request)
    if err:
        return err
    return _ok(student_accounts.list(class_id, q, status, page, size))


@router.post("/accounts/students/generate")
async def student_accounts_generate(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    class_id = str(body.get("class_id") or "")
    password = str(body.get("password") or DEFAULT_PASSWORD)
    result = student_accounts.generate(class_id, password)
    _audit(admin, "student_account:generate", resource=class_id or "all",
           detail="generated=%d" % result["generated"])
    return _ok(result)


@router.post("/accounts/students/reset-password")
async def student_account_reset_password(request: Request):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    class_id = str(body.get("class_id") or "")
    student_id = str(body.get("student_id") or "")
    if not class_id or not student_id:
        return _fail("缺少 class_id / student_id")
    new_pwd = str(body.get("password") or DEFAULT_PASSWORD)
    try:
        student_accounts.set_password(class_id, student_id, new_pwd)
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "student_account:reset_password", resource="%s/%s" % (class_id, student_id))
    return _ok({"password": new_pwd})


@router.post("/accounts/students/{class_id}/{student_id}/toggle-status")
async def student_account_toggle(request: Request, class_id: str, student_id: str):
    admin, err = _guard(request)
    if err:
        return err
    body = await _json(request)
    try:
        item = student_accounts.set_status(class_id, student_id, body.get("status", "disabled"))
    except ValueError as e:
        return _fail(str(e), 400)
    _audit(admin, "student_account:toggle_status",
           resource="%s/%s" % (class_id, student_id), detail=item.get("status", ""))
    return _ok(item)
