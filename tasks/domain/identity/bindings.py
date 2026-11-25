# -*- coding: utf-8 -*-
"""全校账号 → 职务与班级映射（来源：教师 Casdoor 账号表）。

设计要点：
- 独立表 account_bindings，不写入 org_posts，避免被每次通讯录同步「离岗回收」覆盖。
- org.posts_of 会把本表与 org_posts 合并，账号即可正常装载工作台。
- 映射由规则生成，班级为默认分配，复核状态统一标「待确认」，供政教处校正。
"""

import hashlib

from tasks.domain.identity import accounts
from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS account_bindings (
  post_id TEXT PRIMARY KEY,
  userid TEXT NOT NULL,
  name TEXT NOT NULL,
  category TEXT,
  dept_path TEXT,
  post_name TEXT NOT NULL,
  portal TEXT NOT NULL,
  level TEXT NOT NULL,
  data_scope TEXT,
  class_ids TEXT,
  agent_id TEXT,
  agent_name TEXT,
  primary_flag INTEGER DEFAULT 0,
  committee_line INTEGER DEFAULT 0,
  in_chain INTEGER DEFAULT 1,
  level_source TEXT,
  review_status TEXT DEFAULT '待确认',
  source TEXT,
  generated_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_bind_user ON account_bindings(userid);
CREATE INDEX IF NOT EXISTS idx_bind_portal ON account_bindings(portal);
"""

CLASSES = ["26%02d" % i for i in range(1, 18)]
ADMIN_LEVELS = [
    (("班主任",), "L1"),
    (("政教干事", "干事"), "L2"),
    (("教官寝管", "寝管"), "L2"),
    (("政教副主任", "团委副书记", "副主任"), "L3"),
    (("政教处主任", "政教主任", "团委书记", "主任"), "L4"),
    (("分管副校长", "德育副校长"), "L5"),
    (("校长", "书记"), "L6"),
]


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()


def _level_for(post_name):
    for keys, level in ADMIN_LEVELS:
        if any(k in (post_name or "") for k in keys):
            return level
    return "L3"


def _scope(level, class_ids, post_name):
    if level == "L1":
        return "class:" + ",".join(class_ids or ["2607"])
    if level == "L2":
        return "line:" + (post_name or "本岗条线")
    if level == "L3":
        return "class_dimension_no_name"
    if level == "L4":
        return "grade_dimension"
    if level == "L5":
        return "indicator_only"
    return "school_stat_only"


def _agent(post_name, level):
    if "班主任" in post_name:
        return "bzr_secretary_v1", "班主任秘书"
    if "校长" in post_name or level == "L6":
        return "xz_canmou_v1", "校长参谋"
    if "副校长" in post_name or level == "L5":
        return "xld_fgx_v1", "分管副校长参谋"
    if level == "L4":
        return "zj_zhuren_v1", "政教主任参谋"
    if level == "L3":
        return "zj_fzr_generic_v1", "政教副主任参谋"
    if level == "L2":
        return "zj_ganshi_generic_v1", "政教干事参谋"
    return "generic_agent_v1", "岗位智能体"


def _pid(userid, post_name, idx):
    return "p_" + hashlib.sha1(
        ("%s|%s|%d" % (userid, post_name, idx)).encode("utf-8")).hexdigest()[:12]


def _plan_row(userid, name, category, dept, post_name):
    """按职务判断端与层级。"""
    text = (dept or "") + "／" + (post_name or "")
    if "班主任" in text:
        portal, level = "headteacher", "L1"
    elif "任课教师" in text or category in ("教师", "待入编"):
        portal, level = "teacher", "L1"
    else:
        portal, level = "admin", _level_for(post_name or dept)
    if portal == "teacher":
        level = "L1"
    return portal, level


def generate():
    """从账号表重新生成映射；班级按规则默认分配并标记待确认。"""
    accounts.init()
    init()
    rows = db.q("SELECT * FROM school_accounts ORDER BY userid")
    existing = {}
    for r in db.q("SELECT userid, post_name, class_ids, review_status FROM account_bindings"):
        existing[(r["userid"], r["post_name"])] = r

    def _is_head(row):
        return ("班主任" in (row["dept"] or "") or "班主任" in (row["post_name"] or "")
                or "徐海潮" in row["name"])

    # 只有 17 个班：优先教师类班主任，取 17 人，一人一班；徐海潮固定 2607
    cand = [a for a in rows if _is_head(a)]
    cand.sort(key=lambda a: (0 if a["category"] == "教师" else 1, a["userid"]))
    heads = cand[:len(CLASSES)]
    if not any("徐海潮" in a["name"] for a in heads):
        xh = next((a for a in cand if "徐海潮" in a["name"]), None)
        if xh:
            heads = heads[:-1] + [xh] if len(heads) == len(CLASSES) else heads + [xh]
    head_ids = {a["userid"] for a in heads}
    rest = [c for c in CLASSES if c != "2607"]
    class_map, idx = {}, 0
    for a in sorted(heads, key=lambda a: a["userid"]):
        if "徐海潮" in a["name"]:
            class_map[a["userid"]] = "2607"
        else:
            class_map[a["userid"]] = rest[idx % len(rest)]
            idx += 1

    made = []
    for acc in rows:
        userid = acc["userid"]
        name = acc["name"]
        category = acc["category"] or ""
        dept = (acc["dept"] or "").replace("；", "／")
        post_name = (acc["post_name"] or "").strip()
        segs = [s.strip() for s in dept.split("／") if s.strip()]
        is_head = userid in class_map
        is_teacher = ("任课教师" in dept) or category in ("教师", "待入编")
        is_admin = category in ("校领导", "中层干部")
        is_staff = category in ("干事", "教官寝管")
        base_post = post_name or (segs[-1] if segs else category or "教职员工")

        plan = []
        if is_head:
            classes = [class_map[userid]]
            plan.append(("班主任", "headteacher", "L1", classes))
        if is_admin:
            plan.append((post_name or base_post, "admin", _level_for(post_name or base_post), []))
        elif is_staff:
            staff_post = post_name or ("教官寝管" if category == "教官寝管" else "政教干事")
            plan.append((staff_post, "admin", _level_for(staff_post), []))
        if is_teacher and not any(p[1] == "headteacher" for p in plan):
            plan.append(("任课教师", "teacher", "L1", []))

        for idx, (pname, portal, level, classes) in enumerate(plan):
            pid = _pid(userid, pname, idx)
            old = existing.get((userid, pname))
            agent_id, agent_name = _agent(pname, level)
            primary = 1 if idx == 0 else 0
            review = "待确认"
            if old and old["review_status"] == "已确认":
                review = "已确认"
                classes = db.loads(old["class_ids"], classes)
            made.append((
                pid, userid, name, category, dept, pname, portal, level,
                _scope(level, classes, pname), db.dumps(classes), agent_id, agent_name,
                primary, 1 if "团委" in dept else 0,
                0 if portal == "teacher" else 1,
                "规则生成：部门／职务", review, "教师账号表 2026-11-17 规则映射",
                db.now(), db.now()))

    # 保留已确认的人工修正：仅重建规则生成的记录
    db.exec_("DELETE FROM account_bindings WHERE review_status!='已确认'")
    db.exec_many([
        ("INSERT OR REPLACE INTO account_bindings(post_id,userid,name,category,dept_path,"
         "post_name,portal,level,data_scope,class_ids,agent_id,agent_name,primary_flag,"
         "committee_line,in_chain,level_source,review_status,source,generated_at,updated_at) "
         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", r) for r in made])
    return stats()


def stats():
    total = db.q("SELECT COUNT(*) AS n FROM account_bindings", one=True)["n"]
    users = db.q("SELECT COUNT(DISTINCT userid) AS n FROM account_bindings", one=True)["n"]
    portals = {r["portal"]: r["n"] for r in db.q(
        "SELECT portal,COUNT(*) AS n FROM account_bindings GROUP BY portal")}
    levels = {r["level"]: r["n"] for r in db.q(
        "SELECT level,COUNT(*) AS n FROM account_bindings GROUP BY level ORDER BY level")}
    heads = db.q("SELECT COUNT(*) AS n FROM account_bindings WHERE portal='headteacher'",
                 one=True)["n"]
    classes = set()
    for r in db.q("SELECT class_ids FROM account_bindings WHERE portal='headteacher'"):
        classes.update(db.loads(r["class_ids"], []))
    return {"accounts": accounts.count(), "bound_users": users, "bindings": total,
            "headteachers": heads, "by_portal": portals, "by_level": levels,
            "classes": sorted(classes)}


def list_rows(portal="", keyword="", limit=500):
    sql = "SELECT * FROM account_bindings WHERE 1=1"
    args = []
    if portal:
        sql += " AND portal=?"
        args.append(portal)
    if keyword:
        sql += " AND (name LIKE ? OR userid LIKE ? OR post_name LIKE ?)"
        args += ["%%%s%%" % keyword] * 3
    sql += " ORDER BY userid, primary_flag DESC, post_id LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in db.q(sql, tuple(args))]


def update(userid, post_name="", class_ids=None, level="", portal=""):
    row = db.q("SELECT * FROM account_bindings WHERE userid=? ORDER BY primary_flag DESC LIMIT 1",
               (userid,), one=True)
    if not row:
        raise ValueError("该账号没有映射记录")
    pname = post_name or row["post_name"]
    lv = level or row["level"]
    classes = class_ids if class_ids is not None else db.loads(row["class_ids"], [])
    db.exec_("UPDATE account_bindings SET post_name=?,level=?,portal=?,class_ids=?,"
             "data_scope=?,review_status='已确认',updated_at=? WHERE post_id=?",
             (pname, lv, portal or row["portal"], db.dumps(classes),
              _scope(lv, classes, pname), db.now(), row["post_id"]))
    return {"post_id": row["post_id"], "review_status": "已确认"}


def posts_of(user_id):
    """与 org_posts 同结构的有效职务列表（供 org.posts_of 合并）。"""
    rows = db.q("SELECT * FROM account_bindings WHERE userid=?", (str(user_id),))
    out = []
    for r in rows:
        out.append({
            "user_id": r["userid"], "name": r["name"], "dept_path": r["dept_path"],
            "post_id": r["post_id"], "post_name": r["post_name"],
            "agent_id": r["agent_id"], "agent_name": r["agent_name"],
            "level": r["level"], "data_scope": r["data_scope"], "portal": r["portal"],
            "class_ids": r["class_ids"], "primary_flag": r["primary_flag"],
            "committee_line": r["committee_line"], "level_source": r["level_source"],
            "level_pending": 0, "in_chain": r["in_chain"],
            "auto_level": r["level"], "status": "active",
        })
    return out


def export_csv():
    import csv
    import io
    buf = io.StringIO()
    buf.write("\ufeff")
    w = csv.writer(buf)
    w.writerow(["登录账号", "姓名", "类别", "部门", "职务名称", "端", "层级", "班级",
                "数据范围", "主职务", "智能体", "复核状态"])
    for r in db.q("SELECT * FROM account_bindings ORDER BY userid, primary_flag DESC, post_id"):
        w.writerow([r["userid"], r["name"], r["category"], r["dept_path"], r["post_name"],
                    r["portal"], r["level"], ",".join(db.loads(r["class_ids"], [])),
                    r["data_scope"], "是" if r["primary_flag"] else "否",
                    r["agent_name"], r["review_status"]])
    return buf.getvalue().encode("utf-8")
