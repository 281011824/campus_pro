# -*- coding: utf-8 -*-
"""管理员账号表（独立于教师 school_accounts，职责分离，避免污染教师账号）。

只存 SHA-256 摘要，不存明文。role 预留 superadmin / admin 两级。
"""

import hashlib
import hmac

from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_accounts (
  userid TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  password_sha256 TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'admin',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT,
  last_login_at TEXT
);
"""

DEFAULT_ADMIN_USERID = "admin"
DEFAULT_ADMIN_PASSWORD = "abcd1230"
DEFAULT_ADMIN_NAME = "系统管理员"
ROLES = ("superadmin", "admin")
ACTIVE = "active"
DISABLED = "disabled"


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    _seed_default()


def _seed_default():
    """幂等播种初始超级管理员；已存在则绝不覆盖（保留用户改过的密码）。"""
    if get(DEFAULT_ADMIN_USERID):
        return
    db.exec_(
        "INSERT OR IGNORE INTO admin_accounts(userid,name,password_sha256,role,status,created_at,last_login_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (DEFAULT_ADMIN_USERID, DEFAULT_ADMIN_NAME, sha256_hex(DEFAULT_ADMIN_PASSWORD),
         "superadmin", ACTIVE, db.now(), ""))


def sha256_hex(password):
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def verify_password(userid, password):
    rec = get(userid)
    if not rec:
        return False
    return hmac.compare_digest(sha256_hex(password), str(rec.get("password_sha256") or ""))


def get(userid):
    try:
        row = db.q("SELECT * FROM admin_accounts WHERE userid=?", (str(userid),), one=True)
    except Exception:
        # 表尚未初始化（如测试隔离库）时安全降级为“无此管理员”
        return None
    return dict(row) if row else None


def is_active_admin(userid):
    rec = get(userid)
    return bool(rec) and rec.get("status") == ACTIVE and rec.get("role") in ROLES


def is_superadmin(userid):
    rec = get(userid)
    return bool(rec) and rec.get("status") == ACTIVE and rec.get("role") == "superadmin"


def count():
    try:
        row = db.q("SELECT COUNT(*) AS n FROM admin_accounts", one=True)
    except Exception:
        return 0
    return int(row["n"]) if row else 0


def count_active_superadmin():
    try:
        row = db.q("SELECT COUNT(*) AS n FROM admin_accounts WHERE role='superadmin' AND status=?",
                   (ACTIVE,), one=True)
    except Exception:
        return 0
    return int(row["n"]) if row else 0


def list(keyword="", page=1, size=50):
    where, args = [], []
    keyword = str(keyword or "").strip()
    if keyword:
        where.append("(userid LIKE ? OR name LIKE ?)")
        args += ["%%%s%%" % keyword, "%%%s%%" % keyword]
    sql = "SELECT * FROM admin_accounts"
    if where:
        sql += " WHERE " + " AND ".join(where)
    total = db.q("SELECT COUNT(*) AS n FROM (%s) AS t" % sql, tuple(args), one=True)["n"] if where else count()
    page = max(1, int(page or 1))
    size = max(1, min(200, int(size or 50)))
    sql += " ORDER BY role DESC, userid LIMIT ? OFFSET ?"
    args += [size, (page - 1) * size]
    items = [dict(r) for r in db.q(sql, tuple(args))]
    for it in items:
        it.pop("password_sha256", None)  # 绝不返回密码摘要到前端
    return {"items": items, "total": total, "page": page, "size": size}


def create(userid, name, password, role="admin", status=ACTIVE):
    userid = str(userid or "").strip()
    if not userid:
        raise ValueError("账号不能为空")
    if role not in ROLES:
        raise ValueError("角色不合法")
    if get(userid):
        raise ValueError("账号已存在")
    password = str(password or "")
    if not password:
        raise ValueError("密码不能为空")
    db.exec_(
        "INSERT INTO admin_accounts(userid,name,password_sha256,role,status,created_at,last_login_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (userid, str(name or ""), sha256_hex(password), role, status, db.now(), ""))
    return get(userid)


def update(userid, name=None, role=None):
    rec = get(userid)
    if not rec:
        raise ValueError("账号不存在")
    fields, args = [], []
    if name is not None:
        fields.append("name=?")
        args.append(str(name))
    if role is not None:
        if role not in ROLES:
            raise ValueError("角色不合法")
        if role != "superadmin" and rec.get("role") == "superadmin" and count_active_superadmin() <= 1:
            raise ValueError("至少保留一个超级管理员")
        fields.append("role=?")
        args.append(role)
    if fields:
        args.append(userid)
        db.exec_("UPDATE admin_accounts SET %s WHERE userid=?" % ",".join(fields), tuple(args))
    return get(userid)


def set_password(userid, password):
    rec = get(userid)
    if not rec:
        raise ValueError("账号不存在")
    password = str(password or "")
    if not password:
        raise ValueError("密码不能为空")
    db.exec_("UPDATE admin_accounts SET password_sha256=? WHERE userid=?",
             (sha256_hex(password), userid))
    return True


def set_status(userid, status, operator_userid=None):
    rec = get(userid)
    if not rec:
        raise ValueError("账号不存在")
    if status not in (ACTIVE, DISABLED):
        raise ValueError("状态不合法")
    if status == DISABLED:
        if str(userid) == str(operator_userid or ""):
            raise ValueError("不能停用自己的账号")
        if rec.get("role") == "superadmin" and count_active_superadmin() <= 1:
            raise ValueError("至少保留一个启用的超级管理员")
    db.exec_("UPDATE admin_accounts SET status=? WHERE userid=?", (status, userid))
    return get(userid)


def delete(userid, operator_userid=None):
    rec = get(userid)
    if not rec:
        raise ValueError("账号不存在")
    if str(userid) == str(operator_userid or ""):
        raise ValueError("不能删除自己的账号")
    if rec.get("role") == "superadmin" and count_active_superadmin() <= 1:
        raise ValueError("至少保留一个超级管理员")
    db.exec_("DELETE FROM admin_accounts WHERE userid=?", (userid,))
    return True


def touch_login(userid):
    db.exec_("UPDATE admin_accounts SET last_login_at=? WHERE userid=?", (db.now(), str(userid)))
