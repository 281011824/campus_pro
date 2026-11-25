# -*- coding: utf-8 -*-
"""政教处 · 学生德育问题「自动识别 + 标注」数据结构。

设计目标
--------
现有 `/api/v1/deyu/stats` 的重点名单（focus）是**实时计算**结果：
页面关掉就没有了，无法复核、无法追踪处理过程。本模块把识别结果**持久化**，
形成「规则 → 识别 → 证据 → 标注 → 复核/结案」的闭环。

分层（与既有表的关系）
--------------------
1. 事件层（已有）`dom_behavior`：原始事实；仅 `confirmed` 进入识别，pending/void 不用。
2. 规则层 `moral_issue_rules`：识别规则 = 对象 + 指标 + 阈值 + 窗口 + 严重度 + 自动标签。
   种子规则与统计页现有 focus 口径一一对应（累计扣分 / 同类重复 / 连续下降 / 班级净分）。
3. 识别层 `moral_issues`：一条「问题」，对象为学生或班级；携带原因、统计快照、状态机。
   唯一键 (rule_code, subject_type, class_id, student_id, period_start, period_end)
   保证同一周期重复识别只更新 `last_seen` 与证据，不产生重复问题单；
   已被人工排除(dismissed)或结案(resolved)的问题不会被自动识别复活。
4. 证据层 `moral_issue_evidences`：问题 ↔ 事件多对多，冗余 event_date/points/fact 快照，
   即使原事件后续被修改，复核时仍可追溯当时依据。
5. 标注层 `moral_issue_labels`：标签（考勤纪律 / 课堂纪律 / 同伴冲突 / 需关怀 …），
   source=auto 由规则自动打标，source=manual 由政教处人工补标；(issue_id,label) 唯一。

状态机
------
open（自动识别，待复核）
  ├─ confirm  → confirmed（纳入重点名单）
  │               └─ resolve → resolved（已结案，保留历史）
  └─ dismiss  → dismissed（误报排除，不进统计与名单）

红线（与需求基线一致）
--------------------
- 识别结果只用于「关注与标注」，不生成综合素质总分、不输出任何名次；
- 分值沿用德育量化口径（学生基准 100），本模块不改写 `dom_behavior`；
- 权限在 API 层控制：政教处全校域、班主任仅本班；本模块不做越权读取。

接线方式
--------
识别引擎直接复用 `website/app/api/v1/files.py::deyu_stats()` 的 focus 输出，
调用 `record_focus(focus, start, end)` 批量落库即可，无需另写一套规则计算。
"""

import json

from tasks.shared import db

