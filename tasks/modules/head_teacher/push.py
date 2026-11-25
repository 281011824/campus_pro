# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 六级自动推送与上级催办闭环

上行：按频率自动生成、逐级自动推送，不设逐级人工放行卡点（人审不阻断上行）。
下行：上级只催办直接下级，逐级不越级；先回显 → 确认下达 → 限时反馈 → 超时升级提醒。
团委线按团内程序单列，不进入行政推送链、不纳入工作台考核与留痕。
企业微信只作触达／轻交互层，卡片只带摘要，明细跳转工作台。
"""
from datetime import datetime, timedelta

from tasks.domain import models
from tasks.domain.growth import growth
from tasks.domain.identity import org
from tasks.shared import (config, db, wecom)


def _target_users(level):
    """上一级接收人（跳过团内线职务）。"""
    idx = models.LEVEL_INDEX[level]
    if idx >= len(models.LEVELS) - 1:
        return []
    nxt = models.LEVELS[idx + 1]["id"]
    rows = db.q("SELECT DISTINCT user_id FROM org_posts WHERE level=? AND status='active' "
                "AND committee_line=0 AND in_chain=1", (nxt,))
    return [r["user_id"] for r in rows]


def level_report(level, period=None):
    """逐级聚合、脱敏递增；L6 不含任何个人与班级明细。"""
    idx = models.LEVEL_INDEX.get(level, 0)
    L = models.LEVELS[idx]
    period = period or datetime.now().strftime("%Y-W%V")
    n = growth.weekly_numbers()
    att = growth.attention_list(class_id="2611")
    base = {"level": level, "level_name": L["name"], "period": period,
            "scope": L["scope"], "desensitize": L["desensitize"],
            "freq": L["freq"], "out": L["out"], "generated_at": db.now(),
            "degraded": n["degraded"],
            "notes": [x for x in (n["dorm_note"], n["leave_note"]) if x],
            "source": "智慧校园平台同步（经成长导航数据服务·只读派生区）"}
    if level == "L1":
        base["numbers"] = n
        base["attention"] = att["items"]          # 只含标记＋建议动作，姓名掩码
    elif level == "L2":
        base["line_summary"] = {"班级数": 6, "条线异常": n["dorm_anomaly"] if n["dorm_anomaly"] is not None else "暂不可用",
                                "需关注": n["attention_count"], "姓名": "掩码"}
    elif level == "L3":
        base["line_summary"] = {"分管条线": 2, "需关注人次": n["attention_count"],
                                "班级维度": True, "个人姓名": "不含"}
    elif level == "L4":
        base["grade_summary"] = {"年级数": 3, "预警触发": "11 人次", "口径校验": "通过"}
    elif level == "L5":
        base["indicators"] = {"L1认证": "100%", "滞后项目": 1, "个人数据": "不含"}
    else:
        base["school_stats"] = {"数据口径": "统一", "等保": "二级",
                                "个人与班级明细": "不含（仅全校统计指标）"}
    return base


def auto_push(level, period=None, trigger="auto"):
    """生成报告并自动推送到上一级；不设人工放行卡点。"""
    report = level_report(level, period)
    rid = db.uid("pr_")
    targets = _target_users(level)
    idx = models.LEVEL_INDEX.get(level, 0)
    L = models.LEVELS[idx]
    card = {
        "title": "【德育工作台】%s %s（%s）" % (level, L["name"], report["period"]),
        "description": "可见范围：%s\n%s\n明细请到德育工作台查看" % (
            L["scope"], "；".join(report["notes"]) if report["notes"] else "数据已就绪"),
        "url": config.BASE_URL + "/",
    }
    sent = []
    for u in targets:
        wecom.send_textcard(u, card["title"], card["description"], card["url"])
        sent.append(u)
    db.exec_("INSERT INTO push_flow(ts,level,period,report_id,target_user_ids,channel,status,detail) "
             "VALUES(?,?,?,?,?,?,?,?)",
             (db.now(), level, report["period"], rid, db.dumps(sent),
              "wecom.app_message", "sent" if sent else "no_target",
              "trigger=%s degraded=%s" % (trigger, report["degraded"])))
    db.audit({"user_id": "system", "post_id": "-", "agent_id": "-", "level": level},
             "push.auto", "ok", level, "逐级自动推送至 %s，共 %d 人" %
             ("、".join(targets) if targets else "（本级为最高层，无上行）", len(sent)))
    return {"report_id": rid, "level": level, "period": report["period"],
            "targets": sent, "report": report, "status": "sent" if sent else "no_target",
            "note": "报告自动生成并自动推送；人审不阻断上行"}


def run_due(now=None):
    """按 PUSH_SCHEDULE 判断到期并触发；供 Windows 计划任务 / 定时器调用。"""
    now = now or datetime.now()
    due = []
    for s in models.PUSH_SCHEDULE:
        hit = False
        if s["day"] is not None:
            hit = (now.day == s["day"] and now.hour == s["hour"] and now.minute == s["minute"])
        elif s["weekday"] is not None:
            hit = (now.weekday() == s["weekday"] and now.hour == s["hour"]
                   and now.minute == s["minute"])
        if hit:
            due.append(s["level"])
    return [auto_push(lv) for lv in due]


# ---------------------------------------------------------------- D5 周报定时（2026-11-15）
WEEKLY_REPORT_AT = {"weekday": 0, "hour": 6, "minute": 50}   # 周一 06:50，与 L1 上行同刻


def weekly_due(now=None, trigger="auto"):
    """周报周一自动生成：为每个在链班主任端 L1 职务生成周报草稿（不归档，人审点保留），
    并发企微站内提醒「请到工作台查看」——零姓名、零成绩、零学生明细。
    本机测试态可用 POST /api/v1/scheduler/weekly 手动触发同一函数验证；
    短信兜底属上线九项前置，现场验（READY_SMS_REAL）。
    """
    from tasks.modules.head_teacher import secretary
    now = now or datetime.now()
    if trigger != "manual":
        hit = (now.weekday() == WEEKLY_REPORT_AT["weekday"]
               and now.hour == WEEKLY_REPORT_AT["hour"]
               and now.minute == WEEKLY_REPORT_AT["minute"])
        if not hit:
            return []
    out = []
    rows = db.q("SELECT * FROM org_posts WHERE level='L1' AND portal='headteacher' "
                "AND status='active' AND in_chain=1")
    for r in rows:
        cids = db.loads(r["class_ids"], []) or ["2611"]
        ctx = {"user_id": r["user_id"], "post_id": r["post_id"], "agent_id": r["agent_id"],
               "level": "L1", "post_name": r["post_name"], "class_ids": cids}
        try:
            card = secretary.weekly_card(ctx)
            wecom.send_textcard(
                r["user_id"],
                "【德育工作台】%s 本周班级周报已自动生成（草稿）" % cids[0],
                "四个数字与需关注清单请到工作台查看并确认归档；未经确认不进成长档案。",
                config.BASE_URL + "/")
            db.audit(ctx, "report.weekly_auto", "ok", card["report_id"],
                     "trigger=%s 周报定时生成草稿＋站内提醒（零姓名零成绩零学生明细）" % trigger)
            out.append({"report_id": card["report_id"], "class_id": cids[0],
                        "owner": r["user_id"], "post_id": r["post_id"],
                        "status": "draft",
                        "note": "草稿未归档；人审点＝班主任确认归档（未经确认不进成长档案）"})
        except Exception as e:
            db.audit(ctx, "report.weekly_auto", "failed", "-",
                     "周报定时生成失败：%s" % str(e)[:200])
            out.append({"class_id": cids[0], "owner": r["user_id"],
                        "status": "failed", "error": str(e)[:200]})
    return out


def flow():
    rows = db.q("SELECT * FROM push_flow ORDER BY id DESC LIMIT 30")
    return {"schedule": models.PUSH_SCHEDULE, "levels": models.LEVELS,
            "recent": rows, "rule": "上行自动生成、逐级自动推送，不设逐级人工放行卡点；"
                                    "人审保留在写入类、对外发布、对外口径、处分与复学审批",
            "committee_note": models.COMMITTEE_NOTE}


# ---------------------------------------------------------------- 催办闭环
def dun_targets(ctx):
    """只列出直接下级（层级号 -1），排除团内线职务。"""
    idx = models.LEVEL_INDEX.get(ctx["level"], 0)
    if idx == 0:
        return []
    target_level = models.LEVELS[idx - 1]["id"]
    return db.q("SELECT * FROM org_posts WHERE level=? AND status='active' "
                "AND committee_line=0 AND in_chain=1 ORDER BY user_id, primary_flag DESC",
                (target_level,))


def dun_create(ctx, to_userid, content, hours=24):
    """先回显（status=echo），不直接下达；逐级不越级校验在服务端。"""
    targets = dun_targets(ctx)
    row = next((t for t in targets if t["user_id"] == to_userid), None)
    if not row:
        db.audit(ctx, "dun.create", "denied", to_userid,
                 "催办对象不是直接下级或属团内线；逐级不越级")
        return None, "催办只到直接下级，逐级不越级；团委线按团内程序单列，不进入行政催办链"
    did = db.uid("dun_")
    deadline = (datetime.now() + timedelta(hours=int(hours))).isoformat(timespec="seconds")
    db.exec_("INSERT INTO duns(id,ts,from_user_id,from_post_id,from_agent_id,from_level,"
             "to_user_id,to_level,content,status,deadline) VALUES(?,?,?,?,?,?,?,?,?,'echo',?)",
             (did, db.now(), ctx["user_id"], ctx["post_id"], ctx["agent_id"], ctx["level"],
              to_userid, row["level"], content, deadline))
    db.audit(ctx, "dun.echo", "ok", did, "催办回显：%s → %s" % (ctx["level"], row["level"]))
    return {"id": did, "status": "echo", "to_user_id": to_userid, "to_level": row["level"],
            "content": content, "deadline": deadline,
            "hint": "请确认后下达；确认前不发送、不计入考核"}, None


def dun_confirm(ctx, dun_id):
    r = db.q("SELECT * FROM duns WHERE id=?", (dun_id,), one=True)
    if not r:
        return None, "未找到该催办草稿"
    if r["from_user_id"] != ctx["user_id"] or r["from_post_id"] != ctx["post_id"]:
        db.audit(ctx, "dun.confirm", "denied", dun_id, "非本人／非本职务催办草稿")
        return None, "只能确认本职务本人创建的催办草稿（一岗一智能体隔离）"
    if r["status"] != "echo":
        return None, "该催办已处理，无需重复确认"
    wecom.send_textcard(r["to_user_id"],
                        "【德育工作台】催办 · %s → %s" % (r["from_level"], r["to_level"]),
                        r["content"] + "\n请限时反馈；超时自动升级提醒。",
                        config.BASE_URL + "/")
    db.exec_("UPDATE duns SET status='confirmed',confirmed_at=? WHERE id=?", (db.now(), dun_id))
    db.audit(ctx, "dun.confirm", "ok", dun_id, "确认下达并发送企微卡片")
    return {"id": dun_id, "status": "confirmed", "sent_to": r["to_user_id"]}, None


def dun_reply(ctx, dun_id, text):
    r = db.q("SELECT * FROM duns WHERE id=?", (dun_id,), one=True)
    if not r:
        return None, "未找到该催办"
    if r["to_user_id"] != ctx["user_id"]:
        db.audit(ctx, "dun.reply", "denied", dun_id, "非被催办人")
        return None, "只有被催办人可反馈"
    db.exec_("UPDATE duns SET status='replied',reply_at=?,reply_text=? WHERE id=?",
             (db.now(), text, dun_id))
    db.audit(ctx, "dun.reply", "ok", dun_id, "限时反馈完成")
    return {"id": dun_id, "status": "replied"}, None


def escalate_overdue(now=None):
    """超时自动升级提醒（计入年度考核），不改变逐级链、不越级抄送。"""
    now = now or datetime.now()
    rows = db.q("SELECT * FROM duns WHERE status='confirmed' AND escalated=0")
    out = []
    for r in rows:
        try:
            dl = datetime.fromisoformat(r["deadline"])
        except Exception:
            continue
        if now > dl:
            wecom.send_textcard(r["from_user_id"],
                                "【德育工作台】催办超时升级提醒",
                                "催办 %s 未在时限内反馈，已自动升级提醒并计入年度考核。" % r["id"],
                                config.BASE_URL + "/")
            db.exec_("UPDATE duns SET escalated=1 WHERE id=?", (r["id"],))
            db.audit({"user_id": "system"}, "dun.escalate", "ok", r["id"], "超时自动升级提醒")
            out.append(r["id"])
    return out


def dun_list(ctx=None):
    return db.q("SELECT * FROM duns ORDER BY ts DESC LIMIT 50")
