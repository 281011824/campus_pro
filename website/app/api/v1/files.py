# -*- coding: utf-8 -*-
"""工作台数据接口：学生名册、成绩概览、德育台账、Excel 模板/导入/导出。"""

import io
import os
import sqlite3
import tempfile
import zipfile
from datetime import date, timedelta
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from app.services import deyu_auth, wecom_oauth
from app.api.v1.head_teacher_workbench import LOGIN_USER_ALIASES
from tasks.domain.growth import (datadomains, growth_archive)
from tasks.domain.identity import (access, accounts, bindings, classes as class_dict)
from tasks.shared import db
from tasks.modules.head_teacher import assistant
from tasks.modules.supervisor import dorms
from tasks.modules.head_teacher import (moral_criteria, redpoint, roster, seating)
from tasks.modules.head_teacher.exports import (seating_excel, seating_pdf)

router = APIRouter()

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _user(request: Request) -> str:
    user = request.headers.get("X-Auth-User", "")
    session = wecom_oauth.read_session(request.cookies.get(wecom_oauth.SESSION_COOKIE, ""))
    if session:
        return LOGIN_USER_ALIASES.get(session, session)
    if not user and wecom_oauth.auth_required():
        return ""
    return user


def _unauthorized():
    return JSONResponse({"code": 401, "error": "登录已过期，请重新登录"}, status_code=401)


def _class_id(request: Request, given: str = "") -> str:
    return given or request.query_params.get("class_id") or "2607"


def _ok(data):
    return JSONResponse({"code": 0, "data": data})


def _forbidden(msg="仅本班班主任可查看本班学生信息"):
    return JSONResponse({"code": 403, "error": msg}, status_code=403)


def _guard_class(user, class_id):
    """非本班班主任一律拒绝，避免越班查看学生信息。"""
    return None if access.can_view_class(user, class_id) else _forbidden()


def _can_manage_teachers(user: str) -> bool:
    """校领导、中层干部可维护教师账号；未登记的环境账号默认放行。"""
    rec = accounts.get(user)
    if not rec:
        return True
    return (rec.get("category") or "") in ("校领导", "中层干部")


def _can_teach_class(user: str, class_id: str) -> bool:
    """班主任本人或任课绑定覆盖该班的教师，可提交科任反馈。"""
    if access.can_view_class(user, class_id):
        return True
    try:
        for p in bindings.posts_of(user):
            cids = p.get("class_ids")
            if isinstance(cids, str):
                cids = db.loads(cids, [])
            if str(class_id) in [str(x) for x in (cids or [])]:
                return True
    except Exception:
        pass
    return False


async def _json_object(request: Request):
    """解析 JSON 请求体；非对象一律返回 None（由调用方回 400）。"""
    try:
        body = await request.json()
    except Exception:
        return None
    return body if isinstance(body, dict) else None


@router.get("/me")
async def me(request: Request):
    user = _user(request)
    if not user:
        return _unauthorized()
    rec = accounts.get(user) or {}
    classes = sorted(access.headteacher_classes(user))
    return _ok({"user_id": user, "name": rec.get("name") or "",
                "category": rec.get("category") or "",
                "can_manage_teachers": _can_manage_teachers(user),
                "is_headteacher": bool(classes),
                "class_ids": classes,
                "can_view_students": bool(classes)})


@router.get("/students")
async def students(request: Request):
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    items = roster.list_students(cid, request.query_params.get("q", ""))
    return _ok({"class_id": cid, "items": items, "total": len(items)})


@router.get("/scores/summary")
async def scores_summary(request: Request):
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    return _ok(roster.score_summary(cid))


@router.get("/moral/records")
async def moral_records(request: Request):
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    sid = request.query_params.get("student_id", "").strip()
    start = request.query_params.get("start", "").strip()
    end = request.query_params.get("end", "").strip()
    if bool(start) != bool(end):
        return JSONResponse({"code": 400, "error": "开始日期和结束日期必须同时提供"}, status_code=400)
    if start:
        try:
            start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            return JSONResponse({"code": 400, "error": "日期格式应为 YYYY-MM-DD"}, status_code=400)
        if start_day > end_day:
            return JSONResponse({"code": 400, "error": "开始日期不能晚于结束日期"}, status_code=400)
    where, args = ["b.class_id=?"], [cid]
    if sid:
        where.append("b.student_id=?")
        args.append(sid)
    if start:
        where.append("b.event_date BETWEEN ? AND ?")
        args.extend([start, end])
    rows = db.q(
        "SELECT b.id,b.event_date,b.student_id,COALESCE(s.name,'') AS name,b.polarity,"
        "b.category,b.points,b.status,b.fact,b.source,b.confirmed_at FROM dom_behavior b "
        "LEFT JOIN students s ON s.class_id=b.class_id AND s.student_id=b.student_id "
        "WHERE " + " AND ".join(where) + " ORDER BY b.event_date DESC,b.ts DESC LIMIT 100",
        tuple(args))
    return _ok({"items": [dict(r) for r in rows]})


@router.get("/attendance/week")
async def attendance_week(request: Request):
    """本周出勤：逐日出勤率、今日未到名单、请假记录。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    rows = db.q("SELECT date,status,COUNT(*) AS n FROM dom_attendance WHERE class_id=? "
                "AND date BETWEEN ? AND ? GROUP BY date,status",
                (cid, start.isoformat(), end.isoformat()))
    stat = {}
    for r in rows:
        d = stat.setdefault(r["date"], {"present": 0, "absent": 0, "leave": 0, "late": 0})
        d[r["status"]] = d.get(r["status"], 0) + int(r["n"])
    days = []
    for i in range(7):
        key = (start + timedelta(days=i)).isoformat()
        v = stat.get(key)
        if v:
            total = sum(v.values())
            v = dict(v, date=key, total=total,
                     rate=round(v["present"] * 100.0 / total, 1) if total else None)
        else:
            v = {"date": key, "total": 0, "rate": None, "present": 0, "absent": 0,
                 "leave": 0, "late": 0}
        days.append(v)
    absent = db.q(
        "SELECT a.student_id,COALESCE(s.student_no,'') AS student_no,COALESCE(s.name,'') AS name,"
        "a.status FROM dom_attendance a "
        "LEFT JOIN students s ON s.class_id=a.class_id AND s.student_id=a.student_id "
        "WHERE a.class_id=? AND a.date=? AND a.status!='present' ORDER BY a.student_id",
        (cid, today.isoformat()))
    leaves = db.q(
        "SELECT l.student_id,COALESCE(s.student_no,'') AS student_no,COALESCE(s.name,'') AS name,"
        "l.date_from,l.date_to,l.leave_type "
        "FROM dom_leave l LEFT JOIN students s ON s.class_id=l.class_id AND s.student_id=l.student_id "
        "WHERE l.class_id=? AND l.approved=1 AND NOT (l.date_to < ? OR l.date_from > ?) "
        "ORDER BY l.date_from", (cid, start.isoformat(), end.isoformat()))
    week_rate = None
    total = sum(d["total"] for d in days)
    present = sum(d["present"] for d in days)
    if total:
        week_rate = round(present * 100.0 / total, 1)
    return _ok({"class_id": cid, "week": "%s~%s" % (start.isoformat(), end.isoformat()),
                "week_rate": week_rate, "days": days,
                "today": {"date": today.isoformat(), "absent": [dict(r) for r in absent]},
                "leaves": [dict(r) for r in leaves]})


@router.get("/learning/overview")
async def learning_overview(request: Request):
    """学情：作业提交率（低提交名单）＋最近考试等第分布。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    rows = db.q(
        "SELECT h.student_id,COALESCE(s.student_no,'') AS student_no,COALESCE(s.name,'') AS name,"
        "SUM(h.submitted) AS done,COUNT(*) AS total "
        "FROM dom_homework h LEFT JOIN students s ON s.class_id=h.class_id AND s.student_id=h.student_id "
        "WHERE h.class_id=? GROUP BY h.student_id ORDER BY h.student_id", (cid,))
    low, all_done, all_total = [], 0, 0
    for r in rows:
        done, total = int(r["done"] or 0), int(r["total"] or 0)
        all_done += done
        all_total += total
        if total and done * 1.0 / total < 0.7:
            low.append({"student_id": r["student_id"], "student_no": r["student_no"],
                        "name": r["name"], "rate": round(done * 100.0 / total, 1)})
    return _ok({
        "class_id": cid,
        "homework": {"rate": round(all_done * 100.0 / all_total, 1) if all_total else None,
                     "low": low, "total": all_total},
        "scores": roster.score_summary(cid),
    })


