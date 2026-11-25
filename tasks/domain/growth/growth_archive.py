# -*- coding: utf-8 -*-
"""学生成长档案 · 五维记录模型（P0）

对应《学生成长模块重构方案 v1.0》的“一轴五维三阶”：
  - 五维：品德与公民素养 / 学业与专业技能 / 身心与健康 / 审美与艺体 / 劳动与职业素养
  - 每条记录含事实、时间、来源、佐证与确认状态
  - 五维分别评级，不合成总分、不排名
  - 心理明细、家长电话不进入本表

本模块只负责成长档案本身；出勤、德育、成绩等仍从 dom_* / students 只读引用。
"""
import json
from datetime import date, datetime, timedelta

from tasks.shared import db

DIMENSIONS = [
    {"id": "de", "name": "品德与公民素养", "short": "品德", "items": [
        {"key": "behavior", "name": "行为规范与校纪校规"},
        {"key": "theme", "name": "主题教育与党团活动"},
        {"key": "volunteer", "name": "志愿服务与公益劳动"},
        {"key": "integrity", "name": "诚信与责任表现"},
        {"key": "honor", "name": "荣誉与家校沟通"},
    ]},
    {"id": "xue", "name": "学业与专业技能", "short": "学业技能", "items": [
        {"key": "basic", "name": "公共基础课学习"},
        {"key": "major", "name": "专业课程与实训成绩"},
        {"key": "contest", "name": "技能竞赛"},
        {"key": "cert", "name": "1+X与职业资格证书"},
        {"key": "work", "name": "作品与项目"},
    ]},
    {"id": "shen", "name": "身心与健康", "short": "身心健康", "items": [
        {"key": "fitness", "name": "体质健康测试"},
        {"key": "sports", "name": "体育锻炼与运动会"},
        {"key": "mind", "name": "心理课程与活动参与"},
        {"key": "habit", "name": "健康生活习惯"},
    ]},
    {"id": "mei", "name": "审美与艺体", "short": "审美艺体", "items": [
        {"key": "art", "name": "艺术课程学习"},
        {"key": "club", "name": "社团与文艺活动"},
        {"key": "works", "name": "艺术作品与特长"},
    ]},
    {"id": "lao", "name": "劳动与职业素养", "short": "劳动职业", "items": [
        {"key": "labor", "name": "校园劳动与专业劳动"},
        {"key": "intern", "name": "跟岗与顶岗实习"},
        {"key": "career", "name": "职业认知与生涯规划"},
        {"key": "spirit", "name": "职业精神与团队协作"},
    ]},
]

DIM_MAP = {d["id"]: d for d in DIMENSIONS}
STATUS_TEXT = {"confirmed": "已确认", "pending": "待确认", "returned": "退回补证"}
LEVEL_RANK = {"A": 3, "B": 2, "C": 1}

SCHEMA = """
CREATE TABLE IF NOT EXISTS growth_items (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  dim TEXT NOT NULL,
  sub_item TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  fact TEXT NOT NULL DEFAULT '',
  occurred_on TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '班主任',
  evidence TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'confirmed',
  term TEXT NOT NULL DEFAULT '',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  confirmed_by TEXT,
  confirmed_at TEXT,
  origin TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_growth_stu ON growth_items(class_id, student_id, occurred_on);
CREATE INDEX IF NOT EXISTS idx_growth_term ON growth_items(class_id, term);

CREATE TABLE IF NOT EXISTS growth_certificates (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  name TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT '',
  issuer TEXT NOT NULL DEFAULT '',
  cert_no TEXT NOT NULL DEFAULT '',
  issued_on TEXT NOT NULL DEFAULT '',
  evidence TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS growth_internships (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  company TEXT NOT NULL DEFAULT '',
  post TEXT NOT NULL DEFAULT '',
  period TEXT NOT NULL DEFAULT '',
  mentor TEXT NOT NULL DEFAULT '',
  enterprise_score TEXT NOT NULL DEFAULT '',
  comment TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS growth_terms (
  id TEXT PRIMARY KEY,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  term TEXT NOT NULL,
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'draft',
  generated_at TEXT,
  published_at TEXT,
  UNIQUE(class_id, student_id, term)
);

CREATE TABLE IF NOT EXISTS growth_report_versions (
  id TEXT PRIMARY KEY,
  report_id TEXT NOT NULL,
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL,
  term TEXT NOT NULL,
  version INTEGER NOT NULL,
  snapshot_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'published',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  published_at TEXT,
  UNIQUE(report_id, version)
);
"""


