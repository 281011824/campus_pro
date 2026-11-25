# -*- coding: utf-8 -*-
"""学生登录账号（供管理员创建 / 重置 / 停用；本次不交付学生登录页面，预留扩展）。

只存 SHA-256 摘要。PK 为 (class_id, student_id)，与 students 主数据一致。
"""

import hashlib

from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS student_accounts (
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  password_sha256 TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  updated_at TEXT,
  PRIMARY KEY (class_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_student_accounts_class ON student_accounts(class_id);
"""

DEFAULT_PASSWORD = "123456"
ACTIVE = "active"
DISABLED = "disabled"


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()


def sha256_hex(password):
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def get(class_id, student_id):
    row = db.q("SELECT * FROM student_accounts WHERE class_id=? AND student_id=?",
               (str(class_id), str(student_id)), one=True)
    return dict(row) if row else None


def list(class_id="", keyword="", status="", page=1, size=50):
    where, args = [], []
    class_id = str(class_id or "").strip()
    if class_id:
        where.append("sa.class_id=?"); args.append(class_id)
    status = str(status or "").strip()
    if status:
        where.append("sa.status=?"); args.append(status)
    keyword = str(keyword or "").strip()
    join = "LEFT JOIN students s ON s.class_id=sa.class_id AND s.student_id=sa.student_id"
    if keyword:
        where.append("(sa.student_id LIKE ? OR sa.class_id LIKE ? OR COALESCE(s.name,'') LIKE ? "
                     "OR COALESCE(s.student_no,'') LIKE ?)")
        args += ["%%%s%%" % keyword] * 4
    sql = ("SELECT sa.*, COALESCE(s.name,'') AS name, COALESCE(s.student_no,'') AS student_no "
           "FROM student_accounts sa " + join)
    if where:
        sql += " WHERE " + " AND ".join(where)
    total = db.q("SELECT COUNT(*) AS n FROM student_accounts sa " + join +
                 (" WHERE " + " AND ".join(where) if where else ""), tuple(args), one=True)["n"]
    page = max(1, int(page or 1))
    size = max(1, min(200, int(size or 50)))
    sql += " ORDER BY sa.class_id, sa.student_id LIMIT ? OFFSET ?"
    args += [size, (page - 1) * size]
    items = [dict(r) for r in db.q(sql, tuple(args))]
    for it in items:
        it.pop("password_sha256", None)
    return {"items": items, "total": total, "page": page, "size": size}


def generate(class_id="", password=DEFAULT_PASSWORD):
    """为在册但尚无账号的学生批量生成账号；返回生成数量。跳过已有。"""
    where = "WHERE 1=1"
    args = []
    class_id = str(class_id or "").strip()
    if class_id:
        where += " AND class_id=?"
        args.append(class_id)
    rows = db.q(
        "SELECT class_id, student_id FROM students %s AND (class_id,student_id) NOT IN "
        "(SELECT class_id,student_id FROM student_accounts)" % where, tuple(args))
    now = db.now()
    digest = sha256_hex(password)
    stmts = [
        ("INSERT OR IGNORE INTO student_accounts(class_id,student_id,password_sha256,status,updated_at) "
         "VALUES(?,?,?,?,?)",
         (str(r["class_id"]), str(r["student_id"]), digest, ACTIVE, now))
        for r in rows]
    if stmts:
        db.exec_many(stmts)
    return {"generated": len(rows), "skipped": 0, "password": password}


def set_password(class_id, student_id, password=DEFAULT_PASSWORD):
    if not get(class_id, student_id):
        raise ValueError("学生账号不存在")
    password = str(password or "")
    if not password:
        raise ValueError("密码不能为空")
    db.exec_("UPDATE student_accounts SET password_sha256=?, updated_at=? WHERE class_id=? AND student_id=?",
             (sha256_hex(password), db.now(), str(class_id), str(student_id)))
    return True


def set_status(class_id, student_id, status):
    if status not in (ACTIVE, DISABLED):
        raise ValueError("状态不合法")
    if not get(class_id, student_id):
        raise ValueError("学生账号不存在")
    db.exec_("UPDATE student_accounts SET status=?, updated_at=? WHERE class_id=? AND student_id=?",
             (status, db.now(), str(class_id), str(student_id)))
    return get(class_id, student_id)


def count(class_id=""):
    if class_id:
        row = db.q("SELECT COUNT(*) AS n FROM student_accounts WHERE class_id=?", (str(class_id),), one=True)
    else:
        row = db.q("SELECT COUNT(*) AS n FROM student_accounts", one=True)
    return int(row["n"]) if row else 0