# ---------------------------------------------------------------- 班主任小秘书
@router.get("/assistant/summary")
async def assistant_summary(request: Request):
    """小秘书提醒角标：重点学生数 + 科任反馈未读数。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    return _ok(dict(assistant.summary(cid), class_id=cid))


@router.get("/assistant/focus")
async def assistant_focus_list(request: Request):
    """本班重点学生标记列表：班主任与本班任课教师可读。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    if not _can_teach_class(user, cid):
        return _forbidden("仅本班班主任或任课教师可查看")
    return _ok({"class_id": cid, "items": assistant.list_focus(cid),
                "tags": assistant.FOCUS_TAGS})


@router.post("/assistant/focus")
async def assistant_focus_add(request: Request):
    """给学生打重点标签（重复标签仅更新备注）。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = _class_id(request, str(body.get("class_id") or ""))
    denied = _guard_class(user, cid)
    if denied:
        return denied
    try:
        item, created = assistant.add_focus(
            cid, body.get("student_id"), body.get("tag"), body.get("note", ""), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    return _ok({"item": item, "created": created, "items": assistant.list_focus(cid)})


@router.post("/assistant/focus/remove")
async def assistant_focus_remove(request: Request):
    """移除重点标签。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = _class_id(request, str(body.get("class_id") or ""))
    denied = _guard_class(user, cid)
    if denied:
        return denied
    try:
        assistant.remove_focus(cid, body.get("mark_id"), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    return _ok({"items": assistant.list_focus(cid)})


@router.get("/assistant/feedback")
async def assistant_feedback_list(request: Request):
    """科任反馈收件箱（班主任端）。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    unread = request.query_params.get("unread") in ("1", "true", "yes")
    return _ok({"class_id": cid, "items": assistant.list_comments(cid, unread),
                "kinds": assistant.COMMENT_KINDS,
                "summary": assistant.comment_summary(cid)})


@router.post("/assistant/feedback")
async def assistant_feedback_add(request: Request):
    """科任教师提交课堂表现 / 作业情况点评。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = _class_id(request, str(body.get("class_id") or ""))
    if not _can_teach_class(user, cid):
        return _forbidden("仅本班任课教师或班主任可提交点评")
    try:
        item = assistant.add_comment(cid, body.get("student_id"), body.get("kind"),
                                     body.get("content"), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    return _ok({"item": item, "summary": assistant.comment_summary(cid)})


@router.post("/assistant/feedback/read")
async def assistant_feedback_read(request: Request):
    """班主任标记反馈已读。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = _class_id(request, str(body.get("class_id") or ""))
    denied = _guard_class(user, cid)
    if denied:
        return denied
    try:
        assistant.mark_read(cid, body.get("comment_id"), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    return _ok({"summary": assistant.comment_summary(cid)})


@router.get("/students/{student_id}/profile")
async def student_profile(request: Request, student_id: str):
    """成长档案：基本信息＋近 7 日出勤＋近期德育事件。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    info = db.q("SELECT * FROM students WHERE class_id=? AND student_id=?",
                (cid, student_id), one=True)
    if not info:
        return JSONResponse({"code": 404, "error": "未找到该学生"}, status_code=404)
    start = date.today() - timedelta(days=6)
    att = db.q("SELECT status,COUNT(*) AS n FROM dom_attendance WHERE class_id=? AND student_id=? "
               "AND date>=? GROUP BY status", (cid, student_id, start.isoformat()))
    moral = db.q("SELECT event_date,polarity,category,points,status FROM dom_behavior "
                 "WHERE class_id=? AND student_id=? ORDER BY event_date DESC, ts DESC LIMIT 8",
                 (cid, student_id))
    return _ok({"student": dict(info),
                "attendance": {r["status"]: int(r["n"]) for r in att},
                "records": roster.list_records(cid, student_id),
                "behavior": [dict(r) for r in moral]})


@router.get("/growth360/dimensions")
async def growth_dimensions(request: Request):
    """成长档案五维配置（服务端下发，前端不得自行扩展）。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    return _ok({"dimensions": growth_archive.DIMENSIONS})


@router.get("/growth360/class/overview")
async def growth_class_overview(request: Request):
    """班级成长视图：五维覆盖、待确认、记录较少。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    return _ok(growth_archive.class_overview(cid))


@router.get("/growth360/{student_id}")
async def growth_student(request: Request, student_id: str):
    """学生 360：五维等级、时间轴、证书实习与出勤摘要。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    data = growth_archive.student360(cid, student_id, request.query_params.get("term", ""))
    if not data:
        return JSONResponse({"code": 404, "error": "未找到该学生"}, status_code=404)
    return _ok(data)


@router.post("/growth360/{student_id}/items")
async def growth_add_item(request: Request, student_id: str):
    """新增成长记录；任课教师 / 企业导师提交的默认待班主任确认。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    if not db.q("SELECT 1 FROM students WHERE class_id=? AND student_id=?",
                (cid, student_id), one=True):
        return JSONResponse({"code": 404, "error": "未找到该学生"}, status_code=404)
    body = await request.json()
    try:
        res = growth_archive.add_item(cid, student_id, body, user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "growth.add", "ok", student_id, str(body.get("dim") or ""))
    return _ok(res)


@router.post("/growth360/items/{item_id}/confirm")
async def growth_confirm_item(request: Request, item_id: str):
    """班主任确认或退回一条成长记录。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    row = db.q("SELECT class_id FROM growth_items WHERE id=?", (item_id,), one=True)
    if not row:
        return JSONResponse({"code": 404, "error": "记录不存在"}, status_code=404)
    denied = _guard_class(user, row["class_id"])
    if denied:
        return denied
    body = await request.json()
    try:
        res = growth_archive.confirm_item(item_id, str(body.get("action") or ""), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "growth.confirm", "ok", item_id, str(body.get("action") or ""))
    return _ok(res)


@router.post("/growth360/{student_id}/certificates")
async def growth_add_certificate(request: Request, student_id: str):
    """登记 1+X / 职业资格证书，并同步进入五维时间轴。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    if not db.q("SELECT 1 FROM students WHERE class_id=? AND student_id=?",
                (cid, student_id), one=True):
        return JSONResponse({"code": 404, "error": "未找到该学生"}, status_code=404)
    body = await request.json()
    try:
        res = growth_archive.add_certificate(cid, student_id, body, user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "growth.certificate.add", "ok", student_id, res["id"])
    return _ok(res)


@router.post("/growth360/certificates/{cert_id}/confirm")
async def growth_confirm_certificate(request: Request, cert_id: str):
    """确认或退回外部提交的证书，时间轴记录同步变更。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    row = db.q("SELECT class_id FROM growth_certificates WHERE id=?", (cert_id,), one=True)
    if not row:
        return JSONResponse({"code": 404, "error": "证书记录不存在"}, status_code=404)
    denied = _guard_class(user, row["class_id"])
    if denied:
        return denied
    body = await request.json()
    try:
        res = growth_archive.confirm_certificate(cert_id, str(body.get("action") or ""), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "growth.certificate.confirm", "ok", cert_id, str(body.get("action") or ""))
    return _ok(res)


@router.get("/growth360/{student_id}/report")
async def growth_get_report(request: Request, student_id: str):
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    if not db.q("SELECT 1 FROM students WHERE class_id=? AND student_id=?",
                (cid, student_id), one=True):
        return JSONResponse({"code": 404, "error": "未找到该学生"}, status_code=404)
    try:
        return _ok(growth_archive.get_report(
            cid, student_id, request.query_params.get("term", "")))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)


@router.post("/growth360/{student_id}/report/generate")
async def growth_generate_report(request: Request, student_id: str):
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = growth_archive.generate_report(cid, student_id, str(body.get("term") or ""), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "growth.report.generate", "ok", student_id, str(body.get("term") or ""))
    return _ok(res)


@router.post("/growth360/{student_id}/report/edit")
async def growth_edit_report(request: Request, student_id: str):
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = growth_archive.edit_report(cid, student_id, str(body.get("term") or ""),
                                        body.get("teacher_comment") or "", user)
    except growth_archive.ReportLockedError as exc:
        return JSONResponse({"code": 409, "error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "growth.report.edit", "ok", student_id, str(body.get("term") or ""))
    return _ok(res)


@router.post("/growth360/{student_id}/report/publish")
async def growth_publish_report(request: Request, student_id: str):
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = growth_archive.publish_report(cid, student_id, str(body.get("term") or ""), user)
    except growth_archive.ReportLockedError as exc:
        return JSONResponse({"code": 409, "error": str(exc)}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "growth.report.publish", "ok", student_id, str(body.get("term") or ""))
    return _ok(res)


@router.get("/seating/{kind}")
async def seating_get(request: Request, kind: str):
    """座位表 / 寝室表：行列、卡片位置与待排学生。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    try:
        return _ok(seating.get_plan(cid, kind))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)


@router.get("/seating/{kind}/export")
async def seating_export(request: Request, kind: str):
    """导出当前座位表 / 寝室表为 A4 PDF。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    try:
        plan = seating.get_plan(cid, kind)
        data = seating_pdf.render(plan)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"code": 500, "error": str(exc)}, status_code=500)
    name = "%s班_%s_%s.pdf" % (
        cid, "座位表" if plan["kind"] == "seat" else "寝室表", date.today().strftime("%Y%m%d"))
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(name)})


@router.get("/seating/{kind}/export/xlsx")
async def seating_export_xlsx(request: Request, kind: str):
    """导出当前座位表 / 寝室表为 Excel。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    try:
        plan = seating.get_plan(cid, kind)
        data = seating_excel.render(plan)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    name = "%s班_%s_%s.xlsx" % (
        cid, "座位表" if plan["kind"] == "seat" else "寝室表", date.today().strftime("%Y%m%d"))
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(name)})


