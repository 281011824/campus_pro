# -*- coding: utf-8 -*-
"""教官 / 寝管巡查记录（违纪违规 · 仪容仪表 · 卫生检查）。

- 事项与分值固定，现场提交即生效（status=effective）；
- 学生级记录在同一事务内镜像写入 dom_behavior 并直接置 confirmed，进入既有德育量化；
- 班级 / 寝室级卫生记录只进巡查台账，不写 dom_behavior；
- 本人可撤回当日记录，政教处与管理员可作废任意记录；作废同步置 dom_behavior 为 void。
"""

import re
from datetime import date

from tasks.domain.identity import classes as class_dict
from tasks.shared import db
from tasks.modules.supervisor import dorms

SCHEMA = """
CREATE TABLE IF NOT EXISTS inspection_records (
  id TEXT PRIMARY KEY, ts TEXT NOT NULL, event_date TEXT NOT NULL,
  category TEXT NOT NULL, item_code TEXT NOT NULL, item_name TEXT NOT NULL,
  points INTEGER NOT NULL, target_type TEXT NOT NULL,
  class_id TEXT, student_id TEXT, dorm_id INTEGER, dorm_label TEXT,
  grade TEXT, note TEXT NOT NULL DEFAULT '',
  operator TEXT NOT NULL, operator_category TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'effective',
  voided_by TEXT, voided_at TEXT, void_reason TEXT,
  moral_event_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspection_date ON inspection_records(event_date);
CREATE INDEX IF NOT EXISTS idx_inspection_class ON inspection_records(class_id);
CREATE INDEX IF NOT EXISTS idx_inspection_student ON inspection_records(class_id, student_id);
CREATE INDEX IF NOT EXISTS idx_inspection_operator ON inspection_records(operator);
"""

# ---------------------------------------------------------------- 事项目录（分值固定）
# (code, name)
VIOLATIONS = [
    ("late_morning", "早自习迟到"),
    ("late_afternoon", "下午上课迟到"),
    ("smoking", "抽烟"),
    ("fight", "打架"),
    ("climb_wall", "翻墙"),
    ("takeout", "外卖"),
    ("theft", "偷盗"),
    ("alcohol", "酗酒"),
    ("littering", "乱丢垃圾"),
    ("vandalism", "毁坏公物"),
    ("phone", "玩手机"),
    ("romance", "谈恋爱"),
    ("dorm_discipline", "就寝纪律"),
]

APPEARANCE = [
    ("no_uniform", "不穿校服"),
    ("jewelry", "戴首饰"),
    ("tattoo", "纹身"),
    ("strange_clothes", "奇装异服"),
    ("hairstyle", "发型发饰"),
]

# (code, name, points, target_type, object, grade)
# object 为卫生对象标识（classroom 教室 / dorm 寝室 / area 清洁区），前端按此匹配切换
SANITATION = [
    ("classroom_excellent", "教室卫生·优", 1, "class", "classroom", "优"),
    ("classroom_poor", "教室卫生·差", -1, "class", "classroom", "差"),
    ("dorm_excellent", "寝室卫生·优", 1, "dorm", "dorm", "优"),
    ("dorm_poor", "寝室卫生·差", -1, "dorm", "dorm", "差"),
    ("area_excellent", "清洁区·优", 1, "class", "area", "优"),
    ("area_poor", "清洁区·差", -1, "class", "area", "差"),
]

# 学生级事项目标类型固定为 student，全部 -1 分
_ITEMS = {}
for _code, _name in VIOLATIONS:
    _ITEMS[_code] = {"code": _code, "name": _name, "points": -1,
                     "target_type": "student", "category": "violation"}
for _code, _name in APPEARANCE:
    _ITEMS[_code] = {"code": _code, "name": _name, "points": -1,
                     "target_type": "student", "category": "appearance"}
for _code, _name, _points, _target, _obj, _grade in SANITATION:
    _ITEMS[_code] = {"code": _code, "name": _name, "points": _points,
                     "target_type": _target, "category": "sanitation",
                     "object": _obj, "grade": _grade}

CATEGORIES = ("violation", "appearance", "sanitation")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def catalog():
    """固定事项目录：违纪违规 / 仪容仪表 / 卫生检查（含对象与评价）。"""
    return {
        "violation": [{"code": c, "name": n, "points": -1} for c, n in VIOLATIONS],
        "appearance": [{"code": c, "name": n, "points": -1} for c, n in APPEARANCE],
        "sanitation": [
            {"code": c, "name": n, "points": p, "target_type": t,
             "object": o, "grade": g}
            for c, n, p, t, o, g in SANITATION
        ],
    }


def init():
    """幂等建表与索引；重复调用不报错。"""
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()


def _today():
    return date.today().isoformat()


