# -*- coding: utf-8 -*-
"""德育工作台部署样本 · 两段式写入与人审归档

所有写入先生成「回显卡」草稿（pending_writes，不落业务库），用户明确确认后才落库；
含糊回复需二次确认。周报归档是独立人审点（未经确认的版本不进入成长导航档案）。
"""
from tasks.domain import models
from tasks.shared import db


def classify(text):
    if any(k in text for k in ("家访", "沟通", "联系家长", "记录一次", "谈心")):
        return "communication"
    if any(k in text for k in ("补记", "出勤", "考勤")):
        return "attendance_patch"
    if any(k in text for k in ("待办", "任务", "提醒我")):
        return "task"
    return "moral_record"


def draft(ctx, text):
    kind = classify(text)
    pid = db.uid("pw_")
    payload = {
        "text": text,
        "kind_name": models.WRITE_KINDS.get(kind, kind),
        "class_ids": ctx.get("class_ids", []),
        "data_class": "教师业务数据（学生姓名已掩码）",
        "rule": "仅在前端回显并获明确确认后落库；含糊回复二次确认",
    }
    db.exec_("INSERT INTO pending_writes(id,ts,session_id,user_id,post_id,agent_id,kind,"
             "payload_json,status) VALUES(?,?,?,?,?,?,?,?,'pending')",
             (pid, db.now(), ctx["session_id"], ctx["user_id"], ctx["post_id"],
              ctx["agent_id"], kind, db.dumps(payload)))
    db.audit(ctx, "write.draft", "ok", pid, "生成回显卡，未落业务库")
    return pid


def pending_for(session_id):
    return db.q("SELECT * FROM pending_writes WHERE session_id=? AND status='pending' "
                "ORDER BY ts DESC LIMIT 1", (session_id,), one=True)


def confirm(ctx, pending, decision):
    from tasks.modules.head_teacher import secretary
    pid = pending["id"]
    if decision != "confirm":
        db.exec_("UPDATE pending_writes SET status='cancelled',resolved_at=? WHERE id=?",
                 (db.now(), pid))
        db.audit(ctx, "write.cancel", "ok", pid)
        return secretary.out(models.REPLY["cancel"] + "（草稿已作废，未产生任何写入）",
                             audit=("write.cancel", "ok", pid))
    db.exec_("INSERT INTO write_records(ts,user_id,post_id,agent_id,kind,payload_json) "
             "VALUES(?,?,?,?,?,?)",
             (db.now(), ctx["user_id"], ctx["post_id"], ctx["agent_id"],
              pending["kind"], pending["payload_json"]))
    db.exec_("UPDATE pending_writes SET status='confirmed',resolved_at=? WHERE id=?",
             (db.now(), pid))
    db.audit(ctx, "write.confirm", "ok", pid,
             "人审点：写入回显确认后落库（三元组留痕）")
    payload = db.loads(pending["payload_json"], {})
    return secretary.out(
        "已确认落库：%s。记录按 userid＋post_id＋agent_id 留痕，可在统一台账复核。" %
        payload.get("kind_name", pending["kind"]),
        card={"type": "write_echo", "title": "写入已确认落库", "pending_id": pid,
              "kind": payload.get("kind_name"), "payload": payload},
        kind="card", audit=("write.confirm", "ok", pid))


def archive(ctx, report_id):
    from tasks.modules.head_teacher import secretary
    r = db.q("SELECT * FROM weekly_reports WHERE id=?", (report_id,), one=True)
    if not r:
        return secretary.out("未找到该周报草稿。", audit=("report.archive", "denied", report_id))
    if r["status"] == "archived":
        return secretary.out("该周报已归档，无需重复操作。", audit=("report.archive", "ok", report_id))
    db.exec_("UPDATE weekly_reports SET status='archived',archived_at=?,archived_by=? WHERE id=?",
             (db.now(), ctx["user_id"], report_id))
    db.audit(ctx, "report.archive", "ok", report_id, "人审点：班主任确认归档至成长导航档案")
    return secretary.out("周报已确认归档（人审点完成），未经确认的版本不进入成长导航档案。",
                         card={"type": "weekly_report", "report_id": report_id,
                               "status": "archived", "title": "周报归档回执"},
                         kind="card", audit=("report.archive", "ok", report_id))