@router.post("/seating/room")
async def seating_add_room(request: Request):
    """寝室表新增一间寝室，房号手工填写。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = seating.add_room(cid, body.get("room_name"), body.get("gender"))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "seating.room.add", "ok", cid, str(body.get("room_name") or ""))
    return _ok(res)


@router.post("/seating/room/update")
async def seating_update_room(request: Request):
    """修改寝室类型；寝室号不可修改。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = seating.update_room(cid, body.get("room_name"), body.get("gender"))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "seating.room.update", "ok", cid, str(body.get("room_name") or ""))
    return _ok(res)


@router.post("/seating/room/delete")
async def seating_delete_room(request: Request):
    """删除寝室，寝室内学生回到未分配区。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = seating.delete_room(cid, body.get("room_name"))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "seating.room.delete", "ok", cid, str(body.get("room_name") or ""))
    return _ok(res)


@router.post("/seating/layout")
async def seating_layout(request: Request):
    """调整行列；超出范围的位置会被清空。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = seating.save_layout(cid, str(body.get("kind") or "seat"),
                                  body.get("rows"), body.get("cols"), body.get("meta"))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "seating.layout", "ok", cid, "%sx%s" % (res["rows"], res["cols"]))
    return _ok(res)


@router.post("/seating/assign")
async def seating_assign(request: Request):
    """拖拽落位：目标已有人则两人互换。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = seating.assign(cid, str(body.get("kind") or "seat"),
                             body.get("row"), body.get("col"), body.get("student_id"),
                             operator=user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "seating.assign", "ok", cid, str(body.get("student_id") or ""))
    return _ok(res)


@router.post("/seating/unassign")
async def seating_unassign(request: Request):
    """把学生移回待排区。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        return _ok(seating.unassign(cid, str(body.get("kind") or "seat"),
                                    body.get("student_id"), operator=user))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)


@router.post("/seating/auto")
async def seating_auto(request: Request):
    """按学号顺序自动排位。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = seating.auto_arrange(cid, str(body.get("kind") or "seat"))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "seating.auto", "ok", cid, res["kind"])
    return _ok(res)


@router.post("/seating/clear")
async def seating_clear(request: Request):
    """清空当前表格的位置，学生回到待排区。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    body = await request.json()
    try:
        res = seating.clear(cid, str(body.get("kind") or "seat"), operator=user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "seating.clear", "ok", cid, res["kind"])
    return _ok(res)


@router.post("/students/{student_id}/records")
async def add_student_record(request: Request, student_id: str):
    """成长档案新增一条特长/兴趣/奖惩/家访记录。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    denied = _guard_class(user, _class_id(request))
    if denied:
        return denied
    body = await request.json()
    try:
        res = roster.add_record(_class_id(request), student_id,
                                str(body.get("kind") or "").strip(),
                                str(body.get("title") or "").strip(),
                                str(body.get("detail") or "").strip(),
                                str(body.get("day") or "").strip(), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "student.record", "ok", student_id, body.get("kind"))
    return _ok(res)


@router.post("/files/family/note")
async def family_note(request: Request):
    """家校沟通留痕：只记分类与时间，不存家长电话与事由细节。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    denied = _guard_class(user, _class_id(request))
    if denied:
        return denied
    body = await request.json()
    category = str(body.get("category") or "").strip()
    allowed = ("归寝异常", "缺勤关注", "学业联系", "行为观察", "家长告知", "其他")
    if category not in allowed:
        return JSONResponse({"code": 400, "error": "分类不合法"}, status_code=400)
    tid = db.uid("td_")
    week = redpoint._week_key()
    db.exec_(
        "INSERT INTO todo_items(id,ts,week,owner_user_id,owner_post_id,owner_agent_id,"
        "class_id,kind,category,fact,status,created_via) "
        "VALUES(?,?,?,?,?,?,?,?,?, '人工登记（家校沟通）', 'open','note')",
        (tid, db.now(), week, user, "", "htw-web", _class_id(request), "notify", category))
    db.audit({"user_id": user, "post_id": "", "agent_id": "htw-web"},
             "family.note", "ok", tid, "家校沟通留痕：%s（不自动推送家长）" % category)
    return _ok({"item_id": tid, "category": category, "ts": db.now(),
                "note": "已登记为家校沟通留痕（人工登记，不自动推送给家长）"})


