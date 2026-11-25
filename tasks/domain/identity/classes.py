# -*- coding: utf-8 -*-
"""班级字典表：全校班级统一管理，学生的 class_id 引用此处。"""

import hashlib

from tasks.domain.identity import accounts
from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS classes (
  class_id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  grade TEXT NOT NULL DEFAULT '',
  major TEXT NOT NULL DEFAULT '',
  head_teacher_userid TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_classes_status ON classes(status);
"""


def _migrate_classes():
    """兼容已有库：补加 专业 列（幂等）。"""
    c = db.connect()
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(classes)").fetchall()}
        if "major" not in cols:
            c.execute("ALTER TABLE classes ADD COLUMN major TEXT NOT NULL DEFAULT ''")
        c.commit()
    finally:
        c.close()


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    _migrate_classes()
    backfill()
    backfill_head_from_bindings()
    try:
        accounts.backfill_head_teacher_pool()
    except Exception:
        pass


def backfill_head_from_bindings():
    """历史数据里班主任只在 account_bindings 中，回填到班级字典便于展示与编辑。"""
    try:
        rows = db.q("SELECT userid,class_ids FROM account_bindings "
                    "WHERE portal='headteacher' ORDER BY primary_flag DESC,updated_at DESC")
    except Exception:
        return
    for r in rows:
        for cid in db.loads(r["class_ids"], []):
            db.exec_("UPDATE classes SET head_teacher_userid=?,updated_at=? "
                     "WHERE class_id=? AND head_teacher_userid=''",
                     (str(r["userid"]), db.now(), str(cid)))


def backfill():
    """把已存在于 students / org_posts.class_ids 中的班级补登记，不覆盖用户已维护内容。"""
    seen = set()
    try:
        for r in db.q("SELECT DISTINCT class_id FROM students WHERE class_id IS NOT NULL AND class_id!=''"):
            seen.add(str(r["class_id"]))
    except Exception:
        pass
    try:
        for r in db.q("SELECT class_ids FROM org_posts WHERE class_ids IS NOT NULL AND class_ids!='[]'"):
            for cid in db.loads(r["class_ids"], []):
                if cid:
                    seen.add(str(cid))
    except Exception:
        pass
    for cid in sorted(seen):
        if not get(cid):
            db.exec_(
                "INSERT OR IGNORE INTO classes(class_id,name,grade,head_teacher_userid,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (cid, "%s班" % cid, "", "", "active", db.now(), db.now()))


def get(class_id):
    row = db.q("SELECT * FROM classes WHERE class_id=?", (str(class_id),), one=True)
    if not row:
        return None
    item = dict(row)
    _with_head_name(item)
    return item


def _with_head_name(item):
    uid = str(item.get("head_teacher_userid") or "")
    item["head_teacher_name"] = (accounts.get(uid) or {}).get("name", "") if uid else ""
    return item


def list(keyword="", status=""):
    where, args = [], []
    keyword = str(keyword or "").strip()
    if keyword:
        where.append("(class_id LIKE ? OR name LIKE ? OR grade LIKE ?)")
        args += ["%%%s%%" % keyword] * 3
    status = str(status or "").strip()
    if status:
        where.append("status=?")
        args.append(status)
    sql = "SELECT * FROM classes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY class_id"
    items = [dict(r) for r in db.q(sql, tuple(args))]
    for it in items:
        it["student_count"] = db.q(
            "SELECT COUNT(*) AS n FROM students WHERE class_id=?", (it["class_id"],), one=True)["n"]
        _with_head_name(it)
    return items


def create(class_id, name="", grade="", head_teacher_userid="", status="active", major=""):
    class_id = str(class_id or "").strip()
    if not class_id:
        raise ValueError("班级编号不能为空")
    if get(class_id):
        raise ValueError("班级已存在")
    db.exec_(
        "INSERT INTO classes(class_id,name,grade,major,head_teacher_userid,status,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (class_id, str(name or "%s班" % class_id), str(grade or ""), str(major or ""),
         str(head_teacher_userid or ""), str(status or "active"), db.now(), db.now()))
    return get(class_id)


def update(class_id, name=None, grade=None, head_teacher_userid=None, status=None, major=None):
    if not get(class_id):
        raise ValueError("班级不存在")
    fields, args = [], []
    if name is not None:
        fields.append("name=?"); args.append(str(name))
    if grade is not None:
        fields.append("grade=?"); args.append(str(grade))
    if major is not None:
        fields.append("major=?"); args.append(str(major))
    if head_teacher_userid is not None:
        fields.append("head_teacher_userid=?"); args.append(str(head_teacher_userid))
    if status is not None:
        fields.append("status=?"); args.append(str(status))
    if fields:
        fields.append("updated_at=?"); args.append(db.now()); args.append(class_id)
        db.exec_("UPDATE classes SET %s WHERE class_id=?" % ",".join(fields), tuple(args))
    return get(class_id)


def set_majors(class_ids, major=""):
    """批量把多个班级的专业设为同一值，忽略不存在的班级。

    major 允许为空字符串（表示清空专业）；返回实际更新的班级编号。
    """
    major = str(major or "")
    updated = []
    for cid in (class_ids or []):
        cid = str(cid or "").strip()
        if not cid or cid in updated:
            continue
        if not db.q("SELECT 1 FROM classes WHERE class_id=?", (cid,), one=True):
            continue
        db.exec_("UPDATE classes SET major=?,updated_at=? WHERE class_id=?",
                 (major, db.now(), cid))
        updated.append(cid)
    return {"updated": len(updated), "class_ids": updated}


def delete(class_id):
    if not get(class_id):
        raise ValueError("班级不存在")
    n = db.q("SELECT COUNT(*) AS n FROM students WHERE class_id=?", (str(class_id),), one=True)["n"]
    if n:
        raise ValueError("该班级下仍有 %d 名学生，请先转出或删除后再删除班级" % n)
    _drop_class_from_bindings(str(class_id))
    db.exec_("DELETE FROM classes WHERE class_id=?", (str(class_id),))
    return True


def set_head_teacher(class_id, userid):
    """设置班级班主任，并同步 account_bindings 的班主任班级范围。

    这是班级绑定生效的关键：班主任端的数据范围由 account_bindings 决定，
    仅写 classes.head_teacher_userid 不会授予访问权限。
    """
    class_id = str(class_id or "").strip()
    userid = str(userid or "").strip()
    if not get(class_id):
        raise ValueError("班级不存在")
    if userid and not accounts.get(userid):
        raise ValueError("班主任账号不存在：%s" % userid)
    db.exec_("UPDATE classes SET head_teacher_userid=?,updated_at=? WHERE class_id=?",
             (userid, db.now(), class_id))
    _drop_class_from_bindings(class_id, keep_userid=userid)
    if userid:
        _ensure_head_binding(userid, class_id)
    return get(class_id)


def _drop_class_from_bindings(class_id, keep_userid=""):
    """把班级从其他班主任的 account_bindings 中移除。"""
    for r in db.q("SELECT post_id,userid,class_ids FROM account_bindings WHERE portal='headteacher'"):
        if keep_userid and str(r["userid"]) == keep_userid:
            continue
        ids = [str(x) for x in db.loads(r["class_ids"], [])]
        if class_id not in ids:
            continue
        ids = [x for x in ids if x != class_id]
        db.exec_("UPDATE account_bindings SET class_ids=?,data_scope=?,updated_at=? WHERE post_id=?",
                 (db.dumps(ids), "class:" + ",".join(ids), db.now(), r["post_id"]))


def _promote_headteacher(userid, head_post_id):
    """班主任职务优先于任课教师：无行政主职务时，把班主任设为主职务、任课教师降级。

    修复历史映射：班主任绑定由班级管理补齐时 primary_flag 曾为 0，
    导致登录后主职务落到「任课教师」、班级范围回落到默认班。
    """
    admin_primary = db.q(
        "SELECT 1 FROM account_bindings WHERE userid=? AND portal='admin' "
        "AND primary_flag=1 LIMIT 1", (userid,), one=True)
    db.exec_("UPDATE account_bindings SET primary_flag=0,updated_at=? "
             "WHERE userid=? AND portal='teacher'", (db.now(), userid))
    if not admin_primary:
        db.exec_("UPDATE account_bindings SET primary_flag=1,updated_at=? "
                 "WHERE post_id=?", (db.now(), head_post_id))


def _ensure_head_binding(userid, class_id):
    """确保该账号持有包含本班的 headteacher 映射；已有则追加班级。"""
    row = db.q("SELECT * FROM account_bindings WHERE userid=? AND portal='headteacher' "
               "ORDER BY primary_flag DESC LIMIT 1", (userid,), one=True)
    if row:
        ids = [str(x) for x in db.loads(row["class_ids"], [])]
        if class_id not in ids:
            ids.append(class_id)
        db.exec_("UPDATE account_bindings SET class_ids=?,data_scope=?,review_status='已确认',"
                 "updated_at=? WHERE post_id=?",
                 (db.dumps(ids), "class:" + ",".join(ids), db.now(), row["post_id"]))
        _promote_headteacher(userid, row["post_id"])
        return
    acc = accounts.get(userid) or {}
    admin_primary = db.q(
        "SELECT 1 FROM account_bindings WHERE userid=? AND portal='admin' "
        "AND primary_flag=1 LIMIT 1", (userid,), one=True)
    post_id = "p_" + hashlib.sha1(("%s|班主任|0" % userid).encode("utf-8")).hexdigest()[:12]
    ids = [class_id]
    db.exec_(
        "INSERT OR REPLACE INTO account_bindings(post_id,userid,name,category,dept_path,"
        "post_name,portal,level,data_scope,class_ids,agent_id,agent_name,primary_flag,"
        "committee_line,in_chain,level_source,review_status,source,generated_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (post_id, userid, acc.get("name") or userid, acc.get("category") or "",
         acc.get("dept") or "", "班主任", "headteacher", "L1",
         "class:" + ",".join(ids), db.dumps(ids), "bzr_secretary_v1", "班主任秘书",
         0 if admin_primary else 1, 0, 1, "班级管理指定", "已确认", "班级管理指定",
         db.now(), db.now()))
    _promote_headteacher(userid, post_id)


def unbind_head_teacher(userid):
    """把某教职工从班主任名单移出时，解除其全部班级绑定。"""
    userid = str(userid or "").strip()
    if not userid:
        return 0
    n = db.q("SELECT COUNT(*) AS n FROM classes WHERE head_teacher_userid=?",
             (userid,), one=True)["n"]
    db.exec_("UPDATE classes SET head_teacher_userid='',updated_at=? WHERE head_teacher_userid=?",
             (db.now(), userid))
    for r in db.q("SELECT post_id FROM account_bindings WHERE portal='headteacher' AND userid=?",
                  (userid,)):
        db.exec_("UPDATE account_bindings SET class_ids='[]',data_scope='class:',"
                 "review_status='已确认',updated_at=? WHERE post_id=?", (db.now(), r["post_id"]))
    return n


def count():
    row = db.q("SELECT COUNT(*) AS n FROM classes", one=True)
    return int(row["n"]) if row else 0
