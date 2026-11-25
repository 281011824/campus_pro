# -*- coding: utf-8 -*-
"""全校教师账号（来源：教师Casdoor账号密码_2026-11-17.xlsx）。

只保存密码的 SHA-256 摘要，不保存明文；登录时摘要比对。
字段：统一ID / 姓名 / 登录账号 / 企业微信userid / 部门 / 职务 / 类别 / 状态。
"""

import hashlib

from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS school_accounts (
  userid TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  password_sha256 TEXT NOT NULL,
  wecom_userid TEXT,
  dept TEXT,
  post_name TEXT,
  category TEXT,
  status TEXT,
  source TEXT,
  imported_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_school_accounts_name ON school_accounts(name);
CREATE INDEX IF NOT EXISTS idx_school_accounts_dept ON school_accounts(dept);
CREATE TABLE IF NOT EXISTS head_teacher_pool (
  userid TEXT PRIMARY KEY,
  created_at TEXT
);
"""

SOURCE = "教师Casdoor账号密码_2026-11-17.xlsx"


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    backfill_head_teacher_pool()


def backfill_head_teacher_pool():
    """把已绑定班级的班主任补入班主任名单，保证下拉框初始有候选人。"""
    for sql in (
        "INSERT OR IGNORE INTO head_teacher_pool(userid,created_at) "
        "SELECT head_teacher_userid,? FROM classes WHERE head_teacher_userid<>''",
        "INSERT OR IGNORE INTO head_teacher_pool(userid,created_at) "
        "SELECT userid,? FROM account_bindings WHERE portal='headteacher'",
    ):
        try:
            db.exec_(sql, (db.now(),))
        except Exception:
            pass


def pool_ids():
    try:
        return {str(r["userid"]) for r in db.q("SELECT userid FROM head_teacher_pool")}
    except Exception:
        return set()


def pool_set(userid, enabled):
    userid = str(userid or "").strip()
    if not userid:
        raise ValueError("请选择教职工")
    if not get(userid):
        raise ValueError("教职工账号不存在")
    if enabled:
        db.exec_("INSERT OR IGNORE INTO head_teacher_pool(userid,created_at) VALUES(?,?)",
                 (userid, db.now()))
    else:
        db.exec_("DELETE FROM head_teacher_pool WHERE userid=?", (userid,))
    return get(userid)


def headteachers_for_select():
    """已指定的班主任名单（供班级绑定下拉框）。"""
    rows = db.q(
        "SELECT a.userid,a.name,a.dept,a.post_name FROM head_teacher_pool p "
        "JOIN school_accounts a ON a.userid=p.userid ORDER BY a.name,a.userid")
    return [dict(r) for r in rows]


def headteacher_overview(keyword="", page=1, size=100):
    """班主任管理页：已指定的班主任 + 其管理班级与班级人数。"""
    where, args = [], []
    keyword = str(keyword or "").strip()
    if keyword:
        where.append("(a.userid LIKE ? OR a.name LIKE ? OR a.dept LIKE ?)")
        args += ["%%%s%%" % keyword] * 3
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.q("SELECT COUNT(*) AS n FROM head_teacher_pool p "
                 "JOIN school_accounts a ON a.userid=p.userid" + where_sql,
                 tuple(args), one=True)["n"]
    page = max(1, int(page or 1))
    size = max(1, min(200, int(size or 100)))
    rows = db.q("SELECT p.userid,a.name,a.dept FROM head_teacher_pool p "
                "JOIN school_accounts a ON a.userid=p.userid" + where_sql +
                " ORDER BY a.name,a.userid LIMIT ? OFFSET ?",
                tuple(args + [size, (page - 1) * size]))
    items = []
    for r in rows:
        classes = db.q(
            "SELECT c.class_id,c.name,COUNT(s.student_id) AS n FROM classes c "
            "LEFT JOIN students s ON s.class_id=c.class_id "
            "WHERE c.head_teacher_userid=? GROUP BY c.class_id ORDER BY c.class_id",
            (r["userid"],))
        names = [str(c["name"] or c["class_id"]) for c in classes]
        items.append({
            "userid": r["userid"], "name": r["name"], "dept": r["dept"],
            "class_ids": [c["class_id"] for c in classes],
            "class_names": "、".join(names),
            "class_count": len(classes),
            "student_count": sum(int(c["n"] or 0) for c in classes) if classes else None,
        })
    return {"items": items, "total": total, "page": page, "size": size}


def sha256_hex(password):
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def import_records(records, source=SOURCE):
    """按登录账号 upsert；records 每项为 dict（password_sha256 必填）。"""
    stmts = []
    for r in records:
        stmts.append((
            "INSERT INTO school_accounts"
            "(userid,name,password_sha256,wecom_userid,dept,post_name,category,status,"
            "source,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(userid) DO UPDATE SET name=excluded.name,"
            "password_sha256=excluded.password_sha256,wecom_userid=excluded.wecom_userid,"
            "dept=excluded.dept,post_name=excluded.post_name,category=excluded.category,"
            "status=excluded.status,source=excluded.source,imported_at=excluded.imported_at",
            (str(r["userid"]), str(r.get("name") or ""), str(r["password_sha256"]),
             str(r.get("wecom_userid") or ""), str(r.get("dept") or ""),
             str(r.get("post_name") or ""), str(r.get("category") or ""),
             str(r.get("status") or "本校"), str(source), db.now()),
        ))
    if stmts:
        db.exec_many(stmts)
    return len(stmts)


def get(userid):
    row = db.q("SELECT * FROM school_accounts WHERE userid=?", (str(userid),), one=True)
    return dict(row) if row else None


def count():
    row = db.q("SELECT COUNT(*) AS n FROM school_accounts", one=True)
    return int(row["n"]) if row else 0


def stats():
    rows = db.q("SELECT category, COUNT(*) AS n FROM school_accounts GROUP BY category "
                "ORDER BY n DESC")
    return {"total": count(), "by_category": {r["category"] or "未分类": r["n"] for r in rows}}


def list(keyword="", category="", page=1, size=50):
    where, args = [], []
    keyword = str(keyword or "").strip()
    if keyword:
        where.append("(a.userid LIKE ? OR a.name LIKE ? OR a.dept LIKE ?)")
        args += ["%%%s%%" % keyword] * 3
    category = str(category or "").strip()
    if category:
        where.append("a.category=?")
        args.append(category)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.q("SELECT COUNT(*) AS n FROM school_accounts a" + where_sql,
                 tuple(args), one=True)["n"]
    page = max(1, int(page or 1))
    size = max(1, min(200, int(size or 50)))
    sql = ("SELECT a.userid,a.name,a.wecom_userid,a.dept,a.post_name,a.category,a.status,"
           "a.source,a.imported_at,CASE WHEN p.userid IS NULL THEN 0 ELSE 1 END AS is_headteacher "
           "FROM school_accounts a LEFT JOIN head_teacher_pool p ON p.userid=a.userid"
           + where_sql + " ORDER BY a.userid LIMIT ? OFFSET ?")
    args += [size, (page - 1) * size]
    items = [dict(r) for r in db.q(sql, tuple(args))]
    for it in items:
        it["is_headteacher"] = bool(it.get("is_headteacher"))
    return {"items": items, "total": total, "page": page, "size": size}


def upsert(userid, name, password=None, wecom_userid="", dept="", post_name="",
           category="教师", status="本校", source="管理台"):
    userid = str(userid or "").strip()
    if not userid:
        raise ValueError("登录账号不能为空")
    name = str(name or "").strip()
    if not name:
        raise ValueError("姓名不能为空")
    existing = get(userid)
    if existing:
        fields, args = (
            ["name=?", "wecom_userid=?", "dept=?", "post_name=?", "category=?", "status=?"],
            [name, str(wecom_userid or ""), str(dept or ""), str(post_name or ""),
             str(category or "教师"), str(status or "本校")],
        )
        if password:
            fields.append("password_sha256=?")
            args.append(sha256_hex(password))
        args.append(userid)
        db.exec_("UPDATE school_accounts SET %s WHERE userid=?" % ",".join(fields), tuple(args))
    else:
        if not password:
            raise ValueError("新建账号必须设置密码")
        db.exec_(
            "INSERT INTO school_accounts(userid,name,password_sha256,wecom_userid,dept,post_name,"
            "category,status,source,imported_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (userid, name, sha256_hex(password), str(wecom_userid or ""), str(dept or ""),
             str(post_name or ""), str(category or "教师"), str(status or "本校"),
             str(source or "管理台"), db.now()))
    return get(userid)


def set_password(userid, password):
    if not get(userid):
        raise ValueError("账号不存在")
    password = str(password or "")
    if not password:
        raise ValueError("密码不能为空")
    db.exec_("UPDATE school_accounts SET password_sha256=? WHERE userid=?",
             (sha256_hex(password), str(userid)))


def set_status(userid, status):
    if not get(userid):
        raise ValueError("账号不存在")
    db.exec_("UPDATE school_accounts SET status=? WHERE userid=?", (str(status), str(userid)))
    return get(userid)


def delete(userid):
    if not get(userid):
        raise ValueError("账号不存在")
    db.exec_("DELETE FROM school_accounts WHERE userid=?", (str(userid),))
    return True