@router.get("/files/backup/zip")
async def backup_zip(request: Request):
    """一键备份：学生/成绩（及有权限时的教师）Excel ＋ 数据库快照。"""
    user = _user(request)
    if not user:
        return _unauthorized()
    cid = _class_id(request)
    denied = _guard_class(user, cid)
    if denied:
        return denied
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("学生名册.xlsx", roster.export("students", cid))
        z.writestr("成绩数据.xlsx", roster.export("scores", cid))
        if _can_manage_teachers(user):
            z.writestr("教师账号.xlsx", roster.export("teachers"))
        with tempfile.TemporaryDirectory() as td:
            snap = os.path.join(td, "dywork.db")
            src = sqlite3.connect(db.DB_PATH)
            dst = sqlite3.connect(snap)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            z.write(snap, "数据库快照.db")
        z.writestr("说明.txt", "班主任工作台备份\n班级：%s\n日期：%s\n"
                   "说明：Excel 可直接编辑后重新导入；数据库快照用于故障恢复。\n"
                   % (cid, date.today().isoformat()))
    name = "班主任工作台备份_%s.zip" % date.today().isoformat()
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(name)})


@router.get("/files/template/{kind}")
async def download_template(request: Request, kind: str):
    if not _user(request):
        return _unauthorized()
    try:
        content = roster.template(kind)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    names = {"students": "学生名册模板.xlsx", "teachers": "教师账号模板.xlsx",
             "scores": "成绩导入模板.xlsx"}
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(names.get(kind, "模板.xlsx"))})


@router.get("/files/export/{kind}")
async def export_file(request: Request, kind: str):
    if not _user(request):
        return _unauthorized()
    if kind == "teachers" and not _can_manage_teachers(_user(request)):
        return JSONResponse({"code": 403, "error": "仅校领导、中层干部可导出教师账号"}, status_code=403)
    if kind in ("students", "scores"):
        denied = _guard_class(_user(request), _class_id(request))
        if denied:
            return denied
    try:
        content = roster.export(kind, _class_id(request))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    names = {"students": "学生名册.xlsx", "teachers": "教师账号.xlsx", "scores": "成绩数据.xlsx"}
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(names.get(kind, "导出.xlsx"))})


@router.post("/files/import/{kind}")
async def import_file(request: Request, kind: str, file: UploadFile = File(...)):
    if not _user(request):
        return _unauthorized()
    if kind == "teachers" and not _can_manage_teachers(_user(request)):
        return JSONResponse({"code": 403, "error": "仅校领导、中层干部可导入教师账号"}, status_code=403)
    if kind in ("students", "scores"):
        denied = _guard_class(_user(request), _class_id(request))
        if denied:
            return denied
    raw = await file.read()
    if not raw:
        return JSONResponse({"code": 400, "error": "文件为空"}, status_code=400)
    if len(raw) > 5 * 1024 * 1024:
        return JSONResponse({"code": 400, "error": "文件超过 5MB，请拆分后重试"}, status_code=400)
    try:
        result = roster.import_file(kind, raw, _class_id(request))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    except Exception as exc:  # 损坏的 xlsx 等
        return JSONResponse({"code": 400, "error": "解析失败：%s" % exc}, status_code=400)
    db.audit({"user_id": _user(request), "post_id": "", "agent_id": ""},
             "file.import", "ok", kind,
             "新增 %s 更新 %s 跳过 %s" % (result["added"], result["updated"], result["skipped"]))
    return _ok(result)


# ---------------------------------------------------------------- 政教处 · 德育指标库
DEYU_DIRECTIONS = [
    {"key": "praise", "label": "掌声鼓励"},
    {"key": "improve", "label": "有待改善"},
]

_EVENT_SELECT = (
    "SELECT b.id,b.ts,b.class_id,b.student_id,COALESCE(s.name,'') AS student_name,"
    "b.event_date,b.polarity,b.category,b.points,b.status,b.fact,b.source,"
    "b.criteria_id,COALESCE(c.name,'') AS criteria_name,b.recorded_by,"
    "b.confirmed_by,b.confirmed_at FROM dom_behavior b "
    "LEFT JOIN students s ON s.class_id=b.class_id AND s.student_id=b.student_id "
    "LEFT JOIN moral_criteria c ON c.id=b.criteria_id "
)


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "启用")


def _event_by_id(event_id):
    row = db.q(_EVENT_SELECT + "WHERE b.id=?", (str(event_id),), one=True)
    return dict(row) if row else None


@router.get("/deyu/criteria")
async def deyu_criteria_list(request: Request):
    """德育指标库：方向枚举 + 全部指标（含停用）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    return _ok({"items": moral_criteria.list_all(False), "directions": DEYU_DIRECTIONS})


@router.post("/deyu/criteria")
async def deyu_criteria_create(request: Request):
    """新增指标；同方向重名返回 400。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    try:
        item = moral_criteria.create(body.get("name"), body.get("direction"),
                                     body.get("points"), body.get("category", ""),
                                     body.get("term", ""), user)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.criteria.create", "ok", item["id"], item["name"])
    return _ok({"item": item})


@router.post("/deyu/criteria/update")
async def deyu_criteria_update(request: Request):
    """修改指标；分值改动只影响后续登记。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = str(body.get("id") or "").strip()
    if not cid:
        return JSONResponse({"code": 400, "error": "缺少指标 id"}, status_code=400)
    fields = {k: body[k] for k in ("name", "direction", "points", "category", "term")
              if k in body}
    try:
        item = moral_criteria.update(cid, **fields)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.criteria.update", "ok", cid, item["name"])
    return _ok({"item": item})


@router.post("/deyu/criteria/toggle")
async def deyu_criteria_toggle(request: Request):
    """启用 / 停用指标。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = str(body.get("id") or "").strip()
    if not cid:
        return JSONResponse({"code": 400, "error": "缺少指标 id"}, status_code=400)
    try:
        item = moral_criteria.set_enabled(cid, _bool(body.get("enabled")))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.criteria.toggle", "ok", cid, "enabled=%s" % item["enabled"])
    return _ok({"item": item})


@router.post("/deyu/criteria/remove")
async def deyu_criteria_remove(request: Request):
    """删除指标；已有事件引用时改为停用，返回 action。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = str(body.get("id") or "").strip()
    if not cid:
        return JSONResponse({"code": 400, "error": "缺少指标 id"}, status_code=400)
    try:
        action = moral_criteria.remove(cid)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.criteria.remove", "ok", cid, action)
    return _ok({"action": action})


# ---------------------------------------------------------------- 政教处 · 全校德育登记与审核
@router.get("/deyu/classes")
async def deyu_classes(request: Request):
    """全校班级：学生数与本周德育净分（仅已确认事件计分）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    start, end = datadomains._week_bounds()
    items = []
    for it in class_dict.list():
        cid = it["class_id"]
        items.append({
            "class_id": cid,
            "name": it.get("name") or ("%s班" % cid),
            "grade": it.get("grade") or "",
            "head_teacher_userid": it.get("head_teacher_userid") or "",
            "student_count": int(it.get("student_count") or 0),
            "moral_net": datadomains.moral_delta(cid, start, end),
        })
    return _ok({"items": items, "week": "%s~%s" % (start.isoformat(), end.isoformat())})