def _day(value):
    """规范化记录日期：空值取今天；格式非法抛 ValueError。"""
    text = str(value or "").strip()
    if not text:
        return _today()
    if not _DATE_RE.match(text):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    return text


# ---------------------------------------------------------------- 选择器数据
def search_students(q, limit=20):
    """按姓名 / 学号模糊检索，只返回学号、姓名、班级与班主任姓名。"""
    keyword = str(q or "").strip()
    if not keyword:
        return []
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(20, limit))
    like = "%%%s%%" % keyword
    rows = db.q(
        "SELECT s.student_id AS student_id, s.student_no AS student_no, s.name AS name, "
        "s.class_id AS class_id, c.name AS class_name, a.name AS head_teacher_name "
        "FROM students s "
        "LEFT JOIN classes c ON c.class_id=s.class_id "
        "LEFT JOIN school_accounts a ON a.userid=c.head_teacher_userid "
        "WHERE s.name LIKE ? OR s.student_no LIKE ? OR s.student_id LIKE ? "
        "ORDER BY s.class_id, s.student_id LIMIT ?",
        (like, like, like, limit))
    items = []
    for r in rows:
        items.append({
            "student_id": str(r.get("student_id") or ""),
            "student_no": str(r.get("student_no") or ""),
            "name": str(r.get("name") or ""),
            "class_id": str(r.get("class_id") or ""),
            "class_name": str(r.get("class_name") or ""),
            "head_teacher_name": str(r.get("head_teacher_name") or ""),
        })
    return items


def classes_for_picker():
    """班级下拉：编号、名称、年级、专业、班主任姓名、学生数。"""
    items = []
    for it in class_dict.list():
        items.append({
            "class_id": it.get("class_id") or "",
            "name": it.get("name") or "",
            "grade": it.get("grade") or "",
            "major": it.get("major") or "",
            "head_teacher_name": it.get("head_teacher_name") or "",
            "student_count": int(it.get("student_count") or 0),
        })
    return items


def dorms_for_picker():
    """寝室下拉：楼栋、房号、展示名、性别、容量与已住人数。

    来源：dorms.list_available()，同时覆盖 dorms 表预置条目与
    students.dorm 里真实在用但未入库的房号。后者 id 为 null，
    前端提交时应走 dorm_label 字段；两者均为可选。
    """
    items = []
    for it in dorms.list_available():
        items.append({
            "id": it.get("id"),  # None 表示仅存在于 students.dorm，未入库
            "building": it.get("building") or "",
            "room_no": it.get("room_no") or "",
            "label": it.get("label") or "",
            "gender": it.get("gender") or "",
            "capacity": int(it.get("capacity") or 0),
            "occupied": int(it.get("occupied") or 0),
        })
    return items


# ---------------------------------------------------------------- 记录写入
def _source_of(operator_category):
    """德育事件来源：教官/寝管（含合并类别）标记为「教官巡查」「寝管巡查」「教官寝管巡查」，其余记「巡查」。"""
    category = str(operator_category or "").strip()
    if category in ("教官", "寝管", "教官寝管"):
        return "%s巡查" % category
    return "巡查"


