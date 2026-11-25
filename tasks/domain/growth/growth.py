# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 成长导航「只读派生区」数据服务客户端

硬约束（v0.10）：
1. 秘书只访问成长导航数据服务 API，**不直连智慧校园平台**（172.16.7.12:8026）；
2. 教师端物理上不查 answers / scores，越权 HTTP 403 并写审计（ZONE_MATRIX）；
3. 字段白名单外（家长电话／请假事由等）一律不进模型上下文；
4. 当前只读 MCP 工具仅 5 个，画像仅学籍／归寝／请假三类，不得称完整画像；
5. 归寝只认「数据就绪日」，未就绪≠未归；请假与归寝口径未对齐即暂停该数字；
6. 任一数据域失败或口径异常 → 标注「暂不可用」，禁止旧值／估算值填充。

v0.11 新增（2607 成长导航系统试点班）：
7. 支持按 class_id 切换只读派生区快照（2611 脱敏示例／2607 真实拉取脱敏汇总）；
8. 2607 教师端派生区（四维平衡／六级目标／成长画像／优势标签）尚未绑定，
   一律降级返回 available=false，不以 2611 示例值或旧值替代；
9. 2607 归寝聚合 leave=0 与请假表 2 条病假口径未对齐，暂停请假数字。
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tasks.domain import models
from tasks.domain.growth import datadomains
from tasks.shared import (config, db)

DATA_DIR = config.ROOT / "data"
FIXTURE_PATHS = {
    "2611": DATA_DIR / "fixtures.json",          # 脱敏示例数据（原型基准）
    "2607": DATA_DIR / "fixtures_2607.json",     # 成长导航系统试点班·真实拉取脱敏汇总
}
DEFAULT_CLASS = "2611"
CACHE = {}


class Forbidden(Exception):
    """派生区越权 → HTTP 403。"""


class ToolNotReady(Exception):
    """调用了尚未跑通的工具。"""


def fixture(class_id=DEFAULT_CLASS):
    """按班级返回只读派生区快照；未知班级回退 2611，不臆造数据。"""
    cid = str(class_id or DEFAULT_CLASS)
    if cid not in FIXTURE_PATHS:
        cid = DEFAULT_CLASS
    if cid not in CACHE:
        CACHE[cid] = json.loads(FIXTURE_PATHS[cid].read_text(encoding="utf-8"))
    return CACHE[cid]


def pilot_classes():
    """试点班清单与口径区分（2611 ≠ 2607，不得混用）。"""
    out = []
    for cid, path in FIXTURE_PATHS.items():
        f = fixture(cid)
        meta = f.get("_meta", {})
        out.append({
            "class_id": cid,
            "name": f["class"]["name"],
            "size": f["class"]["size"],
            "kind": "成长导航系统试点班·真实拉取脱敏汇总" if meta.get("pilot")
                    else "原型脱敏示例数据（一期基准班）",
            "pulled_at": meta.get("pulled_at", meta.get("generated", "")),
            "ready_date": meta.get("ready_date", ""),
            "reconcile_conflict": bool(meta.get("reconcile_conflict")),
            "derived_pending": bool(meta.get("derived_pending")),
            "coverage_ready": meta.get("coverage_ready", models.COVERAGE_READY),
            "coverage_pending": meta.get("coverage_pending", models.COVERAGE_PENDING),
            "fixture_file": path.name,
        })
    return {"classes": out,
            "rule": "2611 为一期学生成长智能助手／AI 教学试点班示例数据；2607 为本次接入的成长导航系统试点班（真实拉取脱敏汇总）。两者口径不同，不得混用、不得互相替代",
            "default_class": DEFAULT_CLASS}


def _pending_view(class_id, view):
    """2607 未就绪的派生区视图统一降级（不估算、不填旧值、不拿示例值替代）。"""
    f = fixture(class_id)
    return {
        "available": False,
        "class_id": str(class_id),
        "view": view,
        "reason": f.get("_meta", {}).get("derived_pending_note",
                 "成长导航教师端派生区尚未绑定本班，该结论暂不可用"),
        "rule": "不以旧值／估算值／其他班示例值替代；本级报告暂停该数字（已通知信息化处）",
        "source": _source(),
    }


