# -*- coding: utf-8 -*-
"""班主任小秘书 · 重点学生标记与科任反馈。

两类数据都按班级隔离：
  - focus_marks：班主任给本班学生打标签（如「英语不足待提高」），供科任教师关注；
  - teacher_comments：科任教师提交课堂表现 / 作业情况点评，班主任在小秘书内接收。

只存必要字段，不写成长报告，不涉及成绩与排名。
"""

from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS focus_marks (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  student_name TEXT NOT NULL DEFAULT '',
  tag TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  removed_at TEXT,
  removed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_focus_class ON focus_marks(class_id, status, ts);
CREATE UNIQUE INDEX IF NOT EXISTS ux_focus_active
  ON focus_marks(class_id, student_id, tag) WHERE status='active';

CREATE TABLE IF NOT EXISTS teacher_comments (
  id TEXT PRIMARY KEY,
  ts TEXT NOT NULL,
  class_id TEXT NOT NULL,
  student_id TEXT,
  student_name TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT '课堂表现',
  content TEXT NOT NULL,
  teacher_userid TEXT NOT NULL DEFAULT '',
  teacher_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'new',
  read_at TEXT,
  read_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_comment_class ON teacher_comments(class_id, status, ts);
"""

# 小秘书内置标签；前端下拉使用，亦允许自定义
FOCUS_TAGS = [
    "英语不足待提高",
    "上课易开小差",
    "作业拖延",
    "情绪波动",
    "需家校沟通",
    "其他",
]
COMMENT_KINDS = ["课堂表现", "作业情况"]


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()


def _student_name(class_id, student_id):
    try:
        row = db.q("SELECT name FROM students WHERE class_id=? AND student_id=?",
                   (str(class_id), str(student_id)), one=True)
        return (row or {}).get("name") or ""
    except Exception:
        return ""


def _teacher_name(userid):
    try:
        from tasks.domain.identity import accounts
        rec = accounts.get(userid) or {}
        return rec.get("name") or ""
    except Exception:
        return ""


# ---------------------------------------------------------------- 重点学生标记
def list_focus(class_id):
    rows = db.q(
        "SELECT * FROM focus_marks WHERE class_id=? AND status='active' "
        "ORDER BY ts DESC, id DESC", (str(class_id),))
    return [dict(r) for r in rows]


def add_focus(class_id, student_id, tag, note="", actor=""):
    class_id, student_id = str(class_id or "").strip(), str(student_id or "").strip()
    tag = str(tag or "").strip()
    if not class_id or not student_id:
        raise ValueError("缺少班级或学生")
    if not tag:
        raise ValueError("请选择标签")
    existing = db.q(
        "SELECT * FROM focus_marks WHERE class_id=? AND student_id=? AND tag=? AND status='active'",
        (class_id, student_id, tag), one=True)
    if existing:
        if note and note != existing["note"]:
            db.exec_("UPDATE focus_marks SET note=?, ts=? WHERE id=?",
                     (str(note), db.now(), existing["id"]))
            existing["note"] = str(note)
        return dict(existing), False
    mark_id = db.uid("fm_")
    db.exec_(
        "INSERT INTO focus_marks(id,ts,class_id,student_id,student_name,tag,note,created_by,status) "
        "VALUES(?,?,?,?,?,?,?,?,'active')",
        (mark_id, db.now(), class_id, student_id, _student_name(class_id, student_id),
         tag, str(note or ""), str(actor or "")))
    row = db.q("SELECT * FROM focus_marks WHERE id=?", (mark_id,), one=True)
    return dict(row), True


def remove_focus(class_id, mark_id, actor=""):
    row = db.q("SELECT * FROM focus_marks WHERE id=? AND class_id=?",
               (str(mark_id), str(class_id)), one=True)
    if not row:
        raise ValueError("标记不存在或不属于本班")
    db.exec_("UPDATE focus_marks SET status='removed', removed_at=?, removed_by=? WHERE id=?",
             (db.now(), str(actor or ""), str(mark_id)))
    return True


def focus_summary(class_id):
    row = db.q("SELECT COUNT(*) AS n FROM focus_marks WHERE class_id=? AND status='active'",
               (str(class_id),), one=True)
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------- 科任反馈
def add_comment(class_id, student_id, kind, content, actor=""):
    class_id = str(class_id or "").strip()
    kind = str(kind or "课堂表现").strip()
    content = str(content or "").strip()
    if not class_id:
        raise ValueError("缺少班级")
    if not content:
        raise ValueError("点评内容不能为空")
    student_id = str(student_id or "").strip()
    cid = db.uid("tc_")
    db.exec_(
        "INSERT INTO teacher_comments(id,ts,class_id,student_id,student_name,kind,content,"
        "teacher_userid,teacher_name,status) VALUES(?,?,?,?,?,?,?,?,?,'new')",
        (cid, db.now(), class_id, student_id,
         _student_name(class_id, student_id) if student_id else "",
         kind, content[:1000], str(actor or ""), _teacher_name(actor)))
    row = db.q("SELECT * FROM teacher_comments WHERE id=?", (cid,), one=True)
    return dict(row)


def list_comments(class_id, unread_only=False):
    sql = "SELECT * FROM teacher_comments WHERE class_id=?"
    if unread_only:
        sql += " AND status='new'"
    sql += " ORDER BY ts DESC, id DESC"
    return [dict(r) for r in db.q(sql, (str(class_id),))]


def mark_read(class_id, comment_id, actor=""):
    row = db.q("SELECT * FROM teacher_comments WHERE id=? AND class_id=?",
               (str(comment_id), str(class_id)), one=True)
    if not row:
        raise ValueError("反馈不存在或不属于本班")
    db.exec_("UPDATE teacher_comments SET status='read', read_at=?, read_by=? WHERE id=?",
             (db.now(), str(actor or ""), str(comment_id)))
    return True


def comment_summary(class_id):
    row = db.q(
        "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status='new' THEN 1 ELSE 0 END),0) AS unread "
        "FROM teacher_comments WHERE class_id=?", (str(class_id),), one=True)
    if not row:
        return {"total": 0, "unread": 0}
    return {"total": int(row["total"]), "unread": int(row["unread"])}


def summary(class_id):
    return {"focus": focus_summary(class_id), "feedback": comment_summary(class_id)}