def create_record(operator, operator_category, item_code, class_id=None, student_id=None,
                  student_no=None, dorm_id=None, dorm_label=None, note="", event_date=None):
    """登记一条巡查记录；学生级同事务镜像 dom_behavior（confirmed）。

    student_id（学籍号 T 开头）与 student_no（正式学号）二选一；同时给出时以 student_id 为准。
    寝室可传 dorm_id（dorms 表主键）或 dorm_label（房号文本，如 3105、2号楼3105），
    前端下拉有 id 的会传 dorm_id，手动输入或仅有房号时传 dorm_label，两者兼容。
    返回 {"record": 记录, "summary": 当日汇总}；校验失败抛 ValueError。
    """
    code = str(item_code or "").strip()
    item = _ITEMS.get(code)
    if not item:
        raise ValueError("巡查事项不存在")

    cid = str(class_id or "").strip()
    sid = str(student_id or "").strip()
    sno = str(student_no or "").strip()
    # 前端检索结果可能只带正式学号：按班级 + 学号解析学籍号，避免把学号误当学籍号
    if cid and not sid and sno:
        found = db.q("SELECT student_id FROM students WHERE class_id=? AND student_no=?",
                     (cid, sno), one=True)
        if not found:
            raise ValueError("学生不存在或学号有误")
        sid = str(found.get("student_id") or "")

    # 寝室入参：优先 dorm_id，其次 dorm_label（文本房号）；允许其中一个传值
    raw_dorm_id = "" if dorm_id is None else str(dorm_id).strip()
    raw_dorm_label = "" if dorm_label is None else str(dorm_label).strip()
    dorm_id_int = None
    dorm_label_text = ""
    if raw_dorm_id:
        try:
            dorm_id_int = int(raw_dorm_id)
            rec = dorms.get(dorm_id_int)
            if rec:
                dorm_label_text = rec.get("label") or rec.get("room_no") or ""
        except (TypeError, ValueError):
            raise ValueError("寝室不存在（dorm_id 不是有效数字）")
        target = "dorm"
    elif raw_dorm_label:
        # 文本房号：不强制查 dorms 表，直接用（兼容学校未录入 dorms 表的真实寝室）
        dorm_label_text = raw_dorm_label
        # 再尝试 dorms 表回填 dorm_id：用 label 末尾的数字房号去匹配
        m = re.search(r"(\d{3,6})$", raw_dorm_label)
        room_only = m.group(1) if m else raw_dorm_label
        try:
            rec = db.q(
                "SELECT id FROM dorms WHERE room_no=? LIMIT 1",
                (str(room_only),), one=True)
            if rec:
                dorm_id_int = int(rec["id"])
        except Exception:
            dorm_id_int = None
        target = "dorm"
    elif sid:
        target = "student"
    else:
        target = "class"

    if item["target_type"] != target:
        if item["category"] == "sanitation":
            raise ValueError("卫生检查只能登记班级或寝室")
        raise ValueError("该事项只能登记到学生")

    if target == "student":
        if not cid:
            raise ValueError("请先选择班级")
        if not db.q("SELECT 1 FROM students WHERE class_id=? AND student_id=?",
                    (cid, sid), one=True):
            raise ValueError("学生不存在")
    elif target == "class":
        if not cid:
            raise ValueError("请先选择班级")
        if not class_dict.get(cid):
            raise ValueError("班级不存在")
    else:
        if cid or sid:
            raise ValueError("寝室记录不能指定班级或学生")
        if not dorm_label_text:
            raise ValueError("请输入寝室号（如 3105）或从下拉选择")

    grade = str(item.get("grade") or "")
    day = _day(event_date)
    note_text = str(note or "").strip()
    now = db.now()
    rid = db.uid("ir_")
    moral_event_id = db.uid("be_") if target == "student" else None

    stmts = [(
        "INSERT INTO inspection_records"
        "(id,ts,event_date,category,item_code,item_name,points,target_type,"
        "class_id,student_id,dorm_id,dorm_label,grade,note,operator,operator_category,"
        "status,moral_event_id,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'effective',?,?)",
        (rid, now, day, item["category"], code, item["name"], item["points"], target,
         cid or None, sid or None, dorm_id_int if target == "dorm" else None,
         dorm_label_text, grade, note_text, str(operator or ""),
         str(operator_category or ""), moral_event_id, now),
    )]

    if target == "student":
        fact = "巡查登记：%s" % item["name"]
        if note_text:
            fact += "；%s" % note_text
        stmts.append((
            "INSERT INTO dom_behavior"
            "(id,ts,class_id,student_id,event_date,polarity,category,points,status,"
            "fact,source,confirmed_by,confirmed_at) "
            "VALUES(?,?,?,?,?,?,?,?,'confirmed',?,?,?,?)",
            (moral_event_id, now, cid, sid, day,
             "negative" if item["points"] < 0 else "positive",
             item["name"], item["points"], fact[:200],
             _source_of(operator_category), str(operator or ""), now),
        ))
    db.exec_many(stmts)

    if target == "student":
        tgt = "%s/%s" % (cid, sid)
    elif target == "class":
        tgt = cid
    else:
        tgt = dorm_label
    db.audit({"user_id": operator}, "inspection.create", "ok", rid,
             "%s/%s/%s" % (item["category"], item["name"], tgt))
    return {"record": _get_record(rid), "summary": summary_today(day)}


def void_record(operator, operator_category, record_id, reason="", is_admin=False,
                is_deyu=False):
    """撤回 / 作废：本人当日或政教处 / 管理员；同步作废德育镜像事件。"""
    rid = str(record_id or "").strip()
    row = db.q("SELECT * FROM inspection_records WHERE id=?", (rid,), one=True)
    if not row:
        return {"ok": False, "error": "记录不存在"}
    rec = dict(row)
    if str(rec.get("status") or "") != "effective":
        return {"ok": False, "error": "该记录已作废"}
    allowed = bool(is_admin or is_deyu) or (
        str(rec.get("operator") or "") == str(operator or "")
        and str(rec.get("event_date") or "") == _today()
    )
    if not allowed:
        return {"ok": False,
                "error": "只能撤回本人当日记录，历史记录请联系政教处处理",
                "forbidden": True}

    now = db.now()
    stmts = [(
        "UPDATE inspection_records SET status='void',voided_by=?,voided_at=?,void_reason=? "
        "WHERE id=?",
        (str(operator or ""), now, str(reason or "").strip(), rid),
    )]
    if rec.get("moral_event_id"):
        stmts.append(("UPDATE dom_behavior SET status='void' WHERE id=?",
                      (rec["moral_event_id"],)))
    db.exec_many(stmts)
    db.audit({"user_id": operator}, "inspection.void", "ok", rid,
             "%s/%s" % (rec.get("category") or "", rec.get("item_name") or ""))
    return {"ok": True, "id": rid, "status": "void",
            "summary": summary_today(rec.get("event_date"))}