def _is_derived_pending(class_id):
    return bool(fixture(class_id).get("_meta", {}).get("derived_pending"))


# ---------------------------------------------------------------- 字段白名单
def whitelist(payload):
    """白名单外字段一律剔除；不递归信任上游返回。"""
    if isinstance(payload, list):
        return [whitelist(x) for x in payload]
    if not isinstance(payload, dict):
        return payload
    out = {}
    for k, v in payload.items():
        if k in models.FIELD_BLACKLIST or k in models.FORBIDDEN_DB_FIELDS:
            continue
        out[k] = whitelist(v)
    return out


def assert_derived(requested_fields, ctx=None):
    """教师端接口在服务端做 ZONE_MATRIX 校验，不是界面隐藏。"""
    bad = [f for f in (requested_fields or []) if f in models.FORBIDDEN_DB_FIELDS]
    if bad:
        db.audit(ctx, "derived.forbidden", "denied", "answers/scores",
                 "请求禁查字段：" + ",".join(bad))
        raise Forbidden("无权访问：教师端只读派生区，物理上不查 answers／scores 等字段")
    return True


def _source():
    return "智慧校园平台同步（经成长导航数据服务·只读派生区）"


def _week_range():
    from datetime import date, timedelta
    d = date.today()
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _http_get(path, params=None):
    # 唯一出口＝成长导航数据服务；绝不把智慧校园平台地址拼进请求 URL
    if (config.NO_DIRECT_CAMPUS_ACCESS and
            ("172.16.7.12" in config.GROWTH_NAV_BASE or "campus" in path.lower())):
        raise ToolNotReady("秘书禁止直连智慧校园平台，只走成长导航数据服务 API")
    url = config.GROWTH_NAV_BASE.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=5) as r:
        return whitelist(json.loads(r.read().decode("utf-8")))


# ---------------------------------------------------------------- 5 个已跑通的只读 MCP 工具
def _tool(name, ctx=None, **kwargs):
    if name not in [t["name"] for t in models.MCP_TOOLS]:
        db.audit(ctx, "mcp.tool_not_ready", "denied", name)
        raise ToolNotReady("当前 growth-agent 仅跑通 5 个只读工具；%s 尚未接入" % name)
    db.audit(ctx, "mcp.call", "ok", name)
    cid = str(kwargs.get("class_id", DEFAULT_CLASS))
    if config.GROWTH_NAV_MODE == "http":
        return _http_get("/mcp/" + name, kwargs)
    f = fixture(cid)
    if name == "get_class_summary":
        c = f["class"]
        data = dict(c)
        data["leave_count"] = f["leave_count"]
        data["reconcile_conflict"] = f["leave_count"] != f["dorm_leave_count"]
        data["reconcile_note"] = f.get("reconcile_note", "") if data["reconcile_conflict"] else ""
        data["source"] = _source()
        return whitelist(data)
    if name == "list_class_unreturned":
        date = kwargs.get("date")
        if date and date not in f["dorm"]["ready_dates"]:
            return {"status": "未就绪", "date": date,
                    "note": models.DATA_READY_NOTE, "source": _source()}
        return {"status": "就绪", "date": date or f["dorm"]["ready_dates"][-1],
                "unreturned": whitelist(f["dorm"]["unreturned"]),
                "late": whitelist(f["dorm"]["late"]),
                "missing_info": whitelist(f["dorm"]["missing_info"]),
                "source": _source()}
    if name == "get_warning_summary":
        return {"warning_count": f["warning"]["count"],
                "items": whitelist(f["warning"]["items"]),
                "text_rule": "只写「需人工关注」与事实，不写结论、不带请假事由",
                "source": _source()}
    if name == "get_student_profile":
        sid = kwargs.get("student_id")
        row = next((s for s in f["students"] if s["student_id"] == sid), None)
        if not row:
            return None
        # 当前画像仅学籍／归寝／请假三类，不得补算成绩／德育
        return whitelist(dict(row, coverage=models.COVERAGE_READY,
                              not_connected=models.COVERAGE_PENDING,
                              note=models.NO_FULL_PROFILE, source=_source()))
    if name == "get_consecutive_unreturned":
        date = kwargs.get("date")
        if date and date not in f["dorm"]["ready_dates"]:
            return {"status": "未就绪", "note": models.DATA_READY_NOTE, "source": _source()}
        days = f["dorm"]["consecutive_unreturned"].get(kwargs.get("student_id"), 0)
        gap = f["dorm"].get("gap_days", [])
        return {"student_id": kwargs.get("student_id"), "days": days,
                "chain_truncated": bool(gap),
                "note": "链条遇缺口日提示截断、不补算" if gap else "只计数据就绪日",
                "source": _source()}
    return None