@router.post("/deyu/classes/create")
async def deyu_class_create(request: Request):
    """政教处新建班级（班级编号必填）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    try:
        item = class_dict.create(body.get("class_id"), body.get("name", ""),
                                 body.get("grade", ""))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.class.create", "ok", item["class_id"], item.get("name") or "")
    return _ok(item)


@router.post("/deyu/classes/update")
async def deyu_class_update(request: Request):
    """政教处编辑班级名称 / 年级（班级编号不可修改）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = str(body.get("class_id") or "").strip()
    try:
        item = class_dict.update(cid, name=body.get("name"), grade=body.get("grade"))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.class.update", "ok", cid, item.get("name") or "")
    return _ok(item)


@router.post("/deyu/classes/delete")
async def deyu_class_delete(request: Request):
    """政教处删除班级；班内仍有学生时拒绝删除。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = str(body.get("class_id") or "").strip()
    try:
        class_dict.delete(cid)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.class.delete", "ok", cid, "")
    return _ok({"class_id": cid})


@router.get("/deyu/students")
async def deyu_students(request: Request):
    """指定班级学生（含扩展字段），供政教处名单展示与登记下拉。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    cid = request.query_params.get("class_id", "").strip()
    if not cid:
        return JSONResponse({"code": 400, "error": "请先选择班级"}, status_code=400)
    return _ok({"class_id": cid, "items": roster.list_students(cid)})


@router.post("/deyu/students/create")
async def deyu_student_create(request: Request):
    """政教处手动新增学生：姓名、性别、班级必填，学号可留空自动生成。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    class_id = str(body.get("class_id") or "").strip()
    if not class_dict.get(class_id):
        return JSONResponse({"code": 400, "error": "班级不存在：%s" % (class_id or "未选择")},
                            status_code=400)
    try:
        item = roster.create_student(
            class_id, "", body.get("name"), body.get("gender", ""),
            body.get("dorm", ""), body.get("address", ""), body.get("phone", ""),
            body.get("guardian_phone", ""), body.get("status", "在读"),
            body.get("major", ""), body.get("grade", ""), body.get("boarding_type", ""),
            body.get("guardian_name", ""), body.get("guardian_relation", ""),
            body.get("bed_no", ""), body.get("student_no", ""))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.student.create", "ok", "%s/%s" % (class_id, item["student_id"]),
             item.get("name") or "")
    if str(body.get("dorm") or "").strip():
        try:
            seating.rebuild_dorm_from_roster(class_id, force=True)
        except Exception:
            pass
    return _ok(item)


# ---------------------------------------------------------------- 政教处 · 名单上传与学号编排
@router.get("/deyu/students/template")
async def deyu_students_template(request: Request):
    """名单导入模板：班级、姓名、性别、学号(可空)。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    content = roster.deyu_student_template()
    name = "学生名单导入模板.xlsx"
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(name)})


@router.post("/deyu/students/import")
async def deyu_students_import(request: Request, file: UploadFile = File(...),
                               overwrite: bool = Form(False)):
    """上传名单 xlsx，逐行校验并返回成功/冲突/失败明细；非法行不写入。

    默认不覆盖已存在学生，命中冲突的行由前端弹窗确认后再以 overwrite=true 重传。
    """
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    raw = await file.read()
    if not raw:
        return JSONResponse({"code": 400, "error": "文件为空"}, status_code=400)
    if len(raw) > 5 * 1024 * 1024:
        return JSONResponse({"code": 400, "error": "文件超过 5MB，请拆分后重试"}, status_code=400)
    try:
        result = roster.deyu_import_students(raw, overwrite=overwrite)
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"code": 400, "error": "解析失败：%s" % exc}, status_code=400)
    # 名单中的宿舍号写入 students.dorm 后，同步刷新班主任端寝室表
    for cid in sorted({r["class_id"] for r in result["rows"]
                       if r.get("status") == "ok" and r.get("class_id")}):
        try:
            seating.rebuild_dorm_from_roster(cid, force=True)
        except Exception:
            pass
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.students.import", "ok", file.filename or "",
             "成功 %d 冲突 %d 失败 %d 覆盖=%s" % (
                 result["ok_count"], result["conflict_count"],
                 result["failed_count"], "是" if overwrite else "否"))
    return _ok(result)


@router.post("/deyu/students/delete")
async def deyu_students_delete(request: Request):
    """批量删除本班学生（单选与多选共用）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = str(body.get("class_id") or "").strip()
    ids = body.get("student_ids")
    if not cid:
        return JSONResponse({"code": 400, "error": "请先选择班级"}, status_code=400)
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"code": 400, "error": "请先选择要删除的学生"}, status_code=400)
    result = roster.delete_students(cid, ids)
    if not result["deleted"] and result["missing"]:
        return JSONResponse({"code": 400, "error": "所选学生不存在或不属于该班级"},
                            status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.students.delete", "ok", cid, "删除 %s 人" % result["deleted"])
    return _ok(result)


@router.post("/deyu/students/numbering/preview")
async def deyu_numbering_preview(request: Request):
    """学号编排预览：仅计算，不落库。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    try:
        data = roster.numbering_preview(body.get("class_id"), body.get("prefix", ""),
                                        body.get("width", 2))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    return _ok(data)


@router.post("/deyu/students/numbering/apply")
async def deyu_numbering_apply(request: Request):
    """应用学号：事务内写入，跳过已有值，冲突整单回滚。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    try:
        result = roster.numbering_apply(body.get("class_id"), body.get("items"))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.students.numbering", "ok", str(body.get("class_id") or ""),
             "更新 %d 跳过 %d" % (result["updated"], result["skipped"]))
    return _ok(result)


# ---------------------------------------------------------------- 政教处 · 寝室统一分配
@router.get("/deyu/dorms")
async def deyu_dorms_list(request: Request):
    """全校寝室与入住统计（与 students.dorm 同源）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    return _ok(dorms.list_for_assignment())


@router.post("/deyu/dorms/assign")
async def deyu_dorms_assign(request: Request):
    """批量分配寝室：性别、余量校验，失败整单不写入。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    try:
        result = dorms.assign(body.get("dorm_id"), body.get("student_ids") or [],
                              body.get("class_id", ""))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.dorms.assign", "ok", str(result["room_no"]),
             "分配 %d 人" % result["assigned"])
    return _ok(result)


@router.post("/deyu/dorms/unassign")
async def deyu_dorms_unassign(request: Request):
    """清空所选学生的寝室。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    try:
        result = dorms.unassign(body.get("student_ids") or [], body.get("class_id", ""))
    except ValueError as exc:
        return JSONResponse({"code": 400, "error": str(exc)}, status_code=400)
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.dorms.unassign", "ok", "", "移出 %d 人" % result["cleared"])
    return _ok(result)


