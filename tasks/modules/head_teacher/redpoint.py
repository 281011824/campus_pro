# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 「本周待确认红点」集中待办（四个智能入口之四）

依据：《系统文档_v1.0\\03》3.1 四个智能入口；本模块 2026-11-15 按
《班主任端_D1-D6逐项完善与补齐规格_v1.0.md》§三（D2）与 §五（D4 方案 B）落地：
  - 入口名：本周待确认红点（集中待办），独立于「待确认写入」两段式草稿
  - 数据来源：预警转介单、家长告知事项（人工登记）、上周未销号项；只读派生区，
    不含成绩／心理明细
  - 三类动作：转介（→L2 台账）、告知（人工签发，秘书不代发）、销号（人审后留痕）
  - 字段：item_id / kind / created_at / owner_post_id / status / handled_at / audit_triple；
    不含姓名、成绩、家长电话
  - 红线：不推家长；对外发布须人工签发；只写事实不写结论；销号留三元组审计
  - 销号后不再出现；空态显示「本周无待确认」，不摆示例数据

D3 边界（不代写规则）：四色预警 12 条规则与影子模式归政教处＋招就处按 04 第三节审定；
本模块只提供 state() 如实报告「规则 0/12、影子模式未启动」，并承接劝返台账的
转介单侧（L2 回执三态：已接收／处置中／已销号），不写台账本体、不作定性。
"""
from datetime import datetime

from tasks.domain.growth import growth
from tasks.shared import db

# 事由分类（只写事实分类，不写结论、不带请假事由）
CATEGORIES = ("归寝异常", "缺勤关注", "学业联系", "行为观察", "家长告知", "其他")

# D3 六件套状态（如实报告，不把「已出规格」写成「已跑通」）
WARNING_STATE = {
    "rules_total": 12,
    "rules_approved": 0,
    "shadow_mode": "未启动（首版 12 条规则待政教处＋招就处按建设路线图 04 第三节审定）",
    "monthly_false_positive": "未开始（影子期结束出对比报告后才有月误报统计）",
    "referral_slips": "已就绪（L1 事实转介 → L2 劝返台账三态回执，见 /api/v1/todo/referrals）",
    "enroll_change_7": "留痕字段已规划（七类异动枚举待教务处确认口径，不反推为处分依据）",
    "retention_snapshot": "按月快照框架已规划（缺口日标注不估算，待贴源后启用）",
    "note": "本视图只如实报告缺口状态；规则内容不由系统代写，影子期内不推送、不进考核",
}

ENROLL_CHANGE_TYPES = ("转学", "休学", "复学", "退学", "转专业", "留级", "跳级")


def _week_key(now=None):
    return (now or datetime.now()).strftime("%G-W%V")


def _prev_week_key(now=None):
    from datetime import timedelta
    d = (now or datetime.now()) - timedelta(days=7)
    return d.strftime("%G-W%V")


def _class_of(ctx):
    cids = ctx.get("class_ids") or ["2611"]
    return str(cids[0])


def _ctx_triple(ctx):
    return (ctx.get("user_id", "-"), ctx.get("post_id", "-"), ctx.get("agent_id", "-"))


# ---------------------------------------------------------------- 查询
def list_items(ctx):
    """本周待确认＝本周新增＋上周未销号；销号项不再出现。"""
    cid = _class_of(ctx)
    wk, pv = _week_key(), _prev_week_key()
    rows = db.q(
        "SELECT * FROM todo_items WHERE class_id=? AND (week=? OR (week=? AND status='open')) "
        "ORDER BY ts DESC", (cid, wk, pv))
    items = [{
        "item_id": r["id"], "kind": r["kind"], "created_at": r["ts"],
        "owner_post_id": r["owner_post_id"], "status": r["status"],
        "student_id": r["student_id"], "category": r["category"], "fact": r["fact"],
        "week": r["week"], "handled_at": r["handled_at"], "handled_by": r["handled_by"],
        "audit_triple": [r["owner_user_id"], r["owner_post_id"], r["owner_agent_id"]],
    } for r in rows]
    open_n = sum(1 for x in items if x["status"] == "open")
    return {
        "class_id": cid, "week": wk, "items": items, "open_count": open_n,
        "empty_text": "本周无待确认" if not items else "",
        "kinds": {"referral": "预警转介（→L2 台账）", "notify": "家长告知（人工签发，秘书不代发）",
                  "carryover": "上周未销号"},
        "rule": "集中待办独立于两段式写入草稿；不含姓名、成绩、家长电话；销号留三元组审计、销号后不再出现",
        "note": "数据来源只读派生区（预警事实／人工登记），空态不摆示例数据",
    }


def slips(ctx=None):
    """转介单列表：L1 看本班；行政端 L2+ 看全部（劝返台账入口，只写事实）。"""
    if ctx and ctx.get("level") in ("L2", "L3", "L4", "L5", "L6"):
        rows = db.q("SELECT * FROM referral_slips ORDER BY ts DESC LIMIT 100")
    else:
        cid = _class_of(ctx or {})
        rows = db.q("SELECT * FROM referral_slips WHERE class_id=? ORDER BY ts DESC LIMIT 100", (cid,))
    return [{
        "slip_id": r["id"], "todo_id": r["todo_id"], "created_at": r["ts"],
        "class_id": r["class_id"], "student_id": r["student_id"],
        "category": r["category"], "fact": r["fact"],
        "status": r["status"],                      # pending / received / processing / closed
        "status_text": {"pending": "待接收", "received": "已接收", "processing": "处置中",
                        "closed": "已销号"}.get(r["status"], r["status"]),
        "received_at": r["received_at"], "closed_at": r["closed_at"],
        "created_by": [r["created_by_user"], r["created_by_post"]],
        "l2_states": ["已接收", "处置中", "已销号"],
    } for r in rows]


def state():
    return dict(WARNING_STATE)


# ---------------------------------------------------------------- 动作（全部写审计）
def refer(ctx, student_id, category):
    """转介：从本班需关注／预警事实生成转介单（D4 方案 B：只出转介单，不写台账本体）。"""
    if category not in CATEGORIES:
        return None, "事由分类只能是：" + "、".join(CATEGORIES)
    cid = _class_of(ctx)
    # 只写事实：事实取自只读派生区该生已有标记（不含原因与分数），不新增任何判断
    att = growth.attention_list(ctx, cid).get("items", [])
    row = next((x for x in att if x.get("student_id") == student_id), None)
    if row is None:
        db.audit(ctx, "todo.refer", "denied", str(student_id),
                 "该生不在本班需关注清单（只读派生区），不能凭空转介")
        return None, "该生不在本班需关注清单（只读派生区），不能凭空转介；只写事实、不作定性"
    fact = "派生区标记：%s；建议动作：%s" % (row["mark"], row["action"])
    tid, rid = db.uid("td_"), db.uid("rf_")
    db.exec_("INSERT INTO todo_items(id,ts,week,owner_user_id,owner_post_id,owner_agent_id,"
             "class_id,kind,student_id,category,fact,status,created_via) "
             "VALUES(?,?,?,?,?,?,?,?,?,?,?, 'open','refer')",
             (tid, db.now(), _week_key(), ctx["user_id"], ctx["post_id"], ctx["agent_id"],
              cid, "referral", student_id, category, fact))
    db.exec_("INSERT INTO referral_slips(id,ts,todo_id,class_id,student_id,category,fact,"
             "status,created_by_user,created_by_post) VALUES(?,?,?,?,?,?,?,'pending',?,?)",
             (rid, db.now(), tid, cid, student_id, category, fact,
              ctx["user_id"], ctx["post_id"]))
    db.audit(ctx, "todo.refer", "ok", rid,
             "转介单 %s（%s / %s）：只写事实，L2 劝返台账回执三态" % (rid, student_id, category))
    return {"todo_id": tid, "slip_id": rid, "class_id": cid, "student_id": student_id,
            "category": category, "fact": fact, "l2_status": "pending",
            "l2_owner": "政教处／招就处（劝返台账，落点按 D4 现场确认）",
            "note": "转介只写事实不作定性；L2 回执三态：已接收／处置中／已销号；不回流学生明细"}, None


def note(ctx, category):
    """家长告知事项登记：只记事由分类与时间；对外发布须人工签发，秘书不代发。"""
    if category not in CATEGORIES:
        return None, "事由分类只能是：" + "、".join(CATEGORIES)
    cid = _class_of(ctx)
    tid = db.uid("td_")
    db.exec_("INSERT INTO todo_items(id,ts,week,owner_user_id,owner_post_id,owner_agent_id,"
             "class_id,kind,category,fact,status,created_via) "
             "VALUES(?,?,?,?,?,?,?,?,?, '人工登记（家长告知事项）', 'open','note')",
             (tid, db.now(), _week_key(), ctx["user_id"], ctx["post_id"], ctx["agent_id"],
              cid, "notify", category))
    db.audit(ctx, "todo.note", "ok", tid,
             "家长告知事项登记（%s）：人工签发、秘书不代发、不存家长联系方式" % category)
    return {"todo_id": tid, "class_id": cid, "category": category,
            "rule": "对外发布须人工签发；不推家长、不代发、不留家长电话／住址／请假事由"}, None


def close(ctx, item_id):
    """销号：人审后留痕；销号后该项不再出现在待确认列表。"""
    r = db.q("SELECT * FROM todo_items WHERE id=?", (item_id,), one=True)
    if not r:
        return None, "未找到该待确认项"
    if r["class_id"] != _class_of(ctx):
        db.audit(ctx, "todo.close", "denied", item_id, "跨班销号被拒")
        return None, "只能销号本班待确认项"
    if r["status"] == "closed":
        return None, "该项已销号，无需重复操作"
    db.exec_("UPDATE todo_items SET status='closed',handled_at=?,handled_by=? WHERE id=?",
             (db.now(), ctx["user_id"], item_id))
    db.audit(ctx, "todo.close", "ok", item_id,
             "销号（人审后留痕）：userid＋post_id＋agent_id 三元组审计")
    if r["kind"] == "referral":
        db.exec_("UPDATE referral_slips SET status='closed',closed_at=?,closed_by=? WHERE todo_id=?",
                 (db.now(), ctx["user_id"], item_id))
    return {"item_id": item_id, "status": "closed", "handled_at": db.now(),
            "audit_triple": list(_ctx_triple(ctx))}, None


def receipt(ctx, slip_id, state_):
    """L2 回执三态（已接收／处置中／已销号）：只行政端 L2 及以上可回执，不回流学生明细。"""
    if ctx.get("level") not in ("L2", "L3", "L4", "L5", "L6"):
        db.audit(ctx, "todo.receipt", "denied", slip_id, "非行政端层级，无 L2 台账回版权限")
        return None, "回执只属行政端（政教处／招就处劝返台账侧），班主任端只读"
    mp = {"received": "已接收", "processing": "处置中", "closed": "已销号"}
    if state_ not in mp:
        return None, "回执状态只能是：received（已接收）／processing（处置中）／closed（已销号）"
    r = db.q("SELECT * FROM referral_slips WHERE id=?", (slip_id,), one=True)
    if not r:
        return None, "未找到该转介单"
    if state_ == "received":
        db.exec_("UPDATE referral_slips SET status='received',received_at=?,received_by=? WHERE id=?",
                 (db.now(), ctx["user_id"], slip_id))
    elif state_ == "processing":
        db.exec_("UPDATE referral_slips SET status='processing',received_at=COALESCE(received_at,?),"
                 "received_by=COALESCE(received_by,?) WHERE id=?",
                 (db.now(), ctx["user_id"], slip_id))
    else:
        db.exec_("UPDATE referral_slips SET status='closed',closed_at=?,closed_by=? WHERE id=?",
                 (db.now(), ctx["user_id"], slip_id))
        db.exec_("UPDATE todo_items SET status='closed',handled_at=?,handled_by=? WHERE id=?",
                 (db.now(), ctx["user_id"], r["todo_id"]))
    db.audit(ctx, "todo.receipt", "ok", slip_id,
             "L2 劝返台账回执：%s（%s）；不回流学生明细" % (mp[state_], r["category"]))
    return {"slip_id": slip_id, "status": state_, "status_text": mp[state_],
            "note": "一件事一条流、一条上报线；L1 与 L2 可关联但不继承字段、不继承上下文"}, None


# ---------------------------------------------------------------- 秘书对话入口
def summary_for_chat(ctx):
    v = list_items(ctx)
    n = v["open_count"]
    sp = slips(ctx)
    pend = sum(1 for x in sp if x["status"] == "pending")
    if not v["items"]:
        text = ("【本周待确认红点】本周无待确认。数据来源＝预警转介单、家长告知事项（人工登记）、"
                "上周未销号项；空态不摆示例数据。")
    else:
        text = ("【本周待确认红点】本周待确认 %d 项（含上周未销号）：" % n)
        for x in v["items"][:8]:
            text += "\n  · %s ｜ %s ｜ %s%s ｜ %s" % (
                x["item_id"], v["kinds"].get(x["kind"], x["kind"]), x["category"],
                ("（" + x["student_id"] + "）") if x["student_id"] else "", x["status"])
    text += ("\n三类动作：转介（→L2 劝返台账，回执三态）、告知（人工签发，秘书不代发）、"
             "销号（人审后留三元组审计）。当前待 L2 接收转介单 %d 张。" % pend)
    text += "\n不含姓名、成绩、家长电话；预警只写事实不作定性（四色 12 条规则与影子模式待政教处＋招就处审定，未启动）。"
    return {"text": text, "card": {"type": "todo_digest", "title": "本周待确认红点（集中待办）",
                                   "items": v["items"], "open_count": n, "week": v["week"],
                                   "referrals_pending": pend,
                                   "hint": "入口独立于「待确认写入」草稿；销号后不再出现"}}