def call_tool(name, ctx=None, **kwargs):
    try:
        return {"ok": True, "tool": name, "data": _tool(name, ctx, **kwargs)}
    except ToolNotReady as e:
        return {"ok": False, "tool": name, "available": False, "reason": str(e)}


# ---------------------------------------------------------------- 派生区视图（28/29/30/57）
def class_overview(ctx=None, class_id=DEFAULT_CLASS):
    """28 号：班级概览 4 数字，只读派生区、不查 answers/scores。"""
    assert_derived([], ctx)
    live = datadomains.weekly_numbers(class_id)
    if live:
        return whitelist({
            "class_id": str(class_id),
            "attendance_rate": live["attendance_rate"],
            "attention_count": live["attention_count"],
            "balance_unbalanced": None,
            "role_registered": fixture(class_id)["class"]["role_registered"],
            "leave_count": live["leave_count"],
            "leave_reconcile": "已对齐（请假与晚寝同一权威来源）",
            "source": live["source"], "zone": "数据域聚合（不查 answers／scores）",
            "attendance_note": live.get("attendance_note"),
            "moral_note": live.get("moral_note"),
        })
    f = fixture(class_id)
    conflict = f["leave_count"] != f["dorm_leave_count"]
    out = {
        "class_id": str(class_id),
        "attendance_rate": f["class"]["attendance_rate"],
        "attention_count": len(f["attention"]),
        "balance_unbalanced": f["balance_unbalanced"],
        "role_registered": f["class"]["role_registered"],
        "leave_count": None if conflict else f["leave_count"],
        "leave_reconcile": (f.get("reconcile_note") or models.RECONCILE_NOTE)
                           if conflict else "已对齐",
        "source": _source(), "zone": "派生区（不查 answers／scores）",
    }
    if f["class"].get("attendance_note"):
        out["attendance_note"] = f["class"]["attendance_note"]
    if f["class"].get("moral_note"):
        out["moral_note"] = f["class"]["moral_note"]
    if f.get("_meta", {}).get("derived_pending"):
        out["derived_pending"] = True
        out["derived_pending_note"] = f["_meta"]["derived_pending_note"]
    return whitelist(out)


def attention_list(ctx=None, class_id=DEFAULT_CLASS):
    """29 号：只返回标记＋建议动作＋状态，不含原因与分数。"""
    live = datadomains.weekly_numbers(class_id)
    if live:
        items = datadomains.attention_items(class_id, *_week_range())
        return {"class_id": str(class_id), "items": whitelist(items),
                "note": "不含原因与分数；不含心理明细；仅列命中规则的少数学生",
                "source": live["source"]}
    f = fixture(class_id)
    items = [{k: it[k] for k in ("student_id", "name_masked", "mark", "action", "status")}
             for it in f["attention"]]
    return {"class_id": str(class_id), "items": whitelist(items),
            "note": "不含原因与分数；不含心理明细", "source": _source()}