# ---------------------------------------------------------------- 查询
_RECORD_SELECT = (
    "SELECT r.*, s.name AS student_name, s.student_no AS student_no, "
    "c.name AS class_name "
    "FROM inspection_records r "
    "LEFT JOIN students s ON s.class_id=r.class_id AND s.student_id=r.student_id "
    "LEFT JOIN classes c ON c.class_id=r.class_id "
)


def _target_label(row):
    target = str(row.get("target_type") or "")
    if target == "student":
        name = str(row.get("student_name") or "")
        no = str(row.get("student_no") or "").strip()
        if no:
            return "%s（%s）" % (name, no) if name else no
        return name
    if target == "dorm":
        return str(row.get("dorm_label") or "")
    return str(row.get("class_name") or row.get("class_id") or "")


def _present(row):
    """统一输出字段（白名单，不含学生电话 / 住址 / 家长信息）。"""
    target = str(row.get("target_type") or "")
    return {
        "id": row.get("id") or "",
        "ts": row.get("ts") or "",
        "event_date": row.get("event_date") or "",
        "category": row.get("category") or "",
        "item_code": row.get("item_code") or "",
        "item_name": row.get("item_name") or "",
        "points": int(row.get("points") or 0),
        "target_type": target,
        "target_label": _target_label(row),
        "class_id": row.get("class_id") or "",
        "class_name": row.get("class_name") or "",
        "student_id": row.get("student_id") or "",
        "student_name": row.get("student_name") or "",
        "student_no": row.get("student_no") or "",
        "dorm_id": row.get("dorm_id"),
        "dorm_label": row.get("dorm_label") or "",
        "grade": row.get("grade") or "",
        "note": row.get("note") or "",
        "operator": row.get("operator") or "",
        "operator_category": row.get("operator_category") or "",
        "status": row.get("status") or "",
    }


def _get_record(record_id):
    row = db.q(_RECORD_SELECT + "WHERE r.id=?", (str(record_id),), one=True)
    return _present(dict(row)) if row else None


def list_records(event_date=None, category="", operator=None, limit=50):
    """查询记录：默认今天；可按类别、记录人过滤。"""
    day = _day(event_date)
    where, args = ["r.event_date=?"], [day]
    category = str(category or "").strip()
    if category:
        if category not in CATEGORIES:
            raise ValueError("类别不合法")
        where.append("r.category=?")
        args.append(category)
    operator = str(operator or "").strip()
    if operator:
        where.append("r.operator=?")
        args.append(operator)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(200, limit))
    args.append(limit)
    rows = db.q(_RECORD_SELECT + "WHERE " + " AND ".join(where) +
                " ORDER BY r.ts DESC, r.id DESC LIMIT ?", tuple(args))
    return [_present(dict(r)) for r in rows]


def can_void(record, viewer, viewer_category, is_admin, is_deyu):
    """是否可撤回：管理员 / 政教处任意记录，本人仅当日记录。"""
    if not record or str(record.get("status") or "") != "effective":
        return False
    if is_admin or is_deyu:
        return True
    if str(record.get("operator") or "") != str(viewer or ""):
        return False
    return str(record.get("event_date") or "") == _today()


def summary_today(event_date=None):
    """当日汇总：三类各自条数与净分，以及合计。"""
    day = _day(event_date)
    rows = db.q(
        "SELECT category, COUNT(*) AS n, COALESCE(SUM(points),0) AS p "
        "FROM inspection_records WHERE event_date=? AND status='effective' "
        "GROUP BY category", (day,))
    out = {"date": day,
           "violation_count": 0, "violation_points": 0,
           "appearance_count": 0, "appearance_points": 0,
           "sanitation_count": 0, "sanitation_points": 0,
           "total_count": 0, "total_points": 0}
    for r in rows:
        key = str(r.get("category") or "")
        if key not in CATEGORIES:
            continue
        out[key + "_count"] = int(r.get("n") or 0)
        out[key + "_points"] = int(r.get("p") or 0)
        out["total_count"] += int(r.get("n") or 0)
        out["total_points"] += int(r.get("p") or 0)
    return out