@router.post("/deyu/moral/register")
async def deyu_moral_register(request: Request):
    """政教处登记全校任一班级学生的德育事件（待班主任确认后计分）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    cid = str(body.get("class_id") or "").strip()
    sid = str(body.get("student_id") or "").strip()
    criteria_id = str(body.get("criteria_id") or "").strip()
    if not cid or not sid or not criteria_id:
        return JSONResponse({"code": 400, "error": "班级、学生与指标均不能为空"},
                            status_code=400)
    if not db.q("SELECT 1 FROM students WHERE class_id=? AND student_id=?",
                (cid, sid), one=True):
        return JSONResponse({"code": 400, "error": "该学生不属于所选班级"}, status_code=400)
    criteria = moral_criteria.get(criteria_id)
    if not criteria:
        return JSONResponse({"code": 400, "error": "德育指标不存在"}, status_code=400)
    if not criteria.get("enabled"):
        return JSONResponse({"code": 400, "error": "该指标已停用"}, status_code=400)
    points = moral_criteria.snapshot_points(criteria_id)
    polarity = "positive" if criteria["direction"] == "praise" else "negative"
    event_date = str(body.get("event_date") or "").strip() or date.today().isoformat()
    try:
        date.fromisoformat(event_date)
    except ValueError:
        return JSONResponse({"code": 400, "error": "日期格式应为 YYYY-MM-DD"}, status_code=400)
    category = criteria.get("category") or criteria.get("name") or ""
    eid = db.uid("be_")
    db.exec_(
        "INSERT INTO dom_behavior(id,ts,class_id,student_id,event_date,polarity,category,"
        "points,status,fact,source,criteria_id,recorded_by) "
        "VALUES(?,?,?,?,?,?,?,?, 'pending', ?,?,?,?)",
        (eid, db.now(), cid, sid, event_date, polarity, category, int(points or 0),
         str(body.get("fact") or "")[:200], "政教处", criteria_id, user))
    db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
             "deyu.moral.register", "ok", eid,
             "%s/%s 待班主任确认后计分" % (cid, criteria["name"]))
    return _ok({"item": _event_by_id(eid)})


@router.get("/deyu/moral/records")
async def deyu_moral_records(request: Request):
    """全校德育事件流水：可按班级、状态、事件日期筛选。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    cid = request.query_params.get("class_id", "").strip()
    status = request.query_params.get("status", "").strip()
    start = request.query_params.get("start", "").strip()
    end = request.query_params.get("end", "").strip()
    if status and status not in ("pending", "confirmed", "void"):
        return JSONResponse({"code": 400, "error": "状态不合法"}, status_code=400)
    if bool(start) != bool(end):
        return JSONResponse({"code": 400, "error": "开始日期和结束日期必须同时提供"},
                            status_code=400)
    if start:
        try:
            start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            return JSONResponse({"code": 400, "error": "日期格式应为 YYYY-MM-DD"},
                                status_code=400)
        if start_day > end_day:
            return JSONResponse({"code": 400, "error": "开始日期不能晚于结束日期"},
                                status_code=400)
    try:
        limit = int(request.query_params.get("limit") or 100)
    except ValueError:
        return JSONResponse({"code": 400, "error": "limit 必须为整数"}, status_code=400)
    limit = max(1, min(limit, 500))
    where, args = [], []
    if cid:
        where.append("b.class_id=?")
        args.append(cid)
    if status:
        where.append("b.status=?")
        args.append(status)
    if start:
        where.append("b.event_date BETWEEN ? AND ?")
        args.extend([start, end])
    sql = _EVENT_SELECT
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY b.event_date DESC,b.ts DESC LIMIT ?"
    args.append(limit)
    return _ok({"items": [dict(r) for r in db.q(sql, tuple(args))]})