def student_derived(ctx=None, student_id=None, class_id=DEFAULT_CLASS):
    """30 号：growthScore／balance 布尔／psychReferred 布尔，心理内容不过河。"""
    if _is_derived_pending(class_id):
        return _pending_view(class_id, "student_derived")
    f = fixture(class_id)
    row = f["derived_profiles"].get(student_id) or {}
    return whitelist({
        "student_id": student_id,
        "growthScore": row.get("growthScore"),
        "balance": row.get("balance"),
        "psychReferred": row.get("psychReferred"),
        "mark": row.get("mark"), "action": row.get("action"),
        "share": row.get("share"), "src": row.get("src"),
        "note": "心理内容永不过河；不含 answers／scores 原文", "source": _source(),
    })


def balance_view(ctx=None, class_id=DEFAULT_CLASS):
    """57 号：只返回本班四维失衡人数与需关注数，不含明细。"""
    if _is_derived_pending(class_id):
        return _pending_view(class_id, "balance")
    f = fixture(class_id)
    return {"class_id": str(class_id),
            "balance": [{"k": x["k"], "v": x["v"], "s": x["s"]} for x in f["balance"]],
            "unbalanced_count": f["balance_unbalanced"],
            "attention_count": len(f["attention"]),
            "note": "四维平衡＝学习／交友／兴趣／健康；≠ 班主任工作四项；个人目标文本／打卡明细不可见",
            "source": _source()}


def goal_progress(ctx=None, class_id=DEFAULT_CLASS):
    """六级目标班级派生进度：不返回个人目标正文。"""
    if _is_derived_pending(class_id):
        return _pending_view(class_id, "goals")
    f = fixture(class_id)
    return whitelist({"class_id": str(class_id), **f["goals"],
                      "note": "六级目标＝三年／年／学期／月／周／日；目标设定权归学生本人，禁止代设／代改／代打卡",
                      "source": _source()})


def growth_profile(ctx=None, class_id=DEFAULT_CLASS):
    """派生区结论：优势／隐形优势标签、赛道建议、复核状态、建议动作。"""
    if _is_derived_pending(class_id):
        return _pending_view(class_id, "growth_profile")
    f = fixture(class_id)
    return whitelist({"class_id": str(class_id), "tags": f["derived_tags"],
                      "advice": f["derived_advice"],
                      "note": "不出八维雷达图、维度分、原始作答", "source": _source()})


# ---------------------------------------------------------------- 尚未接入的数据域（降级不估算）
NOT_CONNECTED = {
    "scores": "成绩／学情：教务系统与 AI 批改系统待二期 P0 接口接入，当前画像不含该域",
    "attendance": "考勤：待智慧校园平台二期 P0 接口",
    "moral": "德育：待接入（德育记录走底线轨校纪台账，两轨不串用）",
    "psych": "心理：心理区独立库独立密钥，教师端永不可见明细",
}


def work_item(ctx=None, item="scores", class_id=DEFAULT_CLASS):
    """班主任工作四项取数：已就绪的走派生区；未接入的一律返回 available=false。"""
    if item in ("scores", "attendance", "moral", "psych"):
        db.audit(ctx, "growth.not_connected", "degraded", item, NOT_CONNECTED[item])
        return {"available": False, "item": item, "class_id": str(class_id),
                "reason": NOT_CONNECTED[item],
                "rule": "不以旧值或估算值替代；本级报告暂停该数字"}
    return {"available": True, "item": item, "class_id": str(class_id),
            "data": "派生区结论", "source": _source()}


def readiness(ctx=None, class_id=DEFAULT_CLASS):
    f = fixture(class_id)
    return {
        "mcp_service": "growth-agent",
        "mcp_tools": models.MCP_TOOLS,
        "coverage_ready": models.COVERAGE_READY,
        "coverage_pending": models.COVERAGE_PENDING,
        "no_full_profile": models.NO_FULL_PROFILE,
        "permission_risk": "当前单 token 为校长角色、工具不做学生范围过滤；正式给班主任试用前必须换成按角色／班级过滤 token",
        "token_scope": config.TOKEN_SCOPE,
        "token_scope_ok": config.TOKEN_SCOPE == "role_class",
        "data_ready_note": models.DATA_READY_NOTE,
        "reconcile_note": models.RECONCILE_NOTE,
        "field_whitelist": models.FIELD_WHITELIST,
        "field_blacklist": models.FIELD_BLACKLIST,
        "no_direct_platform_access": config.NO_DIRECT_CAMPUS_ACCESS,
        "code_baseline": config.CODE_BASELINE,
        "sync_tasks": config.SYNC_TASKS,
        "pilot_classes": pilot_classes()["classes"],
        "current_class": str(class_id),
        "class_ready_date": f.get("_meta", {}).get("ready_date", ""),
        "derived_pending": bool(f.get("_meta", {}).get("derived_pending")),
        "reconcile_conflict": bool(f.get("_meta", {}).get("reconcile_conflict")),
    }


