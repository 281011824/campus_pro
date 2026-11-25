# -*- coding: utf-8 -*-
"""学生个人门户接口（只本人、无排名、不聚合他人）。

口径：
- 身份只认签名会话解析出的学号，不接受前端传学号查别人（越权 403）。
- 德育：本周，基准 100，仅 confirmed 计分；不返回班级均值、排名或他人明细。
- 考勤 / 作业：本周；无记录返回 null，前端显示「暂不可用」。
"""

from datetime import date, timedelta

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.services import student_auth
from tasks.shared import db
from tasks.modules.student import student_portal as portal

router = APIRouter()

BASE_SCORE = 100


def _ok(data):
    return {"code": 0, "message": "", "data": data}


def _err(status, message):
    return JSONResponse({"code": status, "message": message, "data": None},
                        status_code=status)


def _portal_error(exc):
    return _err(getattr(exc, "status", 400), str(exc))


async def _json_body(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise portal.InvalidInput("请求格式错误")
    if not isinstance(payload, dict):
        raise portal.InvalidInput("请求格式错误")
    return payload


def _own_assessment(stu, assessment_id):
    """测评归属校验：他人测评一律 404，不泄露是否存在。"""
    assessment = portal.get_assessment(assessment_id) if str(assessment_id).isdigit() else None
    if (not assessment
            or str(assessment["class_id"]) != str(stu["class_id"])
            or str(assessment["student_id"]) != str(stu["student_id"])):
        raise portal.NotFound("测评不存在")
    return assessment


def _week_range():
    today = date.today()
    start = today - timedelta(days=today.weekday())
    return today, start, start + timedelta(days=6)


def _class_meta(class_id):
    row = db.q("SELECT name,grade,major FROM classes WHERE class_id=?",
               (str(class_id),), one=True)
    return dict(row) if row else {}


@router.get("/student/me")
async def me(request: Request):
    """本人档案（字段白名单）：学号 / 姓名 / 班级 / 专业 / 年级。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    meta = _class_meta(stu["class_id"])
    return _ok({
        "student_id": stu["student_id"],
        "student_no": str(stu.get("student_no") or stu["student_id"]),
        "name": stu["name"],
        "class_id": stu["class_id"],
        "class_name": meta.get("name") or stu["class_id"],
        "major": stu.get("major") or meta.get("major") or "",
        "grade": stu.get("grade") or meta.get("grade") or "",
    })


@router.get("/student/moral")
async def moral(request: Request):
    """本周德育：基准 100，仅 confirmed 计分；每日净得分 + 事件明细。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    today, start, end = _week_range()
    rows = db.q(
        "SELECT event_date,category,points,fact FROM dom_behavior "
        "WHERE class_id=? AND student_id=? AND status='confirmed' "
        "AND event_date BETWEEN ? AND ? ORDER BY event_date, ts",
        (stu["class_id"], stu["student_id"], start.isoformat(), end.isoformat()))
    daily = {}
    for i in range(7):
        day = (start + timedelta(days=i)).isoformat()
        daily[day] = {"date": day, "net": 0, "count": 0}
    events, delta = [], 0
    for r in rows:
        points = int(r["points"] or 0)
        delta += points
        day = daily.get(r["event_date"])
        if day:
            day["net"] += points
            day["count"] += 1
        events.append({"date": r["event_date"], "category": r["category"],
                       "points": points, "fact": r["fact"] or ""})
    return _ok({
        "week": "%s~%s" % (start.isoformat(), end.isoformat()),
        "base_score": BASE_SCORE,
        "total_score": BASE_SCORE + delta,
        "week_delta": delta,
        "event_count": len(events),
        "daily": list(daily.values()),
        "events": events,
    })


@router.get("/student/attendance")
async def attendance(request: Request):
    """本周考勤：今日状态 + 逐日出勤 + 本周出勤率（仅本人）。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    today, start, end = _week_range()
    rows = db.q(
        "SELECT date,status FROM dom_attendance WHERE class_id=? AND student_id=? "
        "AND date BETWEEN ? AND ? ORDER BY date, session_no",
        (stu["class_id"], stu["student_id"], start.isoformat(), end.isoformat()))
    days = {}
    for i in range(7):
        day = (start + timedelta(days=i)).isoformat()
        days[day] = {"date": day, "status": None, "present": 0, "total": 0}
    today_statuses = []
    present = total = 0
    for r in rows:
        total += 1
        if r["status"] == "present":
            present += 1
        day = days.get(r["date"])
        if day:
            day["present"] += 1 if r["status"] == "present" else 0
            day["total"] += 1
            if not day["status"] or (r["status"] != "present" and day["status"] == "present"):
                day["status"] = r["status"]
        if r["date"] == today.isoformat():
            today_statuses.append(r["status"])
    today_status = None
    if today_statuses:
        today_status = "present"
        for bad in ("absent", "late", "leave"):
            if bad in today_statuses:
                today_status = bad
                break
    return _ok({
        "week": "%s~%s" % (start.isoformat(), end.isoformat()),
        "today": {"date": today.isoformat(), "status": today_status},
        "week_rate": round(present * 100.0 / total, 1) if total else None,
        "days": list(days.values()),
    })


@router.get("/student/homework")
async def homework(request: Request):
    """本周作业提交率与未交清单（仅本人）。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    _today, start, end = _week_range()
    rows = db.q(
        "SELECT date,subject,submitted FROM dom_homework WHERE class_id=? AND student_id=? "
        "AND date BETWEEN ? AND ? ORDER BY date, subject",
        (stu["class_id"], stu["student_id"], start.isoformat(), end.isoformat()))
    done = sum(1 for r in rows if int(r["submitted"] or 0))
    total = len(rows)
    missed = [{"date": r["date"], "subject": r["subject"] or "未分科"}
              for r in rows if not int(r["submitted"] or 0)]
    return _ok({
        "week": "%s~%s" % (start.isoformat(), end.isoformat()),
        "rate": round(done * 100.0 / total, 1) if total else None,
        "submitted": done,
        "total": total,
        "missed": missed,
    })


# ---------------------------------------------------------------- 成长首页 / 时间轴
@router.get("/student/home")
async def student_home(request: Request):
    """成长首页：档案 + 德育 + 考勤 + 作业 + 成长进度。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok(portal.home(stu["class_id"], stu["student_id"],
                           stu.get("student_no") or stu["student_id"], stu["name"]))


@router.get("/student/timeline")
async def student_timeline(request: Request,
                           kind: str = Query("all", alias="type"),
                           page: int = 1, size: int = 20):
    """成长时间轴：德育（仅 confirmed）/ 测评 / 考勤异常 / 作业未交 / 计划打卡。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        return _ok(portal.timeline(stu["class_id"], stu["student_id"], kind, page, size))
    except portal.PortalError as exc:
        return _portal_error(exc)


# ---------------------------------------------------------------- 待办
@router.get("/student/todos")
async def student_todos(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok(portal.todos(stu["class_id"], stu["student_id"]))


@router.post("/student/todos/{todo_id}/done")
async def student_todo_done(request: Request, todo_id: str):
    return await _todo_action(request, todo_id, "done")


@router.post("/student/todos/{todo_id}/ignore")
async def student_todo_ignore(request: Request, todo_id: str):
    return await _todo_action(request, todo_id, "ignore")


async def _todo_action(request: Request, todo_id: str, action: str):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        return _ok(portal.todo_action(stu["class_id"], stu["student_id"], todo_id, action))
    except portal.PortalError as exc:
        return _portal_error(exc)


# ---------------------------------------------------------------- 成长计划
@router.get("/student/plan")
async def student_plan(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok(portal.get_plan(stu["class_id"], stu["student_id"]))


@router.post("/student/plan/goals")
async def student_plan_add_goal(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        body = await _json_body(request)
        return _ok(portal.add_goal(stu["class_id"], stu["student_id"], body.get("text")))
    except portal.PortalError as exc:
        return _portal_error(exc)


@router.delete("/student/plan/goals/{goal_id}")
async def student_plan_delete_goal(request: Request, goal_id: str):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        portal.delete_goal(stu["class_id"], stu["student_id"], goal_id)
        return _ok({"deleted": True})
    except portal.PortalError as exc:
        return _portal_error(exc)


@router.post("/student/plan/checkin")
async def student_plan_checkin(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        body = await _json_body(request)
        return _ok(portal.checkin(stu["class_id"], stu["student_id"],
                                  body.get("date"), body.get("text")))
    except portal.PortalError as exc:
        return _portal_error(exc)


# ---------------------------------------------------------------- 隐私与家长绑定
@router.get("/student/privacy")
async def student_privacy(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok(portal.privacy(stu))


@router.post("/student/privacy/binding-code")
async def student_binding_code(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        return _ok(portal.create_bind_code(stu))
    except portal.PortalError as exc:
        return _portal_error(exc)


@router.delete("/student/privacy/bindings/{binding_id}")
async def student_revoke_binding(request: Request, binding_id: str):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        portal.revoke_binding(stu, binding_id)
        return _ok({"deleted": True})
    except portal.PortalError as exc:
        return _portal_error(exc)


# ---------------------------------------------------------------- 测评
@router.get("/student/assess")
async def student_assess(request: Request):
    """测评清单：批次与量表完成度。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok(portal.assess_overview(stu["class_id"], stu["student_id"]))


@router.post("/student/assess/{code}/start")
async def student_assess_start(request: Request, code: str):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        result = portal.start_assessment(stu["class_id"], stu["student_id"], code)
        return _ok({"assessment_id": result["assessment"]["id"],
                    "answered": result["answered"]})
    except portal.PortalError as exc:
        return _portal_error(exc)


@router.get("/student/assess/{assessment_id}/items")
async def student_assess_items(request: Request, assessment_id: int):
    """下发题目与已答：只给题号/题干/选项，不下发 reverse、dimension。"""
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        _own_assessment(stu, assessment_id)
        return _ok(portal.assessment_items(assessment_id))
    except portal.PortalError as exc:
        return _portal_error(exc)


@router.put("/student/assess/{assessment_id}/answers")
async def student_assess_answers(request: Request, assessment_id: int):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        _own_assessment(stu, assessment_id)
        body = await _json_body(request)
        return _ok(portal.save_answers(assessment_id, body.get("answers")))
    except portal.PortalError as exc:
        return _portal_error(exc)


@router.post("/student/assess/{assessment_id}/submit")
async def student_assess_submit(request: Request, assessment_id: int):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    try:
        _own_assessment(stu, assessment_id)
        return _ok(portal.submit_assessment(assessment_id))
    except portal.PortalError as exc:
        return _portal_error(exc)


# ---------------------------------------------------------------- 画像
@router.get("/student/profile")
async def student_profile(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok(portal.get_profile(stu["student_id"]))


@router.get("/student/profile/history")
async def student_profile_history(request: Request):
    stu, err = student_auth.student_or_error(request)
    if err:
        return err
    return _ok({"items": portal.profile_history(stu["student_id"])})