SUBJECT_TYPES = ("student", "class")
STATUSES = ("open", "confirmed", "dismissed", "resolved")
SEVERITIES = {1: "提示", 2: "警告", 3: "严重"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS moral_issue_rules (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  subject_type TEXT NOT NULL CHECK(subject_type IN ('student','class')),
  category TEXT NOT NULL DEFAULT '',
  metric TEXT NOT NULL,
  threshold REAL NOT NULL,
  window_days INTEGER NOT NULL DEFAULT 7,
  severity INTEGER NOT NULL DEFAULT 2 CHECK(severity BETWEEN 1 AND 3),
  auto_label TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  remark TEXT NOT NULL DEFAULT '',
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS moral_issues (
  id TEXT PRIMARY KEY,
  rule_code TEXT NOT NULL,
  subject_type TEXT NOT NULL CHECK(subject_type IN ('student','class')),
  class_id TEXT NOT NULL,
  student_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  severity INTEGER NOT NULL DEFAULT 2 CHECK(severity BETWEEN 1 AND 3),
  status TEXT NOT NULL DEFAULT 'open'
    CHECK(status IN ('open','confirmed','dismissed','resolved')),
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  score INTEGER NOT NULL DEFAULT 0,
  reasons TEXT NOT NULL DEFAULT '[]',
  snapshot TEXT NOT NULL DEFAULT '{}',
  detected_by TEXT NOT NULL DEFAULT 'auto',
  first_seen TEXT,
  last_seen TEXT,
  reviewed_by TEXT NOT NULL DEFAULT '',
  reviewed_at TEXT,
  review_note TEXT NOT NULL DEFAULT '',
  resolved_by TEXT NOT NULL DEFAULT '',
  resolved_at TEXT,
  resolution TEXT NOT NULL DEFAULT '',
  created_at TEXT,
  updated_at TEXT,
  UNIQUE(rule_code, subject_type, class_id, student_id, period_start, period_end)
);
CREATE INDEX IF NOT EXISTS idx_moral_issues_status ON moral_issues(status, severity);
CREATE INDEX IF NOT EXISTS idx_moral_issues_student ON moral_issues(class_id, student_id);
CREATE INDEX IF NOT EXISTS idx_moral_issues_period ON moral_issues(period_end);

CREATE TABLE IF NOT EXISTS moral_issue_evidences (
  issue_id TEXT NOT NULL,
  behavior_id TEXT NOT NULL,
  event_date TEXT,
  points INTEGER NOT NULL DEFAULT 0,
  fact TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(issue_id, behavior_id)
);
CREATE INDEX IF NOT EXISTS idx_moral_issue_ev_behavior ON moral_issue_evidences(behavior_id);

CREATE TABLE IF NOT EXISTS moral_issue_labels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issue_id TEXT NOT NULL,
  label TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'auto' CHECK(source IN ('auto','manual')),
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT,
  UNIQUE(issue_id, label)
);
"""

# 与统计页 focus 口径一致的种子规则（阈值与 files.py 中 FOCUS_* 常量相同）
DEFAULT_RULES = [
    ("STU_NEG_TOTAL", "学生周期累计扣分超阈值", "student", "综合",
     "negative_total", -10, 7, 3, "重点关注"),
    ("STU_CATEGORY_REPEAT", "同类问题重复发生", "student", "",
     "category_repeat", 3, 7, 2, "重复违纪"),
    ("STU_NET_DECLINE", "净分连续两个周期下降", "student", "综合",
     "net_decline", 2, 7, 2, "趋势下滑"),
    ("CLASS_NET_LOW", "班级周期净分过低", "class", "综合",
     "class_net", -20, 7, 3, "班级预警"),
]


def init():
    """幂等建表 + 播种规则；重复调用不报错、不覆盖已有规则。"""
    c = db.connect()
    try:
        c.executescript(SCHEMA)
        c.commit()
    finally:
        c.close()
    _seed_rules()


def _seed_rules():
    now = db.now()
    stmts = [
        ("INSERT OR IGNORE INTO moral_issue_rules"
         "(code,name,subject_type,category,metric,threshold,window_days,severity,"
         "auto_label,enabled,remark,created_at,updated_at) "
         "VALUES(?,?,?,?,?,?,?,?,?,1,'',?,?)",
         (code, name, st, cat, metric, th, win, sev, label, now, now))
        for code, name, st, cat, metric, th, win, sev, label in DEFAULT_RULES
    ]
    db.exec_many(stmts)


def _loads(text, default):
    try:
        return json.loads(text or "")
    except (TypeError, ValueError):
        return default


def get_rule(code):
    row = db.q("SELECT * FROM moral_issue_rules WHERE code=?", (code,), one=True)
    return dict(row) if row else None


def list_rules(enabled_only=False):
    sql = "SELECT * FROM moral_issue_rules"
    if enabled_only:
        sql += " WHERE enabled=1"
    return [dict(r) for r in db.q(sql + " ORDER BY severity DESC, code")]


def get(issue_id):
    """问题详情：含证据与标签。"""
    row = db.q("SELECT * FROM moral_issues WHERE id=?", (issue_id,), one=True)
    if not row:
        return None
    it = dict(row)
    it["reasons"] = _loads(it["reasons"], [])
    it["snapshot"] = _loads(it["snapshot"], {})
    it["severity_label"] = SEVERITIES.get(it["severity"], "提示")
    it["evidences"] = [dict(r) for r in db.q(
        "SELECT * FROM moral_issue_evidences WHERE issue_id=? ORDER BY event_date",
        (issue_id,))]
    it["labels"] = [dict(r) for r in db.q(
        "SELECT label,source,created_by,created_at FROM moral_issue_labels "
        "WHERE issue_id=? ORDER BY id", (issue_id,))]
    return it


def list_issues(status="", class_id="", student_id="", subject_type="", limit=200):
    where, args = [], []
    if status:
        where.append("status=?"); args.append(status)
    if class_id:
        where.append("class_id=?"); args.append(class_id)
    if student_id:
        where.append("student_id=?"); args.append(student_id)
    if subject_type:
        where.append("subject_type=?"); args.append(subject_type)
    sql = "SELECT * FROM moral_issues"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY severity DESC, last_seen DESC LIMIT ?"
    args.append(int(limit or 200))
    items = []
    for r in db.q(sql, tuple(args)):
        it = dict(r)
        it["reasons"] = _loads(it["reasons"], [])
        it.pop("snapshot", None)
        it["labels"] = []
        items.append(it)
    if items:
        by_id = {it["id"]: it for it in items}
        placeholders = ",".join("?" for _ in by_id)
        for row in db.q(
                "SELECT issue_id,label FROM moral_issue_labels WHERE issue_id IN ("
                + placeholders + ") ORDER BY id", tuple(by_id)):
            by_id[row["issue_id"]]["labels"].append(row["label"])
    return items


def count_open():
    row = db.q("SELECT COUNT(*) AS n FROM moral_issues WHERE status='open'", one=True)
    return int(row["n"]) if row else 0


def upsert_issue(rule_code, subject_type, class_id, student_id="", title="",
                 period_start="", period_end="", score=0, reasons=None,
                 snapshot=None, evidences=None, detected_by="auto"):
    """识别写入（幂等）。

    同唯一键已存在：更新 last_seen/score/reasons/snapshot 并合并证据；
    但 status 保持原值 —— 人工已排除或已结案的问题不被自动识别复活。
    返回 (issue_id, created: bool)。
    """
    if subject_type not in SUBJECT_TYPES:
        raise ValueError("subject_type 不合法")
    rule = get_rule(rule_code)
    if not rule:
        raise ValueError("识别规则不存在: %s" % rule_code)
    now = db.now()
    reasons = reasons or []
    snapshot = snapshot or {}
    category = rule["category"]
    if not category and snapshot.get("category"):
        category = snapshot["category"]
    title = title or ("%s %s" % (class_id, rule["name"]))
    existing = db.q(
        "SELECT id,status,category FROM moral_issues WHERE rule_code=? AND subject_type=? "
        "AND class_id=? AND student_id=? AND period_start=? AND period_end=?",
        (rule_code, subject_type, class_id, student_id or "", period_start, period_end),
        one=True)
    if existing:
        issue_id = existing["id"]
        category = category or existing["category"]
        db.exec_(
            "UPDATE moral_issues SET last_seen=?,score=?,reasons=?,snapshot=?,"
            "title=?,category=?,updated_at=? WHERE id=?",
            (now, int(score or 0), json.dumps(reasons, ensure_ascii=False),
             json.dumps(snapshot, ensure_ascii=False), title, category, now, issue_id))
        created = False
    else:
        issue_id = db.uid("mi_")
        db.exec_(
            "INSERT INTO moral_issues(id,rule_code,subject_type,class_id,student_id,title,"
            "category,severity,status,period_start,period_end,score,reasons,snapshot,"
            "detected_by,first_seen,last_seen,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,'open',?,?,?,?,?,?,?,?,?,?)",
            (issue_id, rule_code, subject_type, class_id, student_id or "", title,
             category, rule["severity"], period_start, period_end, int(score or 0),
             json.dumps(reasons, ensure_ascii=False), json.dumps(snapshot, ensure_ascii=False),
             detected_by or "auto", now, now, now, now))
        created = True
    if rule["auto_label"]:
        add_label(issue_id, rule["auto_label"], source="auto", actor=detected_by)
    for ev in evidences or []:
        add_evidence(issue_id, ev)
    return issue_id, created


def add_evidence(issue_id, evidence):
    """登记一条证据事件（冗余快照，事件被改仍可追溯）。

    evidence: {behavior_id, event_date?, points?, fact?}
    缺省时回读 dom_behavior（仅允许 confirmed 事件作为证据）。
    """
    bid = str((evidence or {}).get("behavior_id") or "").strip()
    if not bid:
        raise ValueError("证据缺少 behavior_id")
    row = db.q("SELECT event_date,points,fact,status FROM dom_behavior WHERE id=?",
               (bid,), one=True)
    if not row:
        raise ValueError("证据源事件不存在")
    if row["status"] != "confirmed":
        raise ValueError("仅已确认事件可作为识别证据")
    db.exec_(
        "INSERT OR REPLACE INTO moral_issue_evidences(issue_id,behavior_id,event_date,points,fact) "
        "VALUES(?,?,?,?,?)",
        (issue_id, bid,
         evidence.get("event_date") or row["event_date"],
         int(evidence.get("points") if evidence.get("points") is not None
             else row["points"]),
         evidence.get("fact") or row["fact"]))


def add_label(issue_id, label, source="manual", actor=""):
    """打标；(issue_id,label) 唯一，重复打标静默成功。"""
    label = str(label or "").strip()
    if not label:
        return
    if source not in ("auto", "manual"):
        raise ValueError("source 不合法")
    db.exec_(
        "INSERT OR IGNORE INTO moral_issue_labels(issue_id,label,source,created_by,created_at) "
        "VALUES(?,?,?,?,?)", (issue_id, label, source, actor or "", db.now()))


def remove_label(issue_id, label):
    db.exec_("DELETE FROM moral_issue_labels WHERE issue_id=? AND label=? AND source='manual'",
             (issue_id, label))


def review(issue_id, action, actor="", note=""):
    """复核：action='confirm'（纳入重点）或 'dismiss'（误报排除）。

    仅 open 状态可复核，重复复核返回 409 语义（ValueError）。
    """
    it = get(issue_id)
    if not it:
        raise ValueError("问题不存在")
    if it["status"] != "open":
        raise ValueError("仅待复核(open)状态可执行复核，当前为 %s" % it["status"])
    if action not in ("confirm", "dismiss"):
        raise ValueError("action 不合法")
    status = "confirmed" if action == "confirm" else "dismissed"
    now = db.now()
    db.exec_("UPDATE moral_issues SET status=?,reviewed_by=?,reviewed_at=?,review_note=?,"
             "updated_at=? WHERE id=?", (status, actor or "", now, note or "", now, issue_id))
    db.audit({"user_id": actor or "deyu"}, "moral_issue_review", resource=issue_id,
             detail=json.dumps({"action": action, "note": note or ""}, ensure_ascii=False))
    return get(issue_id)


def resolve(issue_id, actor="", resolution=""):
    """结案：仅 confirmed 可结案；保留全部历史与证据。"""
    it = get(issue_id)
    if not it:
        raise ValueError("问题不存在")
    if it["status"] != "confirmed":
        raise ValueError("仅已确认(confirmed)状态可结案")
    now = db.now()
    db.exec_("UPDATE moral_issues SET status='resolved',resolved_by=?,resolved_at=?,"
             "resolution=?,updated_at=? WHERE id=?",
             (actor or "", now, resolution or "", now, issue_id))
    db.audit({"user_id": actor or "deyu"}, "moral_issue_resolve", resource=issue_id,
             detail=(resolution or "")[:200])
    return get(issue_id)


def reopen(issue_id, actor=""):
    """人工重开（dismissed/resolved → open），用于误排除或问题复发。"""
    it = get(issue_id)
    if not it:
        raise ValueError("问题不存在")
    if it["status"] not in ("dismissed", "resolved"):
        raise ValueError("仅已排除或已结案的问题可重开")
    db.exec_("UPDATE moral_issues SET status='open',updated_at=? WHERE id=?",
             (db.now(), issue_id))
    db.audit({"user_id": actor or "deyu"}, "moral_issue_reopen", resource=issue_id)
    return get(issue_id)


def record_focus(focus_items, period_start, period_end, detected_by="auto"):
    """把 deyu_stats 的 focus 列表批量落库（识别引擎与持久化之间的桥）。

    按统计结果显式返回的 rule_codes 落库，不依赖 reasons 展示文案。
    一个对象命中多条规则时生成多张问题单。
    返回 {"created": n, "updated": m, "issue_ids": [...]}。
    """
    created = updated = 0
    ids = []
    for item in focus_items or []:
        reasons = item.get("reasons") or []
        codes = list(dict.fromkeys(item.get("rule_codes") or []))
        for code in codes:
            snapshot = {"reasons": reasons}
            issue_id, is_new = upsert_issue(
                rule_code=code,
                subject_type=item.get("type") or "student",
                class_id=item.get("class_id") or "",
                student_id=item.get("id") if item.get("type") == "student" else "",
                title="%s · %s" % (item.get("class_name") or item.get("class_id") or "",
                                   item.get("name") or item.get("id") or ""),
                period_start=period_start, period_end=period_end,
                score=item.get("score") or 0, reasons=reasons, snapshot=snapshot,
                detected_by=detected_by)
            ids.append(issue_id)
            if is_new:
                created += 1
            else:
                updated += 1
    return {"created": created, "updated": updated, "issue_ids": ids}