def _today():
    return date.today().isoformat()


def term_of(day=None):
    d = str(day or _today())
    try:
        y, m = int(d[:4]), int(d[5:7])
    except Exception:
        y, m = datetime.now().year, datetime.now().month
    return "%d%s" % (y, "秋" if m >= 8 else "春")


def init(seed_class="2607"):
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    migrate_legacy()
    seeded = seed_demo(seed_class)
    return {"seeded": seeded}


# ---------------------------------------------------------------- 旧记录迁移
def _legacy_map(kind, title):
    title = title or ""
    if kind == "特长":
        if any(k in title for k in ("数控", "电子", "计算机", "烹饪", "汽修", "电商", "会计", "机械")):
            return "xue", "作品与项目"
        if any(k in title for k in ("篮球", "田径", "足球", "羽毛球", "乒乓", "体育")):
            return "shen", "体育锻炼与运动会"
        return "mei", "艺术作品与特长"
    if kind == "兴趣":
        return "mei", "社团与文艺活动"
    if kind == "奖惩":
        if any(k in title for k in ("技能", "竞赛", "大赛")):
            return "xue", "技能竞赛"
        return "de", "荣誉与家校沟通"
    return "de", "荣誉与家校沟通"


def migrate_legacy():
    """把 student_records（特长/兴趣/奖惩/家访）迁入五维，幂等，可回滚。"""
    rows = db.q("SELECT * FROM student_records ORDER BY created_at")
    if not rows:
        return 0
    done = {r["origin"] for r in db.q(
        "SELECT origin FROM growth_items WHERE origin LIKE 'sr:%'")}
    batch = []
    for r in rows:
        origin = "sr:" + r["id"]
        if origin in done:
            continue
        dim, sub = _legacy_map(r["kind"], r["title"])
        day = r["day"] or (r["created_at"] or "")[:10] or _today()
        batch.append((
            db.uid("gi_"), r["class_id"], r["student_id"], dim, sub,
            r["title"] or r["kind"], r["detail"] or "", day[:10],
            "历史记录", "", "confirmed", term_of(day),
            r["created_by"] or "", r["created_at"] or db.now(),
            r["created_by"] or "", r["created_at"] or db.now(), origin,
        ))
    if not batch:
        return 0
    db.exec_many([(
        "INSERT INTO growth_items(id,class_id,student_id,dim,sub_item,title,fact,occurred_on,"
        "source,evidence,status,term,created_by,created_at,confirmed_by,confirmed_at,origin) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row) for row in batch])
    return len(batch)


def seed_demo(class_id="2607"):
    """为演示班补几条五维记录，让成长档案有可看的连续性；幂等。"""
    if not db.q("SELECT 1 FROM students WHERE class_id=? LIMIT 1", (str(class_id),), one=True):
        return 0
    if db.q("SELECT 1 FROM growth_items WHERE class_id=? AND origin='demo' LIMIT 1",
            (str(class_id),), one=True):
        return 0
    students = db.q("SELECT student_id FROM students WHERE class_id=? ORDER BY student_id",
                    (str(class_id),))
    batch = []
    for i, s in enumerate(students):
        sid = s["student_id"]

        def add(dim, sub, title, day, evidence):
            batch.append((
                db.uid("gi_"), str(class_id), sid, dim, sub, title,
                "演示数据，用于联调五维档案展示", day, "演示数据", evidence,
                "confirmed", term_of(day), "演示数据", db.now(), "演示数据", db.now(), "demo",
            ))

        if i % 2 == 0:
            add("de", "志愿服务与公益劳动", "社区志愿服务 6 小时", "2026-11-10", "服务证明")
        if i % 5 == 0:
            add("xue", "技能竞赛", "校级技能竞赛 三等奖", "2026-12-06", "获奖证书")
        if i % 6 == 0:
            add("xue", "1+X与职业资格证书", "1+X 证书（初级）", "2026-11-22", "证书照片")
        if i % 3 == 0:
            add("lao", "校园劳动与专业劳动", "校园劳动周", "2026-10-30", "劳动评价")
        if i % 4 == 0:
            add("shen", "体育锻炼与运动会", "校运动会参赛", "2026-10-18", "参赛记录")
        if i % 2 == 1:
            add("mei", "社团与文艺活动", "社团活动展示", "2026-11-08", "活动照片")
    if batch:
        db.exec_many([(
            "INSERT INTO growth_items(id,class_id,student_id,dim,sub_item,title,fact,occurred_on,"
            "source,evidence,status,term,created_by,created_at,confirmed_by,confirmed_at,origin) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row) for row in batch])
    return len(batch)


# ---------------------------------------------------------------- 查询
def _items(class_id, student_id, term=None):
    sql = "SELECT * FROM growth_items WHERE class_id=? AND student_id=?"
    args = [str(class_id), str(student_id)]
    if term:
        sql += " AND term=?"
        args.append(str(term))
    sql += " ORDER BY occurred_on DESC, created_at DESC"
    return db.q(sql, args)


def _level(items):
    confirmed = [x for x in items if x["status"] == "confirmed"]
    count = len(confirmed)
    subs = {x["sub_item"] for x in confirmed if x["sub_item"]}
    evidence = sum(1 for x in confirmed if x["evidence"])
    if count == 0:
        return None, "证据不足"
    if count >= 4 and len(subs) >= 2 and evidence >= 2:
        return "A", "表现突出"
    if count >= 3 and len(subs) >= 2:
        return "B", "达到要求"
    return "C", "证据待补充"


def _dim_summary(items, dim):
    arr = [x for x in items if x["dim"] == dim["id"]]
    level, text = _level(arr)
    confirmed = [x for x in arr if x["status"] == "confirmed"]
    subs = {x["sub_item"] for x in confirmed if x["sub_item"]}
    return {
        "id": dim["id"], "name": dim["name"], "short": dim["short"],
        "level": level, "level_text": text,
        "count": len(confirmed),
        "pending": sum(1 for x in arr if x["status"] == "pending"),
        "evidence": sum(1 for x in confirmed if x["evidence"]),
        "coverage": round(len(subs) * 100.0 / max(1, len(dim["items"]))),
        "items": sorted(arr, key=lambda x: (x["occurred_on"] or "", x["created_at"] or ""),
                        reverse=True)[:6],
    }


def _prev_term(term):
    try:
        y, season = int(term[:4]), term[4:]
    except Exception:
        return ""
    if season == "秋":
        return "%d春" % y
    return "%d秋" % (y - 1)


def _progress(cur_items, prev_items):
    if not prev_items:
        return None
    cur = len([x for x in cur_items if x["status"] == "confirmed"])
    prev = len([x for x in prev_items if x["status"] == "confirmed"])
    if prev == 0:
        return None
    if cur >= prev + 2:
        return "进步"
    if cur <= prev - 2:
        return "需关注"
    return "稳定"


def student360(class_id, student_id, term=None):
    stu = db.q("SELECT * FROM students WHERE class_id=? AND student_id=?",
               (str(class_id), str(student_id)), one=True)
    if not stu:
        return None
    items = _items(class_id, student_id)
    all_certs = db.q("SELECT * FROM growth_certificates WHERE class_id=? AND student_id=? "
                     "ORDER BY issued_on DESC", (str(class_id), str(student_id)))
    report_terms = db.q("SELECT term FROM growth_terms WHERE class_id=? AND student_id=?",
                        (str(class_id), str(student_id)))
    terms = sorted({x["term"] for x in items if x["term"]} |
                   {term_of(x["issued_on"]) for x in all_certs if x["issued_on"]} |
                   {x["term"] for x in report_terms}, reverse=True)
    term = str(term or (terms[0] if terms else term_of()))
    cur = [x for x in items if x["term"] == term]
    prev = [x for x in items if x["term"] == _prev_term(term)]
    dims = []
    for d in DIMENSIONS:
        ds = _dim_summary(cur, d)
        ds["progress"] = _progress([x for x in cur if x["dim"] == d["id"]],
                                   [x for x in prev if x["dim"] == d["id"]])
        dims.append(ds)
    timeline = [{
        "id": x["id"], "date": x["occurred_on"], "dim": x["dim"],
        "dim_name": DIM_MAP.get(x["dim"], {}).get("name", x["dim"]),
        "sub_item": x["sub_item"], "title": x["title"], "fact": x["fact"],
        "source": x["source"], "evidence": x["evidence"], "status": x["status"],
        "status_text": STATUS_TEXT.get(x["status"], x["status"]),
    } for x in cur]
    start = date.today() - timedelta(days=6)
    try:
        att = db.q("SELECT status,COUNT(*) AS n FROM dom_attendance WHERE class_id=? AND student_id=? "
                   "AND date>=? GROUP BY status", (str(class_id), str(student_id), start.isoformat()))
        moral = db.q("SELECT event_date,polarity,category,points,status FROM dom_behavior "
                     "WHERE class_id=? AND student_id=? ORDER BY event_date DESC, ts DESC LIMIT 8",
                     (str(class_id), str(student_id)))
    except Exception:
        att, moral = [], []
    certs = [x for x in all_certs if term_of(x["issued_on"]) == term]
    intern = db.q("SELECT * FROM growth_internships WHERE class_id=? AND student_id=? "
                  "ORDER BY created_at DESC LIMIT 1", (str(class_id), str(student_id)), one=True)
    return {
        "student": dict(stu),
        "term": term, "terms": terms or [term],
        "dims": dims,
        "timeline": timeline,
        "certificates": [dict(x) for x in certs],
        "report": get_report(class_id, student_id, term),
        "internship": dict(intern) if intern else None,
        "attendance": {r["status"]: int(r["n"]) for r in att},
        "behavior": [dict(r) for r in moral],
        "counts": {
            "total": len(cur),
            "confirmed": sum(1 for x in cur if x["status"] == "confirmed"),
            "pending": sum(1 for x in cur if x["status"] == "pending"),
            "returned": sum(1 for x in cur if x["status"] == "returned"),
        },
    }


def class_overview(class_id):
    students = db.q("SELECT * FROM students WHERE class_id=? ORDER BY student_id", (str(class_id),))
    if not students:
        return {"class_id": str(class_id), "total": 0, "items": [], "stats": {
            "attention": 0, "pending": 0, "empty": 0}, "terms": [term_of()]}
    rows = db.q("SELECT * FROM growth_items WHERE class_id=?", (str(class_id),))
    terms = sorted({r["term"] for r in rows if r["term"]}, reverse=True) or [term_of()]
    term = terms[0]
    rows = [r for r in rows if r["term"] == term]
    by_stu = {}
    for r in rows:
        by_stu.setdefault(r["student_id"], []).append(r)
    items, attention, pending_n, empty_n = [], 0, 0, 0
    for s in students:
        arr = by_stu.get(s["student_id"], [])
        by_dim = {}
        confirmed = 0
        pend = 0
        for x in arr:
            by_dim.setdefault(x["dim"], []).append(x)
            if x["status"] == "confirmed":
                confirmed += 1
            elif x["status"] == "pending":
                pend += 1
        levels = {}
        for d in DIMENSIONS:
            levels[d["id"]] = _level(by_dim.get(d["id"], []))[0]
        missing = sum(1 for d in DIMENSIONS if levels[d["id"]] is None)
        attention_flag = pend > 0 or missing > 0 or confirmed < 2
        if pend:
            pending_n += 1
        if not arr:
            empty_n += 1
        if attention_flag:
            attention += 1
        last = max(arr, key=lambda x: (x["occurred_on"] or "", x["created_at"] or ""), default=None)
        items.append({
            "student_id": s["student_id"], "name": s["name"], "gender": s["gender"],
            "status": s["status"],
            "count": confirmed, "pending": pend, "missing": missing,
            "levels": levels, "attention": attention_flag,
            "flag": "待确认" if pend else ("证据待补" if missing else
                                           ("记录较少" if confirmed < 3 else "")),
            "last": {"title": last["title"], "date": last["occurred_on"],
                     "dim": DIM_MAP.get(last["dim"], {}).get("short", "")} if last else None,
        })
    items.sort(key=lambda x: (0 if x["flag"] == "待确认" else 1,
                              0 if x["flag"] == "证据待补" else 1, x["student_id"]))
    return {
        "class_id": str(class_id), "total": len(students), "items": items,
        "stats": {"attention": attention, "pending": pending_n, "empty": empty_n},
        "term": term, "terms": terms,
    }


# ---------------------------------------------------------------- 写入
def add_item(class_id, student_id, data, actor, source="班主任"):
    dim = str(data.get("dim") or "").strip()
    if dim not in DIM_MAP:
        raise ValueError("请选择成长维度")
    sub = str(data.get("sub_item") or "").strip()
    names = [x["name"] for x in DIM_MAP[dim]["items"]]
    if sub not in names:
        raise ValueError("请选择该维度下的记录类型")
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("请填写记录标题")
    day = str(data.get("occurred_on") or _today()).strip()[:10]
    fact = str(data.get("fact") or "").strip()
    evidence = str(data.get("evidence") or "").strip()
    src = str(data.get("source") or source).strip() or source
    status = "confirmed" if src == "班主任" else "pending"
    rid = db.uid("gi_")
    db.exec_(
        "INSERT INTO growth_items(id,class_id,student_id,dim,sub_item,title,fact,occurred_on,"
        "source,evidence,status,term,created_by,created_at,confirmed_by,confirmed_at,origin) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (rid, str(class_id), str(student_id), dim, sub, title, fact, day, src, evidence,
         status, term_of(day), str(actor or ""), db.now(),
         str(actor or "") if status == "confirmed" else "",
         db.now() if status == "confirmed" else "", ""),
    )
    return {"id": rid, "status": status}


def confirm_item(item_id, action, actor):
    row = db.q("SELECT * FROM growth_items WHERE id=?", (item_id,), one=True)
    if not row:
        raise ValueError("记录不存在")
    if action not in ("confirm", "return"):
        raise ValueError("操作不合法")
    if (row["origin"] or "").startswith("cert:"):
        res = confirm_certificate(row["origin"][5:], action, actor)
        return {"id": item_id, "status": res["status"], "class_id": row["class_id"]}
    status = "confirmed" if action == "confirm" else "returned"
    db.exec_("UPDATE growth_items SET status=?,confirmed_by=?,confirmed_at=? WHERE id=?",
             (status, str(actor or ""), db.now(), item_id))
    return {"id": item_id, "status": status, "class_id": row["class_id"]}


# ---------------------------------------------------------------- 1+X / 职业资格证书
def add_certificate(class_id, student_id, data, actor, source="班主任"):
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValueError("请填写证书名称")
    level = str(data.get("level") or "").strip()
    issuer = str(data.get("issuer") or "").strip()
    cert_no = str(data.get("cert_no") or "").strip()
    day = str(data.get("issued_on") or _today()).strip()[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        raise ValueError("发证日期格式不正确")
    if cert_no and db.q(
            "SELECT 1 FROM growth_certificates WHERE class_id=? AND student_id=? AND cert_no=?",
            (str(class_id), str(student_id), cert_no), one=True):
        raise ValueError("该证书编号已登记")
    evidence = str(data.get("evidence") or "").strip()
    src = str(data.get("source") or source).strip() or source
    status = "confirmed" if src == "班主任" else "pending"
    cid, item_id = db.uid("gc_"), db.uid("gi_")
    title = name + ("（%s）" % level if level else "")
    fact = "；".join(x for x in (
        "发证机构：%s" % issuer if issuer else "",
        "证书编号：%s" % cert_no if cert_no else "",
    ) if x) or "证书登记"
    now = db.now()
    db.exec_many([
        ("INSERT INTO growth_certificates(id,class_id,student_id,name,level,issuer,cert_no,"
         "issued_on,evidence,status,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
         (cid, str(class_id), str(student_id), name, level, issuer, cert_no, day,
          evidence, status, str(actor or ""), now)),
        ("INSERT INTO growth_items(id,class_id,student_id,dim,sub_item,title,fact,occurred_on,"
         "source,evidence,status,term,created_by,created_at,confirmed_by,confirmed_at,origin) "
         "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (item_id, str(class_id), str(student_id), "xue", "1+X与职业资格证书", title, fact,
          day, src, evidence, status, term_of(day), str(actor or ""), now,
          str(actor or "") if status == "confirmed" else "",
          now if status == "confirmed" else "", "cert:" + cid)),
    ])
    return {"id": cid, "item_id": item_id, "status": status}


def confirm_certificate(cert_id, action, actor):
    row = db.q("SELECT * FROM growth_certificates WHERE id=?", (cert_id,), one=True)
    if not row:
        raise ValueError("证书记录不存在")
    if action not in ("confirm", "return"):
        raise ValueError("操作不合法")
    status = "confirmed" if action == "confirm" else "returned"
    now = db.now()
    db.exec_many([
        ("UPDATE growth_certificates SET status=? WHERE id=?", (status, cert_id)),
        ("UPDATE growth_items SET status=?,confirmed_by=?,confirmed_at=? WHERE origin=?",
         (status, str(actor or ""), now, "cert:" + cert_id)),
    ])
    return {"id": cert_id, "status": status, "class_id": row["class_id"]}


# ---------------------------------------------------------------- 学期成长报告
REPORT_STATUS_TEXT = {"draft": "草稿", "published": "已发布"}


class ReportLockedError(ValueError):
    pass


def _valid_term(term):
    term = str(term or term_of())
    if len(term) != 5 or not term[:4].isdigit() or term[4:] not in ("春", "秋"):
        raise ValueError("学期格式应为“2026秋”")
    return term


def get_report(class_id, student_id, term):
    term = _valid_term(term)
    row = db.q("SELECT * FROM growth_terms WHERE class_id=? AND student_id=? AND term=?",
               (str(class_id), str(student_id), term), one=True)
    if not row:
        return None
    content = json.loads(row["snapshot_json"] or "{}")
    versions = db.q(
        "SELECT version,status,created_by,created_at,published_at FROM growth_report_versions "
        "WHERE report_id=? ORDER BY version DESC", (row["id"],))
    return {
        "id": row["id"], "class_id": row["class_id"], "student_id": row["student_id"],
        "term": row["term"], "status": row["status"],
        "status_text": REPORT_STATUS_TEXT.get(row["status"], row["status"]),
        "version": int(content.get("version") or 1),
        "generated_at": row["generated_at"], "published_at": row["published_at"],
        "content": content, "versions": versions,
    }


def generate_report(class_id, student_id, term, actor):
    term = _valid_term(term)
    data = student360(class_id, student_id, term)
    if not data:
        raise ValueError("未找到该学生")
    existing = db.q("SELECT * FROM growth_terms WHERE class_id=? AND student_id=? AND term=?",
                    (str(class_id), str(student_id), term), one=True)
    old = json.loads(existing["snapshot_json"] or "{}") if existing else {}
    version = int(old.get("version") or 1)
    if existing and existing["status"] == "published":
        version += 1
    dims = [{k: x[k] for k in (
        "id", "name", "short", "level", "level_text", "count", "pending", "evidence",
        "coverage", "progress")} for x in data["dims"]]
    highlights = [{k: x[k] for k in (
        "id", "date", "dim", "dim_name", "sub_item", "title", "fact", "source", "evidence")}
        for x in data["timeline"] if x["status"] == "confirmed"][:6]
    notes = ["%s：%s" % (x["name"], x["level_text"]) for x in dims if x["level"] in (None, "C")]
    if not notes:
        notes = ["五维均已有已确认记录，可继续补充代表性佐证。"]
    stu = data["student"]
    default_comment = "本学期形成 %d 条已确认成长记录，覆盖 %d 个维度。" % (
        data["counts"]["confirmed"], sum(1 for x in dims if x["level"]))
    content = {
        "version": version,
        "student": {"student_id": stu["student_id"], "name": stu["name"],
                    "gender": stu.get("gender", ""), "class_id": str(class_id)},
        "term": term,
        "generated_by": str(actor or ""),
        "counts": data["counts"], "dims": dims, "highlights": highlights,
        "certificates": [{k: x[k] for k in (
            "id", "name", "level", "issuer", "cert_no", "issued_on", "evidence", "status")}
            for x in data["certificates"] if x["status"] == "confirmed"],
        "evidence_notes": notes,
        "teacher_comment": str(old.get("teacher_comment") or default_comment),
    }
    now = db.now()
    rid = existing["id"] if existing else db.uid("gt_")
    payload = json.dumps(content, ensure_ascii=False)
    if existing:
        db.exec_("UPDATE growth_terms SET snapshot_json=?,status='draft',generated_at=?,"
                 "published_at=NULL WHERE id=?", (payload, now, rid))
    else:
        db.exec_("INSERT INTO growth_terms(id,class_id,student_id,term,snapshot_json,status,"
                 "generated_at,published_at) VALUES(?,?,?,?,?,'draft',?,NULL)",
                 (rid, str(class_id), str(student_id), term, payload, now))
    return get_report(class_id, student_id, term)


def edit_report(class_id, student_id, term, teacher_comment, actor):
    term = _valid_term(term)
    row = db.q("SELECT * FROM growth_terms WHERE class_id=? AND student_id=? AND term=?",
               (str(class_id), str(student_id), term), one=True)
    if not row:
        raise ValueError("请先生成报告草稿")
    if row["status"] == "published":
        raise ReportLockedError("已发布版本已冻结，请生成新版本后修改")
    content = json.loads(row["snapshot_json"] or "{}")
    comment = str(teacher_comment or "").strip()
    if len(comment) > 2000:
        raise ValueError("教师评语不能超过 2000 字")
    content["teacher_comment"] = comment
    content["edited_by"] = str(actor or "")
    db.exec_("UPDATE growth_terms SET snapshot_json=? WHERE id=?",
             (json.dumps(content, ensure_ascii=False), row["id"]))
    return get_report(class_id, student_id, term)


def publish_report(class_id, student_id, term, actor):
    term = _valid_term(term)
    row = db.q("SELECT * FROM growth_terms WHERE class_id=? AND student_id=? AND term=?",
               (str(class_id), str(student_id), term), one=True)
    if not row:
        raise ValueError("请先生成报告草稿")
    if row["status"] == "published":
        raise ReportLockedError("该学期报告已发布")
    content = json.loads(row["snapshot_json"] or "{}")
    version = int(content.get("version") or 1)
    now = db.now()
    content["published_at"] = now
    content["published_by"] = str(actor or "")
    payload = json.dumps(content, ensure_ascii=False)
    db.exec_many([
        ("UPDATE growth_terms SET snapshot_json=?,status='published',published_at=? WHERE id=?",
         (payload, now, row["id"])),
        ("INSERT OR REPLACE INTO growth_report_versions(id,report_id,class_id,student_id,term,"
         "version,snapshot_json,status,created_by,created_at,published_at) "
         "VALUES(?,?,?,?,?,?,?,'published',?,?,?)",
         (db.uid("gv_"), row["id"], str(class_id), str(student_id), term, version,
          payload, str(actor or ""), now, now)),
    ])
    return get_report(class_id, student_id, term)