@router.post("/deyu/moral/review")
async def deyu_moral_review(request: Request):
    """政教处复核：确认（pending→confirmed）或作废（pending/confirmed→void）。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    body = await _json_object(request)
    if body is None:
        return JSONResponse({"code": 400, "error": "请求格式错误"}, status_code=400)
    event_id = str(body.get("event_id") or "").strip()
    action = str(body.get("action") or "").strip()
    if not event_id:
        return JSONResponse({"code": 400, "error": "缺少事件 id"}, status_code=400)
    if action not in ("confirm", "void"):
        return JSONResponse({"code": 400, "error": "操作只能为 confirm 或 void"},
                            status_code=400)
    row = db.q("SELECT * FROM dom_behavior WHERE id=?", (event_id,), one=True)
    if not row:
        return JSONResponse({"code": 400, "error": "未找到该德育事件"}, status_code=400)
    now = db.now()
    if action == "confirm":
        if row["status"] != "pending":
            return JSONResponse({"code": 400, "error": "该事件已处理，无法确认"},
                                status_code=400)
        db.exec_("UPDATE dom_behavior SET status='confirmed',confirmed_by=?,confirmed_at=? "
                 "WHERE id=?", (user, now, event_id))
    else:
        if row["status"] not in ("pending", "confirmed"):
            return JSONResponse({"code": 400, "error": "该事件已作废"}, status_code=400)
        db.exec_("UPDATE dom_behavior SET status='void',"
                 "confirmed_by=COALESCE(confirmed_by,?),"
                 "confirmed_at=COALESCE(confirmed_at,?) WHERE id=?",
                 (user, now, event_id))
    try:
        db.audit({"user_id": user, "post_id": "", "agent_id": "deyu-web"},
                 "deyu.moral.review", "ok", event_id, action)
    except Exception:
        pass
    return _ok({"item": _event_by_id(event_id), "action": action})


# ---------------------------------------------------------------- 政教处 · 全校德育统计
DEYU_BANDS = ("领先", "良好", "关注", "重点")
DEYU_BAND_LEAD = 15        # 净分 ≥ 15：领先
DEYU_BAND_GOOD = 0         # 0 ≤ 净分 < 15：良好
DEYU_BAND_FOCUS = -20      # 净分 ≤ -20：重点，其余为关注
FOCUS_STUDENT_NEGATIVE = -10
FOCUS_CATEGORY_REPEAT = 3
FOCUS_CLASS_NET = -20


def _month_bounds(day):
    first = day.replace(day=1)
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def _term_bounds(day):
    """秋季学期 9/1~次年 1/31；春季学期 2/1~7/31；8 月按秋季学期起点处理。"""
    y = day.year
    if day.month >= 9:
        return date(y, 9, 1), date(y + 1, 1, 31)
    if day.month == 1:
        return date(y - 1, 9, 1), date(y, 1, 31)
    if day.month <= 7:
        return date(y, 2, 1), date(y, 7, 31)
    return date(y, 9, 1), date(y + 1, 1, 31)


def _stats_range(request):
    """解析 period / start / end，返回 (start, end, period, error_response)。"""
    period = (request.query_params.get("period") or "week").strip()
    if period not in ("week", "month", "term"):
        return None, None, None, JSONResponse(
            {"code": 400, "error": "period 只能为 week / month / term"}, status_code=400)
    start = (request.query_params.get("start") or "").strip()
    end = (request.query_params.get("end") or "").strip()
    if bool(start) != bool(end):
        return None, None, None, JSONResponse(
            {"code": 400, "error": "开始日期和结束日期必须同时提供"}, status_code=400)
    if start:
        try:
            start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError:
            return None, None, None, JSONResponse(
                {"code": 400, "error": "日期格式应为 YYYY-MM-DD"}, status_code=400)
        if start_day > end_day:
            return None, None, None, JSONResponse(
                {"code": 400, "error": "开始日期不能晚于结束日期"}, status_code=400)
        if (end_day - start_day).days > 366:
            return None, None, None, JSONResponse(
                {"code": 400, "error": "单次统计范围不能超过 366 天"}, status_code=400)
        return start_day, end_day, period, None
    today = date.today()
    if period == "month":
        start_day, end_day = _month_bounds(today)
    elif period == "term":
        start_day, end_day = _term_bounds(today)
    else:
        start_day, end_day = datadomains._week_bounds()
    return start_day, end_day, period, None


def _deyu_band(net):
    if net >= DEYU_BAND_LEAD:
        return "领先"
    if net >= DEYU_BAND_GOOD:
        return "良好"
    if net > DEYU_BAND_FOCUS:
        return "关注"
    return "重点"


def _in_clause(class_ids):
    return ",".join("?" for _ in class_ids)


def _stats_period_nets(class_ids, start, end, criteria_id=""):
    """统计区间内每位学生的净分（用于重点识别的连续下降判断）。"""
    crit_sql = " AND criteria_id=?" if criteria_id else ""
    crit_args = (criteria_id,) if criteria_id else ()
    rows = db.q(
        "SELECT class_id,student_id,SUM(points) AS net,COUNT(*) AS n FROM dom_behavior "
        "WHERE status='confirmed' AND event_date BETWEEN ? AND ? AND class_id IN ("
        + _in_clause(class_ids) + ")" + crit_sql + " GROUP BY class_id,student_id",
        tuple([start.isoformat(), end.isoformat()] + list(class_ids)) + crit_args)
    return {(str(r["class_id"]), str(r["student_id"])): r for r in rows}


def deyu_stats(start, end, period, class_id="", grade="", criteria_id=""):
    """全校德育聚合：仅 confirmed 计分，学生基准 100 分；不输出名次。"""
    crit_sql = " AND criteria_id=?" if criteria_id else ""
    crit_sql_b = " AND b.criteria_id=?" if criteria_id else ""
    crit_args = (criteria_id,) if criteria_id else ()
    scoped = [
        it for it in class_dict.list()
        if (not class_id or str(it.get("class_id")) == str(class_id))
        and (not grade or str(it.get("grade") or "") == str(grade))
    ]
    class_ids = [str(it["class_id"]) for it in scoped]
    result = {
        "range": {"start": start.isoformat(), "end": end.isoformat(), "period": period},
        "totals": {"classes": len(scoped), "students": 0, "positive_points": 0,
                   "negative_points": 0, "net": 0, "pending": 0, "confirmed": 0},
        "classes": [], "students": [], "daily": [], "focus": [], "criteria_breakdown": [],
    }
    if not class_ids:
        return result

    first, last = start.isoformat(), end.isoformat()
    ph = _in_clause(class_ids)
    args = tuple([first, last] + class_ids) + crit_args

    result["totals"]["students"] = int(db.q(
        "SELECT COUNT(*) AS n FROM students WHERE class_id IN (" + ph + ")",
        tuple(class_ids), one=True)["n"] or 0)

    total_row = db.q(
        "SELECT SUM(CASE WHEN points>0 THEN points ELSE 0 END) AS pos,"
        "SUM(CASE WHEN points<0 THEN points ELSE 0 END) AS neg,COUNT(*) AS n "
        "FROM dom_behavior WHERE status='confirmed' AND event_date BETWEEN ? AND ? "
        "AND class_id IN (" + ph + ")" + crit_sql, args, one=True)
    pos = int(total_row["pos"] or 0) if total_row else 0
    neg = int(total_row["neg"] or 0) if total_row else 0
    confirmed = int(total_row["n"] or 0) if total_row else 0
    pending_row = db.q(
        "SELECT COUNT(*) AS n FROM dom_behavior WHERE status='pending' "
        "AND event_date BETWEEN ? AND ? AND class_id IN (" + ph + ")" + crit_sql,
        args, one=True)
    result["totals"].update({
        "positive_points": pos, "negative_points": neg, "net": pos + neg,
        "pending": int(pending_row["n"] or 0) if pending_row else 0,
        "confirmed": confirmed,
    })

    # 班级维度
    class_map = {}
    for it in scoped:
        class_map[str(it["class_id"])] = {
            "class_id": str(it["class_id"]),
            "name": it.get("name") or ("%s班" % it["class_id"]),
            "grade": it.get("grade") or "",
            "student_count": int(it.get("student_count") or 0),
            "positive": 0, "negative": 0, "net": 0, "band": "良好",
        }
    for r in db.q(
            "SELECT class_id,"
            "SUM(CASE WHEN points>0 THEN points ELSE 0 END) AS pos,"
            "SUM(CASE WHEN points<0 THEN points ELSE 0 END) AS neg,"
            "SUM(points) AS net,COUNT(*) AS n FROM dom_behavior "
            "WHERE status='confirmed' AND event_date BETWEEN ? AND ? "
            "AND class_id IN (" + ph + ")" + crit_sql + " GROUP BY class_id", args):
        item = class_map.get(str(r["class_id"]))
        if not item:
            continue
        item["positive"] = int(r["pos"] or 0)
        item["negative"] = int(r["neg"] or 0)
        item["net"] = int(r["net"] or 0)
        item["band"] = _deyu_band(item["net"])
    result["classes"] = [class_map[k] for k in sorted(class_map)]

    # 学生维度（仅返回有已确认事件的学生）
    students = {}
    for r in db.q(
            "SELECT b.class_id,b.student_id,COALESCE(s.name,'') AS name,"
            "SUM(CASE WHEN b.points>0 THEN b.points ELSE 0 END) AS pos,"
            "SUM(CASE WHEN b.points<0 THEN b.points ELSE 0 END) AS neg,"
            "SUM(b.points) AS net,COUNT(*) AS n FROM dom_behavior b "
            "LEFT JOIN students s ON s.class_id=b.class_id AND s.student_id=b.student_id "
            "WHERE b.status='confirmed' AND b.event_date BETWEEN ? AND ? "
            "AND b.class_id IN (" + ph + ")" + crit_sql_b + " "
            "GROUP BY b.class_id,b.student_id ORDER BY b.class_id,b.student_id", args):
        key = (str(r["class_id"]), str(r["student_id"]))
        net_val = int(r["net"] or 0)
        students[key] = {
            "student_id": str(r["student_id"]), "name": r["name"] or "",
            "class_id": str(r["class_id"]),
            "class_name": class_map.get(str(r["class_id"]), {}).get("name", ""),
            "total_score": 100 + net_val,
            "positive": int(r["pos"] or 0), "negative": int(r["neg"] or 0),
            "delta": net_val, "event_count": int(r["n"] or 0),
            "negative_categories": [],
        }
    neg_cats = {}
    for r in db.q(
            "SELECT class_id,student_id,category,SUM(points) AS points,COUNT(*) AS n "
            "FROM dom_behavior b WHERE status='confirmed' AND points<0 "
            "AND event_date BETWEEN ? AND ? AND class_id IN (" + ph + ")" + crit_sql_b
            + " GROUP BY class_id,student_id,category ORDER BY points", args):
        key = (str(r["class_id"]), str(r["student_id"]))
        if key in students:
            students[key]["negative_categories"].append(
                {"category": r["category"], "points": int(r["points"] or 0),
                 "count": int(r["n"] or 0)})
    result["students"] = [students[k] for k in sorted(students)]

    # 逐日趋势（含无事件的日期，保证折线连续）
    daily = {}
    for r in db.q(
            "SELECT event_date,"
            "SUM(CASE WHEN points>0 THEN points ELSE 0 END) AS pos,"
            "SUM(CASE WHEN points<0 THEN points ELSE 0 END) AS neg,"
            "SUM(points) AS net,COUNT(*) AS n FROM dom_behavior "
            "WHERE status='confirmed' AND event_date BETWEEN ? AND ? "
            "AND class_id IN (" + ph + ")" + crit_sql + " GROUP BY event_date", args):
        daily[r["event_date"]] = {
            "date": r["event_date"], "positive": int(r["pos"] or 0),
            "negative": int(r["neg"] or 0), "net": int(r["net"] or 0),
            "count": int(r["n"] or 0),
        }
    day, days = start, []
    while day <= end:
        days.append(daily.get(day.isoformat(), {
            "date": day.isoformat(), "positive": 0, "negative": 0,
            "net": 0, "count": 0}))
        day += timedelta(days=1)
    result["daily"] = days

    # 指标维度
    result["criteria_breakdown"] = [
        {"criteria_id": r["criteria_id"] or "", "category": r["category"],
         "direction": "praise" if int(r["points"] or 0) >= 0 else "improve",
         "points": int(r["points"] or 0), "count": int(r["n"] or 0)}
        for r in db.q(
            "SELECT COALESCE(criteria_id,'') AS criteria_id,category,"
            "SUM(points) AS points,COUNT(*) AS n FROM dom_behavior "
            "WHERE status='confirmed' AND event_date BETWEEN ? AND ? "
            "AND class_id IN (" + ph + ")" + crit_sql + " GROUP BY criteria_id,category "
            "ORDER BY points DESC", args)
    ]

    # 重点识别
    span = (end - start).days + 1
    prev1_end = start - timedelta(days=1)
    prev1_start = prev1_end - timedelta(days=span - 1)
    prev2_end = prev1_start - timedelta(days=1)
    prev2_start = prev2_end - timedelta(days=span - 1)
    prev1 = _stats_period_nets(class_ids, prev1_start, prev1_end, criteria_id)
    prev2 = _stats_period_nets(class_ids, prev2_start, prev2_end, criteria_id)

    focus = []
    for key in sorted(students):
        stu = students[key]
        reasons, rule_codes, rank = [], [], 0
        if stu["negative"] <= FOCUS_STUDENT_NEGATIVE:
            reasons.append("累计扣分 %d 分（阈值 ≤ %d）"
                           % (stu["negative"], FOCUS_STUDENT_NEGATIVE))
            rule_codes.append("STU_NEG_TOTAL")
            rank += 100 + abs(stu["negative"])
        for cat in stu["negative_categories"]:
            if cat["count"] >= FOCUS_CATEGORY_REPEAT:
                reasons.append("同类问题「%s」重复 %d 次（阈值 ≥ %d 次）"
                               % (cat["category"], cat["count"], FOCUS_CATEGORY_REPEAT))
                if "STU_CATEGORY_REPEAT" not in rule_codes:
                    rule_codes.append("STU_CATEGORY_REPEAT")
                rank += 80 + cat["count"]
        p1, p2 = prev1.get(key), prev2.get(key)
        if p1 and p2 and int(p1["n"] or 0) > 0 and int(p2["n"] or 0) > 0:
            n1, n2 = int(p1["net"] or 0), int(p2["net"] or 0)
            if n2 > n1 > stu["delta"]:
                reasons.append("近两个统计周期净分连续下降（%d → %d → %d）"
                               % (n2, n1, stu["delta"]))
                rule_codes.append("STU_NET_DECLINE")
                rank += 60 + abs(stu["delta"])
        if reasons:
            focus.append({"type": "student", "id": stu["student_id"],
                          "name": stu["name"] or stu["student_id"],
                          "class_id": stu["class_id"], "class_name": stu["class_name"],
                          "reasons": reasons, "rule_codes": rule_codes,
                          "score": stu["delta"], "_rank": rank})
    for key in sorted(class_map):
        cls = class_map[key]
        if cls["net"] <= FOCUS_CLASS_NET:
            focus.append({
                "type": "class", "id": cls["class_id"], "name": cls["name"],
                "class_id": cls["class_id"], "class_name": cls["name"],
                "reasons": ["班级净分 %d（阈值 ≤ %d）" % (cls["net"], FOCUS_CLASS_NET)],
                "rule_codes": ["CLASS_NET_LOW"],
                "score": cls["net"], "_rank": 200 + abs(cls["net"]),
            })
    focus.sort(key=lambda x: (-x["_rank"], x["score"], x["type"], x["id"]))
    for item in focus:
        item.pop("_rank", None)
    result["focus"] = focus
    return result


def _stats_notes(data, grade="", class_id="", criteria_id=""):
    r = data["range"]
    period_label = {"week": "本周", "month": "本月", "term": "本学期"}.get(
        r["period"], r["period"])
    return [
        "筛选条件：周期=%s；范围=%s~%s；年级=%s；班级=%s；指标=%s"
        % (period_label, r["start"], r["end"], grade or "全部", class_id or "全部",
           criteria_id or "全部"),
        "统计口径：仅统计已确认（confirmed）事件，待确认与作废不计分；"
        "学生基准分 100 分；区间仅作标签，不输出名次。",
    ]


def _stats_workbook(data, grade="", class_id="", criteria_id=""):
    headers = ["班级", "年级", "学生数", "加分", "扣分", "净分", "区间"]
    rows = []
    for c in data["classes"]:
        rows.append([c["name"], c["grade"] or "—", c["student_count"],
                     c["positive"], c["negative"], c["net"], c["band"]])
    rows.append([""])
    rows.append(["重点名单（按严重度降序）"])
    rows.append(["类型", "对象", "班级", "原因", "分数"])
    for f in data["focus"]:
        rows.append(["学生" if f["type"] == "student" else "班级",
                     f["name"], f.get("class_name") or "—",
                     "；".join(f["reasons"]), f["score"]])
    return roster._workbook("全校德育统计", headers, rows,
                            [16, 10, 10, 8, 8, 8, 10],
                            notes=_stats_notes(data, grade, class_id, criteria_id))


@router.get("/deyu/stats")
async def deyu_stats_view(request: Request):
    """全校德育统计：周期 / 年级 / 班级筛选，返回班级、学生、趋势、重点与指标明细。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    start, end, period, err = _stats_range(request)
    if err:
        return err
    class_id = (request.query_params.get("class_id") or "").strip()
    grade = (request.query_params.get("grade") or "").strip()
    criteria_id = (request.query_params.get("criteria_id") or "").strip()
    return _ok(deyu_stats(start, end, period, class_id, grade, criteria_id))


@router.get("/deyu/stats/export")
async def deyu_stats_export(request: Request):
    """导出全校德育统计 Excel：含筛选条件、统计口径、班级表与重点名单。"""
    user, denied = deyu_auth.deyu_or_401(request)
    if denied:
        return denied
    start, end, period, err = _stats_range(request)
    if err:
        return err
    class_id = (request.query_params.get("class_id") or "").strip()
    grade = (request.query_params.get("grade") or "").strip()
    criteria_id = (request.query_params.get("criteria_id") or "").strip()
    data = deyu_stats(start, end, period, class_id, grade, criteria_id)
    content = _stats_workbook(data, grade, class_id, criteria_id)
    name = "全校德育统计_%s.xlsx" % date.today().strftime("%Y%m%d")
    return Response(content=content, media_type=XLSX, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''%s" % quote(name)})