def weekly_numbers(ctx=None, class_id=DEFAULT_CLASS):
    """周报 4 数字：任一域失败/口径异常即标注暂不可用，不估算、不填旧值。"""
    live = datadomains.weekly_numbers(class_id)
    if live:
        return live
    f = fixture(class_id)
    conflict = f["leave_count"] != f["dorm_leave_count"]
    dorm_ready = f["dorm"]["today_ready"]
    return {
        "class_id": str(class_id),
        "attendance_rate": f["class"]["attendance_rate"],
        "attendance_note": f["class"].get("attendance_note"),
        "attention_count": len(f["attention"]),
        "moral_delta": f["class"]["moral_delta"],
        "moral_note": f["class"].get("moral_note"),
        "dorm_anomaly": f["dorm"]["anomaly_count"] if dorm_ready else None,
        "dorm_note": None if dorm_ready else "暂不可用：当日查寝数据未生成（未就绪≠未归），已通知信息化处",
        "leave_note": (f.get("reconcile_note") or models.RECONCILE_NOTE) if conflict else None,
        "degraded": (not dorm_ready) or conflict
                    or f["class"]["attendance_rate"] is None
                    or f["class"]["moral_delta"] is None,
        "source": _source(),
    }


def class_snapshot(class_id="2607"):
    """试点班脱敏汇总快照（供 /api/v1/pilot 使用；不返回名单明细）。"""
    f = fixture(class_id)
    meta = f.get("_meta", {})
    c = f["class"]
    d = f["dorm"]
    out = {
        "class_id": str(class_id),
        "name": c["name"],
        "size": c["size"],
        "boys": c["boys"], "girls": c["girls"],
        "boarding": c["boarding"], "day": c["day"],
        "grade": c.get("grade", ""),
        "enroll_status": c.get("enroll_status", ""),
        "major_distribution": c.get("major_distribution", {}),
        "pulled_at": meta.get("pulled_at", ""),
        "source_system": meta.get("source_system", ""),
        "source_api": meta.get("source_api", ""),
        "ready_date": meta.get("ready_date", ""),
        "ready_dates": d.get("ready_dates", []),
        "dorm_ready_note": d.get("ready_note", ""),
        "dorm": {
            "returned": d.get("returned_count"), "late": d.get("late_count"),
            "unreturned": d.get("unreturned_count"), "missing": d.get("missing_count"),
            "leave": d.get("leave_count_dorm"), "anomaly_count": d.get("anomaly_count"),
        },
        "warning": {"count": f["warning"]["count"], "items": whitelist(f["warning"]["items"])},
        "leave_table_count": f["leave_count"],
        "dorm_leave_count": f["dorm_leave_count"],
        "reconcile_conflict": bool(meta.get("reconcile_conflict")),
        "reconcile_note": f.get("reconcile_note", ""),
        "coverage_ready": meta.get("coverage_ready", models.COVERAGE_READY),
        "coverage_pending": meta.get("coverage_pending", models.COVERAGE_PENDING),
        "derived_pending": bool(meta.get("derived_pending")),
        "derived_pending_note": meta.get("derived_pending_note", ""),
        "no_full_profile": meta.get("no_full_profile", models.NO_FULL_PROFILE),
        "field_whitelist": meta.get("field_whitelist", models.FIELD_WHITELIST),
        "no_real_names": True,
        "rule": "仅落地聚合数字＋合成掩码名单；真实姓名／学号／宿舍／家长电话／请假事由不进样本、不进模型上下文",
    }
    return whitelist(out)
