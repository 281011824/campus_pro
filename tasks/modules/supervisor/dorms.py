# -*- coding: utf-8 -*-
"""全校寝室字典表：楼栋 / 房号 / 性别 / 容量。

学生表 students.dorm 存寝室房号（label），与本表 room_no 对应，便于导入导出与展示；
本表用于下拉分配与容量统计，不与 students 建硬外键（兼容历史自由文本）。
"""

import builtins

from tasks.shared import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS dorms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  building TEXT NOT NULL DEFAULT '',
  room_no TEXT NOT NULL,
  gender TEXT NOT NULL DEFAULT '',
  capacity INTEGER NOT NULL DEFAULT 6,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_dorms_status ON dorms(status);
"""

GENDERS = ("", "男", "女")


def init():
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    _seed_demo()


def _seed_demo():
    # 多 worker 同时启动时用写事务串行化，避免演示寝室被重复播种
    c = db.connect()
    try:
        c.isolation_level = None
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT COUNT(*) FROM dorms").fetchone()[0]:
            c.rollback()
            return
        now = db.now()
        rows = [
            ("1号楼", "1401", "男", 6, "active"),
            ("1号楼", "1402", "男", 6, "active"),
            ("1号楼", "1403", "男", 6, "active"),
            ("2号楼", "2401", "女", 6, "active"),
            ("2号楼", "2402", "女", 6, "active"),
        ]
        for b, r, g, cap, s in rows:
            c.execute("INSERT INTO dorms(building,room_no,gender,capacity,status,created_at,updated_at) "
                      "VALUES(?,?,?,?,?,?,?)", (b, r, g, cap, s, now, now))
        c.commit()
    finally:
        c.close()


def label(rec):
    rec = rec or {}
    building = str(rec.get("building") or "")
    room = str(rec.get("room_no") or "")
    if not building:
        return room
    # 楼栋已自带「楼 / 栋」后缀时直接拼接，避免出现「1栋栋101」这类重复后缀
    if building.endswith(("楼", "栋")):
        return building + room
    return "%s栋%s" % (building, room)


def get(dorm_id):
    row = db.q("SELECT * FROM dorms WHERE id=?", (int(dorm_id),), one=True)
    if not row:
        return None
    it = dict(row)
    it["label"] = label(it)
    return it


def list(keyword="", status=""):
    where, args = [], []
    keyword = str(keyword or "").strip()
    if keyword:
        where.append("(building LIKE ? OR room_no LIKE ?)")
        args += ["%%%s%%" % keyword, "%%%s%%" % keyword]
    status = str(status or "").strip()
    if status:
        where.append("status=?")
        args.append(status)
    sql = "SELECT * FROM dorms"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY building, room_no"
    items = []
    for r in db.q(sql, tuple(args)):
        it = dict(r)
        it["label"] = label(it)
        it["occupied"] = db.q(
            "SELECT COUNT(*) AS n FROM students WHERE dorm=? AND dorm IS NOT NULL AND dorm!=''",
            (it["room_no"],), one=True)["n"]
        items.append(it)
    return items


def create(building="", room_no="", gender="", capacity=6, status="active"):
    room_no = str(room_no or "").strip()
    if not room_no:
        raise ValueError("寝室房号不能为空")
    if gender not in GENDERS:
        raise ValueError("性别不合法")
    try:
        capacity = int(capacity or 6)
    except (TypeError, ValueError):
        raise ValueError("容量必须是数字")
    now = db.now()
    did = db.exec_(
        "INSERT INTO dorms(building,room_no,gender,capacity,status,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (str(building or ""), room_no, str(gender or ""), capacity,
         str(status or "active"), now, now))
    return get(did)


def update(dorm_id, building=None, room_no=None, gender=None, capacity=None, status=None):
    rec = get(dorm_id)
    if not rec:
        raise ValueError("寝室不存在")
    fields, args = [], []
    if building is not None:
        fields.append("building=?"); args.append(str(building))
    if room_no is not None:
        fields.append("room_no=?"); args.append(str(room_no))
    if gender is not None:
        if gender not in GENDERS:
            raise ValueError("性别不合法")
        fields.append("gender=?"); args.append(str(gender))
    if capacity is not None:
        try:
            capacity = int(capacity)
        except (TypeError, ValueError):
            raise ValueError("容量必须是数字")
        fields.append("capacity=?"); args.append(capacity)
    if status is not None:
        fields.append("status=?"); args.append(str(status))
    if fields:
        fields.append("updated_at=?"); args.append(db.now()); args.append(int(dorm_id))
        db.exec_("UPDATE dorms SET %s WHERE id=?" % ",".join(fields), tuple(args))
    return get(dorm_id)


def delete(dorm_id):
    rec = get(dorm_id)
    if not rec:
        raise ValueError("寝室不存在")
    n = db.q("SELECT COUNT(*) AS n FROM students WHERE dorm=?", (rec["room_no"],), one=True)["n"]
    if n:
        raise ValueError("该寝室仍有 %d 名学生入住，请先调整后再删除" % n)
    db.exec_("DELETE FROM dorms WHERE id=?", (int(dorm_id),))
    return True


def count():
    row = db.q("SELECT COUNT(*) AS n FROM dorms", one=True)
    return int(row["n"]) if row else 0


# ---------------------------------------------------------------- 巡查 / 通用选择器
def list_available():
    """所有可用寝室：dorms 表 + students.dorm 中出现过但未入库的房号。

    巡查记录需要覆盖全校所有真实在用寝室，而不仅仅是 dorms 表里预置的
    那些（演示库只播种了 5 条，真实学校寝室远多于此）。对于 dorms 表里
    没有的房号，只返回房号文本（room_no / label），不返回 dorm_id。
    前端可据此走 dorm_label 文本提交，后端 create_record 已兼容两种。
    """
    seen = {}
    for rec in db.q("SELECT * FROM dorms WHERE status!='inactive' ORDER BY building, room_no"):
        it = dict(rec)
        it["label"] = label(it)
        occupied = db.q(
            "SELECT COUNT(*) AS n FROM students "
            "WHERE dorm=? AND dorm IS NOT NULL AND dorm!=''",
            (it["room_no"],), one=True)["n"]
        it["occupied"] = int(occupied or 0)
        seen[str(it["room_no"] or "")] = it

    for rec in db.q(
        "SELECT dorm, COUNT(*) AS occ FROM students "
        "WHERE dorm IS NOT NULL AND dorm!='' GROUP BY dorm ORDER BY dorm"):
        room = str(rec["dorm"] or "").strip()
        if not room or room in seen:
            continue
        seen[room] = {
            "id": None,
            "building": "",
            "room_no": room,
            "label": room,
            "gender": "",
            "capacity": 0,
            "occupied": int(rec["occ"] or 0),
        }

    # 再补上 dorms 表里存在但无学生入住的（dorms 表 active 条目）
    for rec in db.q("SELECT * FROM dorms WHERE status='active' ORDER BY building, room_no"):
        room = str(rec["room_no"] or "").strip()
        if room in seen:
            continue
        it = dict(rec)
        it["label"] = label(it)
        it["occupied"] = 0
        seen[room] = it

    def _sort_key(room_no):
        # 数字房号按数值排，否则按文本
        try:
            return (0, int(room_no), room_no)
        except (TypeError, ValueError):
            return (1, 0, room_no)

    items = [seen[k] for k in sorted(seen.keys(), key=_sort_key)]
    for it in items:
        try:
            it["id"] = int(it.get("id")) if it.get("id") is not None else None
        except (TypeError, ValueError):
            it["id"] = None
    return items


# ---------------------------------------------------------------- 政教处：统一分配
def list_for_assignment():
    """全校寝室 + 入住统计；occupied 与 students.dorm(room_no) 同源。"""
    items = []
    for rec in db.q("SELECT * FROM dorms ORDER BY building, room_no"):
        it = dict(rec)
        it["label"] = label(it)
        occupied = db.q("SELECT COUNT(*) AS n FROM students "
                        "WHERE dorm=? AND dorm IS NOT NULL AND dorm!=''",
                        (it["room_no"],), one=True)["n"]
        capacity = int(it.get("capacity") or 0)
        it["occupied"] = int(occupied or 0)
        it["remaining"] = max(capacity - it["occupied"], 0)
        items.append(it)
    return items


def _resolve_students(refs, class_id=""):
    """把 student_ids 解析为 (class_id, student_id, name, gender, dorm)。

    支持 "学号"、"班级:学号"、"班级/学号" 与 {class_id,student_id} 四种写法；
    学号跨班重复时必须指定班级，否则整单拒绝。
    """
    if not isinstance(refs, (builtins.list, tuple)):
        raise ValueError("学生列表格式错误")
    base_cid = str(class_id or "").strip()
    resolved, seen = [], set()
    for pos, raw in enumerate(refs):
        if isinstance(raw, dict):
            cid = str(raw.get("class_id") or base_cid).strip()
            sid = str(raw.get("student_id") or "").strip()
        else:
            text = str(raw or "").strip()
            cid = base_cid
            if ":" in text:
                cid, text = text.split(":", 1)
                cid = cid.strip()
            elif "/" in text:
                cid, text = text.split("/", 1)
                cid = cid.strip()
            sid = text.strip()
        if not sid:
            raise ValueError("第 %d 位学生学号为空" % (pos + 1))
        if cid:
            row = db.q("SELECT class_id,student_id,name,gender,dorm FROM students "
                       "WHERE class_id=? AND student_id=?", (cid, sid), one=True)
            if not row:
                raise ValueError("学生不存在：%s/%s" % (cid, sid))
        else:
            rows = db.q("SELECT class_id,student_id,name,gender,dorm FROM students "
                        "WHERE student_id=?", (sid,))
            if not rows:
                raise ValueError("学生不存在：%s" % sid)
            if len(rows) > 1:
                raise ValueError("学号 %s 在多个班级重复，请指定班级" % sid)
            row = rows[0]
        key = (str(row["class_id"]), str(row["student_id"]))
        if key in seen:
            continue
        seen.add(key)
        resolved.append(dict(row))
    if not resolved:
        raise ValueError("请选择至少一名学生")
    return resolved


def assign(dorm_id, student_ids, class_id=""):
    """批量分配寝室；任一校验失败整单拒绝，不产生部分写入。"""
    try:
        dorm_id = int(dorm_id)
    except (TypeError, ValueError):
        raise ValueError("寝室不存在")
    rec = get(dorm_id)
    if not rec:
        raise ValueError("寝室不存在")
    if str(rec.get("status") or "") != "active":
        raise ValueError("寝室已停用，不能分配")
    students = _resolve_students(student_ids, class_id)

    gender = str(rec.get("gender") or "").strip()
    if gender:
        bad = [s for s in students
               if str(s.get("gender") or "").strip() != gender]
        if bad:
            raise ValueError("性别不符：%s（%s）不能入住%s寝"
                             % (bad[0]["name"] or bad[0]["student_id"],
                                bad[0].get("gender") or "未登记",
                                gender))
    room_no = str(rec["room_no"])
    occupied = int(db.q("SELECT COUNT(*) AS n FROM students WHERE dorm=?",
                        (room_no,), one=True)["n"] or 0)
    moving = [s for s in students if str(s.get("dorm") or "") != room_no]
    remaining = int(rec.get("capacity") or 0) - occupied
    if len(moving) > remaining:
        raise ValueError("寝室余量不足：剩余 %d 个床位，本次需安排 %d 人"
                         % (max(remaining, 0), len(moving)))

    now = db.now()
    c = db.connect()
    c.isolation_level = None
    try:
        c.execute("BEGIN IMMEDIATE")
        for stu in students:
            c.execute("UPDATE students SET dorm=?,updated_at=? WHERE class_id=? AND student_id=?",
                      (room_no, now, str(stu["class_id"]), str(stu["student_id"])))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    return {"dorm_id": rec["id"], "label": rec["label"], "room_no": room_no,
            "assigned": len(students), "remaining": max(remaining - len(moving), 0)}


def unassign(student_ids, class_id=""):
    """清空所选学生的寝室字段。"""
    students = _resolve_students(student_ids, class_id)
    now = db.now()
    c = db.connect()
    c.isolation_level = None
    cleared = 0
    try:
        c.execute("BEGIN IMMEDIATE")
        for stu in students:
            cur = c.execute(
                "UPDATE students SET dorm='',updated_at=? WHERE class_id=? AND student_id=?",
                (now, str(stu["class_id"]), str(stu["student_id"])))
            cleared += cur.rowcount
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()
    return {"cleared": cleared}
